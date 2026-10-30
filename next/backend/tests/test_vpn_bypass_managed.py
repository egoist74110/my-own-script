"""Managed bypass: no real authorization, daemon control or route mutation."""

import ast
import asyncio
import base64
import copy
import json
import os
import plistlib
import shlex
import subprocess
import time

import httpx
import pytest

from toolbox_backend.adapters import vpn_bypass_privileged as privileged
from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.app import create_app
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.vpn_bypass import BypassSettingsWrite, BypassStatus, VpnBypassConfig
from toolbox_backend.services.vpn_bypass import VpnBypassService
from toolbox_backend.settings import Settings
from toolbox_backend.vpn import bypass_daemon as daemon
from toolbox_backend.vpn import bypass_installer as installer


def config(**changes):
    values = dict(enabled=True, gateway="192.168.8.1", interface="en0", targets=["1.2.3.4"])
    values.update(changes)
    return VpnBypassConfig(**values).model_dump()


class Managed:
    def __init__(self, installed=False):
        self.exists = installed
        self.calls = []
        self.failure = None

    def installed(self):
        return self.exists

    def status(self, config):
        return BypassStatus(installed=self.exists)

    def apply(self, action, config):
        self.calls.append((action, copy.deepcopy(config)))
        if self.failure:
            raise self.failure
        self.exists = True


async def service(tmp_path, installed=False):
    store = ConfigStore(tmp_path)
    await store.initialize()
    managed = Managed(installed)
    return VpnBypassService(store, managed), managed


@pytest.mark.asyncio
async def test_revision_conflict_precedes_authorization(tmp_path):
    app, managed = await service(tmp_path)
    for action in (app.activate, app.deactivate):
        with pytest.raises(SettingsError) as caught:
            await action(900)
        assert caught.value.code == "revision_conflict"
    assert managed.calls == []


@pytest.mark.asyncio
async def test_save_before_install_never_authorizes(tmp_path):
    app, managed = await service(tmp_path)
    saved = await app.update(BypassSettingsWrite(revision=0, settings=config()))
    assert saved.revision == 1
    assert managed.calls == []
    assert (await app.snapshot())["status"].state == "not_installed"
    await app.activate(1)
    assert managed.calls[0][0] == "activate"
    await app.deactivate(1)
    assert managed.calls[-1][0] == "deactivate"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_save_syncs_existing_installation(tmp_path, enabled):
    app, managed = await service(tmp_path, installed=True)
    await app.update(BypassSettingsWrite(revision=0, settings=config(enabled=enabled)))
    assert managed.calls[0][0] == ("activate" if enabled else "deactivate")
    assert managed.calls[0][1]["enabled"] is enabled


@pytest.mark.asyncio
async def test_sync_cancellation_preserves_saved_revision_and_reports_pending(tmp_path):
    app, managed = await service(tmp_path, installed=True)
    managed.failure = SettingsError("bypass_authorization_cancelled", "cancelled")
    with pytest.raises(SettingsError) as caught:
        await app.update(BypassSettingsWrite(revision=0, settings=config()))
    assert caught.value.code == "bypass_sync_failed"
    assert caught.value.extra["revision"] == 1
    assert "已保存" in caught.value.message and "实际状态" in caught.value.message
    saved = await app.store.read()
    assert saved.revision == 1 and saved.vpn_bypass.targets == ["1.2.3.4/32"]
    assert not (await app.snapshot())["status"].synced
    managed.failure = None
    await app.activate(1)
    assert app._sync_error is None


@pytest.mark.asyncio
async def test_daemon_recovery_is_not_masked_by_old_sync_error(tmp_path):
    app, managed = await service(tmp_path, installed=True)
    app._sync_error = "previous update failed"
    managed.status = lambda config: BypassStatus(
        installed=True, running=True, synced=True, state="active", message="verified"
    )
    snapshot = await app.snapshot()
    assert snapshot["status"].state == "active"
    assert snapshot["status"].synced
    assert not snapshot["status"].errors
    assert app._sync_error is None


@pytest.mark.asyncio
async def test_busy_and_cancelled_request_keep_action_serialized(tmp_path):
    app, managed = await service(tmp_path, installed=True)
    started, finish = __import__("threading").Event(), __import__("threading").Event()

    def apply(*args):
        started.set()
        assert finish.wait(5)

    managed.apply = apply
    task = asyncio.create_task(app.update(BypassSettingsWrite(revision=0, settings=config())))
    await asyncio.to_thread(started.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    with pytest.raises(SettingsError) as caught:
        await app.deactivate(1)
    assert caught.value.code == "bypass_busy"
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not app._action_lock.locked()


def decode_authorization(script, python_path="/usr/bin/python3"):
    line = script.splitlines()[1]
    prefix, suffix = 'do shell script "', '" with administrator privileges'
    assert line.startswith(prefix) and line.endswith(suffix)
    shell = line[len(prefix) : -len(suffix)].replace('\\"', '"').replace("\\\\", "\\")
    argv = shlex.split(shell)
    assert argv[:4] == [python_path, "-I", "-S", "-c"]
    tree = ast.parse(argv[4])
    # exec(compile(base64.b64decode(<literal>), ...))
    literal = tree.body[1].value.args[0].args[0].args[0].value
    return base64.b64decode(literal).decode()


def test_auth_quoting_keeps_injection_as_literal_data():
    path = "/Applications/a ' \" ; $(touch /tmp/NEVER) `id` \\ unicode猫.app"
    cfg = config(apps=[{"id": "a", "name": "a", "application_path": path}])
    script = privileged.authorization_script("activate", cfg)
    source = decode_authorization(script)
    tree = ast.parse(source, feature_version=(3, 9))
    call = tree.body[-1].value
    assert call.func.id == "execute"
    assert ast.literal_eval(call.args[0]) == "activate"
    assert json.loads(ast.literal_eval(call.args[2].args[0])) == cfg
    assert "/tmp/NEVER" not in script  # only encoded data crosses the shell
    assert "password" not in script
    ast.parse(ast.literal_eval(call.args[1]), feature_version=(3, 9))


def test_auth_payload_size_and_action_are_bounded():
    with pytest.raises(ValueError):
        privileged.authorization_script("activate;id", config())
    cfg = config(
        apps=[
            {"id": str(i), "name": "a", "application_path": "/" + "x" * 4000 + ".app"}
            for i in range(32)
        ]
    )
    with pytest.raises(SettingsError) as caught:
        privileged.authorization_script("activate", cfg)
    assert caught.value.code == "bypass_payload_too_large"


@pytest.mark.parametrize(
    "stderr,code",
    [
        ("execution error: User canceled. (-128)", "bypass_authorization_cancelled"),
        ("admin denied (-60005)", "bypass_authorization_failed"),
    ],
)
def test_authorization_failures_are_clear_and_not_leaked(monkeypatch, stderr, code):
    calls = []
    monkeypatch.setattr(privileged, "preflight", lambda: "/usr/bin/python3")

    def run(argv, **options):
        calls.append((argv, options))
        return subprocess.CompletedProcess(argv, 1, "", stderr)

    monkeypatch.setattr(privileged.subprocess, "run", run)
    with pytest.raises(SettingsError) as caught:
        privileged.ManagedBypass().apply("activate", config())
    assert caught.value.code == code
    assert stderr not in caught.value.message
    assert calls[0][0] == ["/usr/bin/osascript", "-"]
    assert "with administrator privileges" in calls[0][1]["input"]
    assert calls[0][1].get("shell", False) is False


def test_untrusted_runtime_fails_before_authorization(monkeypatch):
    monkeypatch.setattr(privileged.sys, "platform", "darwin")
    monkeypatch.setattr(installer, "protected", lambda *a, **k: None)
    calls = []

    def run(argv, **options):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "untrusted ancestor")

    monkeypatch.setattr(privileged.subprocess, "run", run)
    with pytest.raises(SettingsError) as caught:
        privileged.ManagedBypass().apply("activate", config())
    assert caught.value.code == "bypass_runtime_untrusted"
    assert all(argv[0] != "/usr/bin/osascript" for argv in calls)


def test_existing_clt_runtime_is_preflighted_and_pinned(tmp_path, monkeypatch):
    candidate = tmp_path / "bin/python3.9"
    candidate.parent.mkdir()
    candidate.touch()
    monkeypatch.setattr(privileged.sys, "platform", "darwin")
    monkeypatch.setattr(privileged.Path, "glob", lambda *a: [candidate])
    monkeypatch.setattr(installer, "protected", lambda *a, **k: None)
    calls = []

    def run(argv, **options):
        calls.append((argv, options))
        return subprocess.CompletedProcess(argv, 0, str(candidate) + "\n", "")

    monkeypatch.setattr(privileged.subprocess, "run", run)
    selected = privileged.preflight()
    assert selected == str(candidate)
    assert calls[0][0][:3] == [selected, "-I", "-S"]
    assert len(calls) == 1
    source = decode_authorization(
        privileged.authorization_script("activate", config(), selected), selected
    )
    tree = ast.parse(source, feature_version=(3, 9))
    assignment = tree.body[-2]
    assert assignment.targets[0].id == "PYTHON"
    assert ast.literal_eval(assignment.value) == selected


def test_user_writable_candidate_is_never_executed(tmp_path, monkeypatch):
    candidate = tmp_path / "python3.9"
    candidate.touch()
    monkeypatch.setattr(privileged.sys, "platform", "darwin")
    monkeypatch.setattr(privileged.Path, "glob", lambda *a: [candidate])
    calls = []

    def protected(path, **kwargs):
        if str(path).startswith(str(tmp_path)):
            raise RuntimeError("user-writable candidate")

    monkeypatch.setattr(installer, "protected", protected)

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "untrusted system runtime")

    monkeypatch.setattr(privileged.subprocess, "run", run)
    with pytest.raises(SettingsError):
        privileged.preflight()
    assert all(argv[0] != str(candidate) for argv in calls)
    assert all(argv[0] != "/usr/bin/osascript" for argv in calls)


@pytest.mark.parametrize("action", ["activate", "deactivate"])
def test_installer_stops_before_writes_and_reconcile_preserves_journal(
    tmp_path, monkeypatch, action
):
    root = tmp_path / "installed"
    root.mkdir()
    journal = root / "state.json"
    journal.write_text('{"pending": "must retain even on conflicts"}')
    plist = tmp_path / "daemon.plist"
    calls = []
    monkeypatch.setattr(installer, "ROOT", root)
    monkeypatch.setattr(installer, "PLIST", plist)
    monkeypatch.setattr(installer, "runtime_preflight", lambda: calls.append("preflight"))
    monkeypatch.setattr(installer, "protected", lambda *a, **k: None)
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(installer, "stop_job", lambda: calls.append("stop"))

    def lock(name, wait=False):
        calls.append("lock:" + name)
        return os.open(tmp_path / name, os.O_CREAT | os.O_RDWR, 0o600)

    def run(argv, **kwargs):
        calls.append(argv)
        assert calls.index("stop") < calls.index("lock:lock")
        assert (root / "helper.py").read_text() == "reviewed-helper"
        assert json.loads((root / "config.json").read_text())["enabled"] == (action == "activate")
        return subprocess.CompletedProcess(argv, 2, "conflict", "")

    monkeypatch.setattr(installer, "lock", lock)
    monkeypatch.setattr(installer, "command", run)
    # Disable needs no gateway and no discovery, and stores a disabled snapshot.
    installer.execute(action, "reviewed-helper", config(gateway=None, interface=None))
    helper_call = next(c for c in calls if isinstance(c, list) and c[0] == "/usr/bin/python3")
    assert helper_call[-1] == ("sweep" if action == "activate" else "undo")
    assert journal.read_text() == '{"pending": "must retain even on conflicts"}'
    data = plistlib.loads(plist.read_bytes())
    assert data["Disabled"] is (action == "deactivate")
    assert data["RunAtLoad"] is (action == "activate")
    assert (root.stat().st_mode & 0o777) == 0o755
    assert ((root / "helper.py").stat().st_mode & 0o777) == 0o600
    assert ((root / "config.json").stat().st_mode & 0o777) == 0o600
    assert (plist.stat().st_mode & 0o777) == 0o644
    assert any(c == ["/bin/launchctl", "disable", installer.JOB] for c in calls) == (
        action == "deactivate"
    )
    assert any(isinstance(c, list) and "bootstrap" in c for c in calls) == (action == "activate")


def observation(cfg):
    return {
        "config_hash": daemon.config_hash(cfg),
        "enabled": cfg["enabled"],
        "last_sweep_at": time.time(),
        "pid": 123,
        "events": [],
        "errors": [],
        "targets": [
            {
                "target": "1.2.3.4/32",
                "gateway": cfg["gateway"],
                "interface": cfg["interface"],
                "owned": True,
                "verified": True,
            }
        ],
    }


@pytest.mark.parametrize(
    "case,state",
    [
        ("healthy", "active"),
        ("stale", "pending"),
        ("mismatch", "pending"),
        ("pid_mismatch", "pending"),
        ("zero", "degraded"),
        ("foreign", "degraded"),
        ("missing", "degraded"),
        ("down", "degraded"),
        ("unowned", "degraded"),
        ("failure", "error"),
        ("stopped", "stopped"),
        ("pending_conflict", "degraded"),
    ],
)
def test_status_requires_fresh_matching_job_and_actual_owned_routes(monkeypatch, case, state):
    cfg = config(targets=[] if case == "zero" else ["1.2.3.4"])
    value = observation(cfg)
    table = {
        "1.2.3.4/32": {"gateway": cfg["gateway"], "interface": cfg["interface"], "flags": "UGHS"}
    }
    if case == "stale":
        value["last_sweep_at"] -= 1000
    if case == "mismatch":
        value["config_hash"] = "old"
    if case == "pid_mismatch":
        value["pid"] = 99
    if case == "zero":
        value["targets"] = []
    if case == "foreign":
        table["1.2.3.4/32"]["interface"] = "utun4"
    if case == "missing":
        table = {}
    if case == "down":
        table["1.2.3.4/32"]["flags"] = "GHS"
    if case == "unowned":
        value["targets"][0]["owned"] = False
    if case == "failure":
        value["errors"] = ["failed"]
    if case == "pending_conflict":
        value["events"] = [["1.2.3.4/32", "pending_conflict_manual_recovery"]]
    managed = privileged.ManagedBypass()
    monkeypatch.setattr(managed, "installed", lambda: True)
    monkeypatch.setattr(managed, "read_public_status", lambda: value)
    monkeypatch.setattr(managed, "job_pid", lambda: None if case == "stopped" else 123)
    monkeypatch.setattr(daemon, "route_table", lambda: table)
    result = managed.status(cfg)
    assert result.state == state
    if case in {"foreign", "missing", "unowned"}:
        assert not result.targets[0].verified
    if case in {"mismatch", "stopped"}:
        assert not result.synced


def test_disabled_snapshot_does_not_look_synced_when_saved_setting_enabled(monkeypatch):
    cfg = config()
    value = observation(config(enabled=False))
    value["targets"] = []
    managed = privileged.ManagedBypass()
    monkeypatch.setattr(managed, "installed", lambda: True)
    monkeypatch.setattr(managed, "read_public_status", lambda: value)
    monkeypatch.setattr(managed, "job_pid", lambda: None)
    monkeypatch.setattr(daemon, "route_table", dict)
    result = managed.status(cfg)
    assert result.state == "stopped" and not result.synced and not result.running


def test_job_pid_requires_launchctl_identity_and_process_liveness(monkeypatch):
    managed = privileged.ManagedBypass()
    monkeypatch.setattr(
        privileged.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, " state = running\n pid = 123\n", ""),
    )
    monkeypatch.setattr(privileged.os, "kill", lambda pid, signal: None)
    assert managed.job_pid() == 123

    def gone(*args):
        raise ProcessLookupError()

    monkeypatch.setattr(privileged.os, "kill", gone)
    assert managed.job_pid() is None


def test_recoverable_discovery_error_publishes_fresh_public_status_then_recovers(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(daemon, "ROOT", tmp_path)
    monkeypatch.setattr(daemon, "protected", lambda *a, **k: None)
    monkeypatch.setattr(daemon, "route_table", dict)
    monkeypatch.setattr(daemon, "physical_gateway", lambda *args: ("192.168.8.1", "en0"))

    def broken(*args, **kwargs):
        raise OSError("private path should not leak")

    monkeypatch.setattr(daemon, "discover", broken)
    assert daemon.sweep_once(config(targets=[]), "loop") == 1
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["errors"] and not status["targets"]
    assert "private path" not in json.dumps(status)
    assert time.time() - status["last_sweep_at"] < 5
    assert (tmp_path / "status.json").stat().st_mode & 0o777 == 0o644
    monkeypatch.setattr(daemon, "discover", lambda *args, **kwargs: [])
    assert daemon.sweep_once(config(targets=[]), "loop") == 0
    assert json.loads((tmp_path / "status.json").read_text())["errors"] == []
    assert (tmp_path / "state.json").stat().st_mode & 0o777 == 0o600


def test_daemon_loop_continues_after_recoverable_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "ROOT", tmp_path)
    monkeypatch.setattr(daemon, "protected", lambda *a, **k: None)
    monkeypatch.setattr(daemon.sys, "platform", "darwin")
    monkeypatch.setattr(daemon.sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(daemon.os, "geteuid", lambda: 0)
    monkeypatch.setattr(daemon, "read_json", lambda path: config(targets=[]))
    results = []

    def sweep(*args):
        results.append(len(results))
        return 1 if len(results) == 1 else 0

    monkeypatch.setattr(daemon, "sweep_once", sweep)

    def sleep(*args):
        if len(results) == 2:
            raise KeyboardInterrupt()

    monkeypatch.setattr(daemon.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        daemon.main(["loop"])
    assert len(results) == 2


@pytest.mark.asyncio
async def test_activate_deactivate_api_and_saved_sync_error(tmp_path):
    app = create_app(Settings(token="test-token", port=12345, data_dir=tmp_path))
    managed = Managed()
    app.state.vpn_bypass_service.managed = managed
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:12345"
    ) as client:
        assert (
            await client.post("/api/vpn/bypass/activate", json={"revision": 0})
        ).status_code == 401
        client.headers["Authorization"] = "Bearer test-token"
        assert (
            await client.patch(
                "/api/vpn/bypass/settings", json={"revision": 0, "settings": config()}
            )
        ).status_code == 200
        conflict = await client.post("/api/vpn/bypass/activate", json={"revision": 0})
        assert conflict.status_code == 409 and not managed.calls
        assert (
            await client.post("/api/vpn/bypass/activate", json={"revision": 1})
        ).status_code == 200
        assert (
            await client.post("/api/vpn/bypass/deactivate", json={"revision": 1})
        ).status_code == 200
        managed.failure = SettingsError("bypass_authorization_cancelled", "cancelled")
        failed = await client.patch(
            "/api/vpn/bypass/settings", json={"revision": 1, "settings": config(enabled=False)}
        )
        assert failed.status_code == 409
        assert failed.json()["detail"]["code"] == "bypass_sync_failed"
        snapshot = (await client.get("/api/vpn/bypass")).json()
        assert snapshot["revision"] == 2 and snapshot["status"]["synced"] is False


@pytest.mark.asyncio
async def test_saved_sync_reports_initial_repair_failure(tmp_path):
    app, managed = await service(tmp_path, installed=True)
    managed.status = lambda config: BypassStatus(installed=True, state="error", errors=["failed"])
    with pytest.raises(SettingsError) as caught:
        await app.update(BypassSettingsWrite(revision=0, settings=config()))
    assert caught.value.code == "bypass_sync_failed"
    assert caught.value.extra["cause"] == "bypass_apply_failed"
    assert (await app.store.read()).revision == 1
    assert not (await app.snapshot())["status"].synced


def test_stop_failure_cannot_proceed_to_write_or_undo(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    root.mkdir()
    original = root / "config.json"
    original.write_text("original")
    monkeypatch.setattr(installer, "ROOT", root)
    monkeypatch.setattr(installer, "PLIST", tmp_path / "job.plist")
    monkeypatch.setattr(installer, "runtime_preflight", lambda: None)
    monkeypatch.setattr(installer, "protected", lambda *a, **k: None)
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        installer, "lock", lambda *a, **k: os.open(tmp_path / "lock", os.O_CREAT | os.O_RDWR, 0o600)
    )

    def stop():
        raise RuntimeError("still running")

    monkeypatch.setattr(installer, "stop_job", stop)
    with pytest.raises(RuntimeError, match="still running"):
        installer.execute("deactivate", "reviewed", config())
    assert original.read_text() == "original"
    assert not (root / "helper.py").exists()


def test_installer_protection_rejects_symlink_and_user_writable_parent(tmp_path):
    file = tmp_path / "file"
    file.write_text("reviewed")
    link = tmp_path / "link"
    link.symlink_to(file)
    for path in (file, link):
        with pytest.raises(RuntimeError, match="unprotected"):
            installer.protected(path)
