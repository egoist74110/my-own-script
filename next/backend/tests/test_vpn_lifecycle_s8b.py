"""Faults at the real parent/worker seam, with all OS/browser operations replaced."""

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.adapters.vpn_browser import ChromeRegistry, ProcessLoginRunner
from toolbox_backend.api.services_schemas import NetworkInfo
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.vpn import VpnConfig
from toolbox_backend.services.vpn import VpnService
from toolbox_backend.vpn.login_worker import encode_event


class Client:
    def resolve(self, bundle):
        return SimpleNamespace(app_path="/fake/client.app")

    async def open(self, bundle):
        pass

    async def restart(self, bundle, **kwargs):
        pass


class Registry:
    def __init__(self):
        self.records, self.cleaned = [], 0

    def record(self, identity):
        self.records.append(identity)

    async def cleanup(self):
        self.cleaned += 1


class Owner:
    def __init__(self, output=()):
        self.writes = []
        self.stdout = asyncio.StreamReader(limit=1 << 20)
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.stdin = self
        self.stopped = self.control_closed = self.closed = False
        for line in output:
            self.stdout.feed_data(line)
        self.on_write = lambda message: None

    def write(self, raw):
        message = json.loads(raw)
        self.writes.append(message)
        self.on_write(message)

    async def drain(self):
        pass

    def stop(self):
        self.stopped = True

    def close_control(self):
        self.control_closed = True

    async def close(self):
        self.closed = True


async def test_worker_environment_excludes_browser_injection(tmp_path, monkeypatch):
    blocked = {"PLAYWRIGHT_BROWSERS_PATH", "PLAYWRIGHT_CUSTOM_FLAG", "NODE_OPTIONS", "DEBUG"}
    for key in blocked:
        monkeypatch.setenv(key, "s8-test-value")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", str(tmp_path))
    environments = []

    async def factory(argv, cwd, **kwargs):
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import json,os; print(json.dumps(dict(os.environ)))",
            cwd=cwd, env=kwargs["env"], stdout=asyncio.subprocess.PIPE,
        )
        output, _ = await asyncio.wait_for(process.communicate(), 2)
        assert process.returncode == 0
        environments.append(json.loads(output))
        return Owner([encode_event("done")])

    runner = ProcessLoginRunner(
        tmp_path, Client(), process_factory=factory, registry=Registry(), path_extras=[]
    )
    await runner.run(VpnConfig(), "S8_FAKE_PASSWORD", None, asyncio.Event(), None)
    assert blocked.isdisjoint(environments[0])
    assert environments[0]["PATH"] == "/usr/bin:/bin"
    assert environments[0]["HOME"] == str(tmp_path)


@pytest.mark.parametrize("relogin", [True, False])
async def test_existing_tunnel_only_shortcuts_normal_connect(tmp_path, relogin):
    started, release = asyncio.Event(), asyncio.Event()
    probes_after_login = []
    login_finished = False

    class Store:
        data_dir = tmp_path

        async def read(self):
            return SimpleNamespace(vpn=VpnConfig(window_automation="connect"), revision=0)

    class Login:
        async def run(self, *args):
            nonlocal login_finished
            started.set()
            await release.wait()
            login_finished = True

    class NoNativeActions(Client):
        async def open(self, bundle):
            pytest.fail("relogin must go directly to login")

        async def restart(self, bundle, **kwargs):
            pytest.fail("relogin must go directly to login")

    async def network(**kwargs):
        probes_after_login.append(login_finished)
        await asyncio.sleep(0)
        return NetworkInfo(vpn_ip="10.254.0.9")

    credentials = MemoryCredentials()
    credentials.set("vpn_password", "S8_FAKE_PASSWORD")
    service = VpnService(
        Store(), credentials, None, NoNativeActions(), None,
        login_runner=Login(), network_reader=network,
    )
    try:
        run = await service.start(relogin=relogin)
        task = service._task
        if relogin:
            waiter = asyncio.create_task(started.wait())
            try:
                done, _ = await asyncio.wait(
                    [waiter, task], timeout=1, return_when=asyncio.FIRST_COMPLETED
                )
                assert waiter in done, "existing tunnel bypassed LoginRunner"
                assert service.get_run(run.run_id).state == "running"
            finally:
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)
                release.set()
        await asyncio.wait_for(task, 1)
        assert service.get_run(run.run_id).state == "succeeded"
        assert started.is_set() == relogin
        if relogin:
            assert any(probes_after_login), "success requires a probe after login completes"
    finally:
        release.set()
        await service.close()


async def test_runner_only_sends_credentials_via_stdin_and_handles_mfa(tmp_path, monkeypatch):
    owner = Owner([encode_event("need_mfa", attempt=1)])
    launches = []
    password, seed, code = "S8_FAKE_PASSWORD_421", "S8_FAKE_SEED_421", "918273"
    monkeypatch.setenv("S8_UNRELATED_NAME", password)
    monkeypatch.setenv("S8_OTHER_NAME", seed)
    registry = Registry()

    async def factory(argv, cwd, **kwargs):
        launches.append((argv, kwargs["env"]))
        return owner

    async def mfa():
        return code

    owner.on_write = lambda message: (
        owner.stdout.feed_data(encode_event("done")) if message.get("event") == "mfa" else None
    )
    runner = ProcessLoginRunner(tmp_path, Client(), process_factory=factory, registry=registry)
    await runner.run(VpnConfig(), password, seed, asyncio.Event(), mfa)
    argv, environment = launches[0]
    rendered = json.dumps([argv, environment])
    assert all(secret not in rendered for secret in (password, seed, code))
    assert owner.writes[0]["password"] == password
    assert "seed" not in owner.writes[0]
    assert owner.writes[1] == {"event": "mfa", "code": code}
    assert owner.stopped and owner.control_closed and owner.closed
    assert registry.cleaned == 1


async def test_cancel_event_interrupts_silent_worker_and_releases_owner(tmp_path):
    owner, registry, cancel = Owner(), Registry(), asyncio.Event()

    async def factory(*args, **kwargs):
        return owner

    runner = ProcessLoginRunner(tmp_path, Client(), process_factory=factory, registry=registry)
    task = asyncio.create_task(runner.run(VpnConfig(), "fake", None, cancel, None))
    await asyncio.sleep(0)
    cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert owner.closed and owner.control_closed and registry.cleaned == 1


@pytest.mark.parametrize(
    "line",
    [b"{}\n", b"not json\n", b"x" * 65536 + b"\n", b'{"event":"step","step":"password-secret"}\n'],
)
async def test_invalid_or_oversized_worker_output_is_generic_and_reclaimed(tmp_path, line):
    owner, registry = Owner([line]), Registry()

    async def factory(*args, **kwargs):
        return owner

    runner = ProcessLoginRunner(tmp_path, Client(), process_factory=factory, registry=registry)
    with pytest.raises(SettingsError) as exc:
        await runner.run(VpnConfig(), "fake", None, asyncio.Event(), None)
    assert exc.value.code == "login_timeout"
    assert "password-secret" not in str(exc.value)
    assert owner.closed and registry.cleaned == 1


async def test_manual_service_mfa_is_connected_to_real_parent_protocol(tmp_path):
    owner, registry = Owner([encode_event("need_mfa", attempt=1)]), Registry()
    connected = False
    requested = asyncio.Event()
    events = []

    class Store:
        data_dir = tmp_path

        async def read(self):
            return SimpleNamespace(vpn=VpnConfig(rung_timeout_s=5), revision=0)

    class Hub:
        def publish_vpn(self, kind, data):
            events.append((kind, data))
            if kind == "vpn.mfa_required":
                requested.set()

    async def factory(*args, **kwargs):
        return owner

    def mfa_written(message):
        nonlocal connected
        if message.get("event") == "mfa":
            connected = True
            owner.stdout.feed_data(encode_event("done"))

    owner.on_write = mfa_written
    client = Client()
    runner = ProcessLoginRunner(tmp_path, client, process_factory=factory, registry=registry)
    credentials = MemoryCredentials()
    credentials.set("vpn_password", "S8_FAKE_PASSWORD")

    async def network(**kwargs):
        return NetworkInfo(vpn_ip="10.254.0.9" if connected else None)

    service = VpnService(
        Store(), credentials, None, client, Hub(), login_runner=runner, network_reader=network
    )
    try:
        run = await service.start(relogin=True)
        await asyncio.wait_for(requested.wait(), 15)
        with pytest.raises(SettingsError) as exc:
            await service.submit_mfa("wrong-run", "123456")
        assert exc.value.code == "vpn_mfa_required"
        await service.submit_mfa(run.run_id, "123456")
        await asyncio.wait_for(service._task, 2)
        assert service.get_run(run.run_id).state == "succeeded"
        assert owner.writes[1] == {"event": "mfa", "code": "123456"}
        assert any(
            kind == "vpn.mfa_required" and data["expires_in_s"] == 120 for kind, data in events
        )
        assert "S8_FAKE_PASSWORD" not in json.dumps(events, default=str)
    finally:
        await service.close()
    assert owner.closed and registry.cleaned == 1


async def test_startup_cleanup_uses_recorded_identity_only(tmp_path):
    records = [{"pid": 765432, "lstart": "old-start"}]
    folder = tmp_path / "vpn"
    folder.mkdir(mode=0o700)
    (folder / "chrome-processes.json").write_text(json.dumps(records))
    calls = []

    async def inspect(pid):
        return {
            "pid": pid,
            "pgid": pid,
            "lstart": "reused-start",
            "command": f"chrome --user-data-dir={folder}/chrome-profile",
        }

    registry = ChromeRegistry(tmp_path, inspect=inspect, killpg=lambda *x: calls.append(x))
    runner = ProcessLoginRunner(tmp_path, Client(), registry=registry)
    await runner.initialize()
    assert calls == []
    assert json.loads((folder / "chrome-processes.json").read_text()) == []


def test_failed_identity_journal_write_preserves_previous_record_and_no_temp(tmp_path, monkeypatch):
    import toolbox_backend.adapters.vpn_browser as browser

    registry = ChromeRegistry(tmp_path)
    registry.record({"pid": 987651, "lstart": "old-start"})
    original = registry.path.read_text()
    registry.records.append({"pid": 987652, "lstart": "new-start"})

    def fail_fsync(fd):
        raise OSError("fake disk failure")

    monkeypatch.setattr(browser.os, "fsync", fail_fsync)
    with pytest.raises(OSError):
        registry.save()
    assert registry.path.read_text() == original
    assert sorted(path.name for path in registry.path.parent.iterdir()) == ["chrome-processes.json"]


async def test_window_connection_is_reprobed_before_browser_login(tmp_path):
    connected = False

    class Store:
        data_dir = tmp_path

        async def read(self):
            return SimpleNamespace(
                vpn=VpnConfig(rung_timeout_s=5, window_automation="connect"), revision=0
            )

    class Window:
        async def permissions(self):
            return {"screen_recording": "granted", "accessibility": "granted"}

        async def connect(self, mode):
            nonlocal connected
            connected = True
            return "connect"

    class Login:
        async def run(self, *args):
            pytest.fail("successful native connect must not start browser login")

    async def network(**kwargs):
        return NetworkInfo(vpn_ip="10.254.0.8" if connected else None)

    credentials = MemoryCredentials()
    credentials.set("vpn_password", "S8_FAKE_PASSWORD")
    service = VpnService(
        Store(),
        credentials,
        None,
        Client(),
        None,
        login_runner=Login(),
        window_automation=Window(),
        network_reader=network,
    )
    try:
        run = await service.start()
        await asyncio.wait_for(service._task, 15)
        assert service.get_run(run.run_id).state == "succeeded"
        assert service.get_run(run.run_id).ip == "10.254.0.8"
    finally:
        await service.close()


async def test_profile_clear_refuses_linked_parent_without_touching_target(tmp_path):
    data_dir, outside = tmp_path / "data", tmp_path / "outside"
    data_dir.mkdir(mode=0o700)
    outside.mkdir(mode=0o700)
    profile = outside / "chrome-profile"
    profile.mkdir()
    sentinel = profile / "Cookies"
    sentinel.write_text("S8_FAKE_COOKIE")
    (data_dir / "vpn").symlink_to(outside, target_is_directory=True)
    service = VpnService(
        SimpleNamespace(data_dir=data_dir),
        None,
        None,
        Client(),
        None,
        login_runner=object(),
        window_automation=object(),
    )
    with pytest.raises(SettingsError) as exc:
        await service.clear_browser_profile()
    assert exc.value.code == "vpn_profile_unsafe"
    assert sentinel.read_text() == "S8_FAKE_COOKIE"


async def test_profile_clear_refuses_user_owned_symlink_above_data_root(tmp_path):
    destination = tmp_path / "destination"
    data_dir = destination / "data"
    profile = data_dir / "vpn/chrome-profile"
    profile.mkdir(parents=True)
    data_dir.chmod(0o700)
    sentinel = profile / "Cookies"
    sentinel.write_text("S8_FAKE_COOKIE")
    linked = tmp_path / "linked-parent"
    linked.symlink_to(destination, target_is_directory=True)
    service = VpnService(
        SimpleNamespace(data_dir=linked / "data"),
        None,
        None,
        Client(),
        None,
        login_runner=object(),
        window_automation=object(),
    )
    with pytest.raises(SettingsError) as exc:
        await service.clear_browser_profile()
    assert exc.value.code == "vpn_profile_unsafe"
    assert sentinel.exists()


async def test_cleanup_failure_still_waits_for_other_cleanup_owner(tmp_path):
    class BrokenOwner(Owner):
        async def close(self):
            self.closed = True
            raise OSError("fake close failure")

    class DelayedRegistry(Registry):
        def __init__(self):
            super().__init__()
            self.started, self.release, self.finished = (
                asyncio.Event(),
                asyncio.Event(),
                asyncio.Event(),
            )

        async def cleanup(self):
            self.started.set()
            await self.release.wait()
            self.cleaned += 1
            self.finished.set()

    owner, registry = BrokenOwner([encode_event("done")]), DelayedRegistry()

    async def factory(*args, **kwargs):
        return owner

    runner = ProcessLoginRunner(tmp_path, Client(), process_factory=factory, registry=registry)
    task = asyncio.create_task(runner.run(VpnConfig(), "fake", None, asyncio.Event(), None))
    try:
        await asyncio.wait_for(registry.started.wait(), 1)
        for _ in range(3):
            await asyncio.sleep(0)
        assert not task.done(), "one failed close must not detach the remaining cleanup task"
    finally:
        registry.release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.wait_for(registry.finished.wait(), 1)
    with pytest.raises(OSError, match="fake close failure"):
        await task
    assert owner.closed and registry.cleaned == 1
