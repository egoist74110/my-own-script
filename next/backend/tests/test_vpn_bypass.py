"""Bypass safety tests: all process/route operations are mocked."""

import copy
import json
import plistlib
import subprocess

import httpx
import pytest
from pydantic import ValidationError

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.app import create_app
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import Config
from toolbox_backend.domain.vpn_bypass import BypassSettingsWrite, VpnBypassConfig
from toolbox_backend.services.vpn_bypass import VpnBypassService, export_bundle
from toolbox_backend.settings import Settings
from toolbox_backend.vpn import bypass_daemon as daemon


def config(**changes):
    return VpnBypassConfig(
        enabled=True, gateway="192.168.8.1", interface="en0", **changes
    ).model_dump()


@pytest.mark.parametrize(
    "value",
    [
        "::1",
        "1.2.3.4/24",
        "0.0.0.0/0",
        "127.1.2.3",
        "169.254.2.3",
        "224.0.0.1",
        "1.2.3.4;id",
        "8.0.0.0/1",
    ],
)
def test_reject_unsafe_targets(value):
    with pytest.raises(ValidationError):
        VpnBypassConfig(targets=[value])


@pytest.mark.parametrize(
    "app",
    [
        {"id": "uu", "name": "UU"},
        {"id": "uu", "name": "UU", "executable_path": "relative"},
        {"id": "uu", "name": "UU", "application_path": "/Applications/UU.app/../Other.app"},
        {"id": "uu", "name": "UU", "application_path": "/Applications/UU"},
        {"id": "uu", "name": "UU", "application_path": "/UU.app", "executable_path": "/bin/uu"},
    ],
)
def test_exact_app_matching_config(app):
    with pytest.raises(ValidationError):
        VpnBypassConfig(apps=[app])


def test_normalization_and_duplicate_ids():
    assert VpnBypassConfig(targets=["1.2.3.4", "1.2.3.4/32"]).targets == ["1.2.3.4/32"]
    app = {"id": "uu", "name": "UU", "application_path": "/Applications/UU.app"}
    with pytest.raises(ValidationError):
        VpnBypassConfig(apps=[app, app])


@pytest.mark.asyncio
async def test_persist_revision_and_backward_compatibility(tmp_path):
    store = ConfigStore(tmp_path)
    await store.initialize()
    service = VpnBypassService(store)
    initial = await service.snapshot()
    body = BypassSettingsWrite(
        revision=initial["revision"], settings=config(targets=["1.2.3.0/24"])
    )
    result = await service.update(body)
    assert result.revision == initial["revision"] + 1
    assert (await ConfigStore(tmp_path).read()).vpn_bypass.targets == ["1.2.3.0/24"]
    with pytest.raises(SettingsError) as exc:
        await service.update(body)
    assert exc.value.code == "revision_conflict"
    raw = Config().model_dump(by_alias=True)
    raw.pop("vpn_bypass")
    assert not Config.model_validate(raw).vpn_bypass.enabled
    # CRUD is whole-list replacement, preserving all other config domains.
    await service.update(BypassSettingsWrite(revision=result.revision, settings=config()))
    assert (await store.read()).vpn_bypass.targets == []
    assert (await store.read()).vpn == result.vpn


@pytest.mark.asyncio
async def test_api_auth_typed_config_and_export(tmp_path, monkeypatch):
    monkeypatch.setattr("toolbox_backend.services.vpn_bypass.sys.platform", "linux")
    app = create_app(Settings(token="test-token", port=12345, data_dir=tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:12345"
    ) as client:
        assert (await client.get("/api/vpn/bypass")).status_code == 401
        client.headers["Authorization"] = "Bearer test-token"
        initial = (await client.get("/api/vpn/bypass")).json()
        assert initial["status"]["mode"] == "managed"
        assert initial["status"]["state"] == "not_installed"
        assert "保存配置不代表规则已生效" in initial["status"]["message"]
        assert all(
            any("\u4e00" <= c <= "\u9fff" for c in line)
            for line in initial["status"]["limitations"]
        )
        response = await client.patch(
            "/api/vpn/bypass/settings", json={"revision": initial["revision"], "settings": config()}
        )
        assert response.status_code == 200, response.text
        sweep = await client.post("/api/vpn/bypass/sweep", json={"apply": True})
        # No native calls in this test: platform check short-circuited by the mocked unsupported platform.
        assert sweep.status_code == 200
        assert sweep.json()["applied"] is False
        bundle = await client.post(
            "/api/vpn/bypass/export", json={"python_path": "/opt/trusted/bin/python3"}
        )
        assert bundle.status_code == 200
        assert "helper_source" in bundle.json()


@pytest.mark.asyncio
async def test_preview_is_read_only_and_reports_inspection_failures(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path)
    service = VpnBypassService(store)
    await service.update(BypassSettingsWrite(revision=0, settings=config(targets=["1.2.3.4"])))
    monkeypatch.setattr("toolbox_backend.services.vpn_bypass.sys.platform", "darwin")
    monkeypatch.setattr(daemon, "route_table", lambda: {})
    monkeypatch.setattr(daemon, "physical_gateway", lambda *args: ("192.168.8.1", "en0"))
    monkeypatch.setattr(daemon, "discover", lambda *args: ["2.3.4.5/32"])
    result = await service.sweep(True)
    assert result.targets == ["1.2.3.4/32", "2.3.4.5/32"]
    assert not result.applied and result.requires_privilege

    def broken(*args):
        raise subprocess.TimeoutExpired("mock", 8)

    monkeypatch.setattr(daemon, "discover", broken)
    assert "预览失败" in (await service.sweep()).errors[0]
    revision = (await store.read()).revision
    await service.update(
        BypassSettingsWrite(revision=revision, settings=VpnBypassConfig(enabled=True))
    )
    assert "缺少物理网关或网卡" in (await service.sweep()).errors[0]
    await service.update(BypassSettingsWrite(revision=revision + 1, settings=config()))
    assert "尚未配置分流目标" in (await service.sweep()).errors[0]
    await service.update(BypassSettingsWrite(revision=revision + 2, settings=VpnBypassConfig()))
    assert "尚未启用" in (await service.sweep()).errors[0]


def test_export_is_standalone_and_fixed_argv():
    bundle = export_bundle(config(), "/opt/trusted path/bin/python3")
    plist = plistlib.loads(bundle["launchd_plist"].encode())
    assert plist["ProgramArguments"] == [
        "/opt/trusted path/bin/python3",
        "-I",
        "-S",
        str(daemon.ROOT / "helper.py"),
        "loop",
    ]
    assert "toolbox_backend" not in bundle["helper_source"]
    compile(bundle["helper_source"], "helper.py", "exec")
    assert json.loads(bundle["config_json"])["interface"] == "en0"
    assert "需要 Python 3.9" in bundle["runtime_requirement"]
    assert "这里只生成导出文件" in bundle["instructions"][0]
    assert "撤销前先停止服务" in "\n".join(bundle["instructions"])
    with pytest.raises(SettingsError):
        export_bundle(config(), "python3")


def test_route_parser_and_physical_gateway_fail_closed():
    table = """Internet:
Destination Gateway Flags Netif Expire
default 192.168.8.1 UGSc en0
192.168.8/24 link#4 UCS en0
1.2.3.4 192.168.8.1 UGHS en0
10/8 10.2.3.4 UGScI utun4
"""
    routes = daemon.route_table(lambda argv: table)
    assert "10.0.0.0/8" not in routes
    assert "192.168.8.0/24" in routes
    assert daemon.physical_gateway(
        config(),
        routes,
        lambda argv: "Device: en0\n" if argv[0].endswith("networksetup") else "status: active\n",
    ) == (
        "192.168.8.1",
        "en0",
    )
    for ports, values in [("Device: en1\n", routes), ("Device: en0\n", {})]:
        with pytest.raises(RuntimeError):
            daemon.physical_gateway(config(), values, lambda argv, ports=ports: ports)
    with pytest.raises(RuntimeError):
        daemon.route_table(lambda argv: "broken")


class Routing:
    def __init__(self, table=None):
        self.table = table or {}
        self.state = {"owned": {}, "cache": {}}
        self.calls = []
        self.saved = []

    def persist(self, state):
        self.saved.append(copy.deepcopy(state))

    def mutate(self, action, net, owner):
        self.calls.append((action, net, copy.deepcopy(owner)))
        if action == "add":
            assert self.saved[-1]["owned"][net]["phase"] == "pending"
            self.table[net] = {**owner, "flags": "UGHS"}
        else:
            self.table.pop(net, None)

    def sweep(self, cfg=None, discovered=None, now=100):
        return daemon.reconcile(
            cfg or config(),
            self.state,
            discovered or [],
            copy.deepcopy(self.table),
            ("192.168.8.1", "en0"),
            lambda: copy.deepcopy(self.table),
            self.mutate,
            self.persist,
            now,
        )


def test_add_verify_repair_after_reconnect_and_cidr_undo():
    routing = Routing()
    cfg = config(targets=["1.2.3.0/24"])
    assert routing.sweep(cfg) == [["1.2.3.0/24", "added_verified"]]
    routing.table.clear()  # VPN flushes our exact route
    assert routing.sweep(cfg) == [["1.2.3.0/24", "added_verified"]]
    routing.sweep(config())
    assert routing.calls[-1][:2] == ("delete", "1.2.3.0/24")
    assert not routing.state["owned"]


def test_never_adopt_replace_or_delete_unrelated_routes():
    routing = Routing(
        {"1.2.3.4/32": {"gateway": "10.0.0.1", "interface": "utun4", "flags": "UGHS"}}
    )
    assert routing.sweep(config(targets=["1.2.3.4"])) == [["1.2.3.4/32", "unowned_conflict"]]
    assert not routing.calls
    routing.table.clear()
    routing.sweep(config(targets=["1.2.3.4"]))
    routing.calls.clear()
    routing.table["1.2.3.4/32"]["gateway"] = "10.0.0.1"
    routing.sweep(config())
    assert not routing.calls
    assert "1.2.3.4/32" in routing.table
    assert not routing.state["owned"]


def test_retention_capacity_and_disabled_cleanup():
    routing = Routing()
    routing.sweep(config(retention_s=10), ["1.2.3.4/32"])
    routing.sweep(config(retention_s=10), now=105)
    assert len(routing.calls) == 1
    routing.sweep(config(retention_s=10), now=111)
    assert routing.calls[-1][0] == "delete"
    routing.sweep(config(targets=["2.3.4.5"]))
    disabled = config()
    disabled["enabled"] = False
    routing.sweep(disabled)
    assert not routing.state["owned"]
    with pytest.raises(RuntimeError, match="capacity"):
        routing.sweep(discovered=[f"10.0.{i // 256}.{i % 256}/32" for i in range(1025)])


def test_failed_add_never_reports_success_and_pending_not_deleted():
    routing = Routing()
    routing.mutate = lambda *args: None
    with pytest.raises(RuntimeError, match="addition verification"):
        routing.sweep(config(targets=["1.2.3.4"]))
    assert routing.state["owned"]["1.2.3.4/32"]["phase"] == "pending"
    routing.table["1.2.3.4/32"] = {"gateway": "192.168.8.1", "interface": "en0", "flags": "UGHS"}
    assert routing.sweep(config()) == [["1.2.3.4/32", "pending_conflict_manual_recovery"]]
    assert not routing.calls


def test_no_delete_when_route_changes_during_sweep():
    routing = Routing()
    routing.sweep(config(targets=["1.2.3.4"]))
    routing.calls.clear()
    initial = copy.deepcopy(routing.table)
    routing.table["1.2.3.4/32"]["interface"] = "utun3"
    daemon.reconcile(
        config(),
        routing.state,
        [],
        initial,
        ("", ""),
        lambda: copy.deepcopy(routing.table),
        routing.mutate,
        routing.persist,
        100,
    )
    assert not routing.calls


def test_root_boundary_rejects_user_owned_or_symlink_paths(tmp_path):
    path = tmp_path / "file"
    path.write_text("{}")
    with pytest.raises(RuntimeError, match="protected"):
        daemon.protected(path)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(RuntimeError):
        daemon.protected(link)


def test_state_validation_rejects_arbitrary_routes_and_fields():
    with pytest.raises(ValueError):
        daemon.validate_state({"cache": {"0.0.0.0/0": 100}, "owned": {}})
    with pytest.raises(ValueError):
        daemon.validate_state({"cache": {}, "owned": {}, "shell": "id"})


def test_discovery_uses_exact_kernel_path_and_connected_ipv4_only(monkeypatch):
    class Libproc:
        def __init__(self):
            def pidpath(pid, buffer, size):
                buffer.value = {
                    11: b"/Applications/UU.app/Contents/MacOS/UU",
                    12: b"/usr/bin/other-UU",
                }[pid]
                return len(buffer.value)

            self.proc_pidpath = pidpath

    monkeypatch.setattr(daemon.ctypes, "CDLL", lambda path: Libproc())
    cfg = config(
        apps=[
            {"id": "uu", "name": "UU", "executable_path": "/Applications/UU.app/Contents/MacOS/UU"}
        ]
    )
    calls = []

    def run(argv, allowed=(0,)):
        calls.append(argv)
        if argv[0] == "/bin/ps":
            return "11\n12\n"
        assert argv == ["/usr/sbin/lsof", "-nP", "-a", "-p", "11", "-i4", "-Fn"]
        return "p11\nn192.168.8.2:100->1.2.3.4:443\nn*:8000\nn[::1]:1->[::2]:2\nn1.1.1.1:22->127.0.0.1:3\n"

    assert daemon.discover(cfg, run) == ["1.2.3.4/32"]
    assert len(calls) == 2


def test_application_metadata_resolves_only_main_executable(tmp_path):
    app = tmp_path / "UU.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "UU"}))
    entries = [{"enabled": True, "executable_path": None, "application_path": str(app)}]
    assert daemon.executable_paths(entries) == {str(app / "Contents/MacOS/UU")}
    (app / "Contents/Info.plist").write_bytes(
        plistlib.dumps({"CFBundleExecutable": "../../bin/sh"})
    )
    with pytest.raises(RuntimeError):
        daemon.executable_paths(entries)


def test_delete_failure_is_verified_not_claimed():
    routing = Routing()
    routing.sweep(config(targets=["1.2.3.4"]))
    routing.mutate = lambda *args: None
    with pytest.raises(RuntimeError, match="deletion verification"):
        routing.sweep(config())
    assert routing.state["owned"]["1.2.3.4/32"]["phase"] == "owned"


def test_gateway_change_removes_old_owned_before_adding_new():
    routing = Routing()
    routing.sweep(config(targets=["1.2.3.4"]))
    initial = copy.deepcopy(routing.table)
    daemon.reconcile(
        config(targets=["1.2.3.4"]),
        routing.state,
        [],
        initial,
        ("192.168.9.1", "en1"),
        lambda: copy.deepcopy(routing.table),
        routing.mutate,
        routing.persist,
        101,
    )
    assert [call[0] for call in routing.calls] == ["add", "delete", "add"]
    assert routing.state["owned"]["1.2.3.4/32"]["interface"] == "en1"


def test_scoped_route_never_adopted_or_counted_as_our_route():
    routes = daemon.route_table(
        lambda args: (
            "Destination Gateway Flags Netif\n192.168.8 link#4 UCS en0\n1.2.3.4 192.168.8.1 UGHSI en0\n"
        )
    )
    assert "1.2.3.4/32" not in routes
    assert "192.168.8.0/24" in routes


def test_exporter_writes_reviewable_bundle_without_install(tmp_path, monkeypatch):
    import runpy
    from pathlib import Path

    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(config(targets=["1.2.3.4"])))
    output = tmp_path / "reviewed-export"
    script = Path(__file__).resolve().parents[2] / "scripts/export_vpn_bypass.py"
    monkeypatch.setattr(
        "sys.argv",
        [str(script), str(snapshot), str(output), "--python", "/opt/trusted/bin/python3"],
    )
    runpy.run_path(str(script), run_name="__main__")
    assert set(p.name for p in output.iterdir()) == {
        "config.json",
        "helper.py",
        "com.toolbox.vpn-bypass.plist",
        "INSTRUCTIONS.txt",
    }
    assert json.loads((output / "config.json").read_text())["targets"] == ["1.2.3.4/32"]
    assert (output / "helper.py").stat().st_mode & 0o777 == 0o600
    assert "bootout" in (output / "INSTRUCTIONS.txt").read_text()
    with pytest.raises(FileExistsError):
        runpy.run_path(str(script), run_name="__main__")


def test_commands_are_fixed_argv_and_timeout(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="result", stderr="")

    monkeypatch.setattr(daemon.subprocess, "run", run)
    assert daemon.command(["/sbin/route", "-n", "get", "1.2.3.4"]) == "result"
    _, options = calls[0]
    assert options["timeout"] == 8
    assert options.get("shell", False) is False
    assert options["env"]["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"
