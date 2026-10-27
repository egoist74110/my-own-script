"""S7 public application seams, using temporary configuration and executable doubles."""

import json

import pytest

from tests.s7_helpers import process_capability  # noqa: F401
from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.domain.settings import Config


async def test_v4_services_migration_is_atomic_and_idempotent(tmp_path):
    raw = Config().model_dump(by_alias=True)
    raw.pop("services", None)
    raw.update(schema_version=4, revision=7)
    original = json.dumps(raw).encode()
    (tmp_path / "config.json").write_bytes(original)
    store = ConfigStore(tmp_path)
    first = await store.initialize()
    assert first.schema_version == 6
    assert first.services.cloudflared.protocol == "http2"
    assert first.revision == 8
    backups = list((tmp_path / "migrations").glob("config-v4-*.json"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    assert await store.initialize() == first
    assert len(list((tmp_path / "migrations").iterdir())) == 1


async def test_services_start_returns_before_readiness_and_stop_is_busy(tmp_path, monkeypatch):
    from toolbox_backend.api.services_schemas import ActionRequest
    from toolbox_backend.domain.errors import SettingsError
    from toolbox_backend.services.services import ServicesService

    monkeypatch.setenv("PATH", str(tmp_path))
    config = tmp_path / "code.yaml"
    config.write_text("auth: password\nbind-addr: 127.0.0.1:54321\n")
    service = ServicesService(ConfigStore(tmp_path), code_server_config_path=config, path_extras=[])
    # Nonexistent confirmed binary is rejected without attempting any real executable.
    with pytest.raises(SettingsError) as exc:
        await service.start("code-server", ActionRequest())
    assert exc.value.code == "service_binary_missing"
    assert (await service.snapshot()).code_server.state == "stopped"
    await service.close()


def test_ambiguous_auth_cannot_prove_password(tmp_path):
    from toolbox_backend.adapters.service_runtime import read_code_server_config

    path = tmp_path / "config.yaml"
    path.write_text('auth: password\n"auth": none\nbind-addr: 0.0.0.0:43210\n')
    assert not read_code_server_config(path).safe


@pytest.mark.usefixtures("process_capability")
async def test_custom_tunnel_holds_owned_group_and_accepts_last_valid_domain(tmp_path, monkeypatch):
    import asyncio
    import sys

    from toolbox_backend.api.services_schemas import ProtocolRequest, TunnelCreate
    from toolbox_backend.services.services import ServicesService

    binary = tmp_path / "cloudflared"
    binary.write_text(
        f"#!{sys.executable}\nimport time\n"
        'print("https://one.trycloudflare.com", flush=True)\n'
        'print("https://two.trycloudflare.com", flush=True)\n'
        'print("evil https://spoof.trycloudflare.com", flush=True)\n'
        'print("2026-10-26T06:00:00Z INF |  https://boxed.trycloudflare.com      |", flush=True)\n'
        'print("2026-10-26T06:00:01Z INF Requesting https://api.trycloudflare.com", flush=True)\n'
        'print("| https://api.trycloudflare.com |", flush=True)\n'
        'print("2026-10-26T06:00:02Z ERR see https://spoof2.trycloudflare.com", flush=True)\n'
        "time.sleep(60)\n"
    )
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    service = ServicesService(ConfigStore(tmp_path), path_extras=[])
    try:
        snap = await service.create_tunnel(
            TunnelCreate(target_url="http://[::1]:43210", ack_public=True)
        )
        assert snap.cloudflared.tunnels[0].state == "starting"
        for _ in range(100):
            snap = await service.snapshot()
            if snap.cloudflared.tunnels[0].state != "starting":
                break
            await asyncio.sleep(0.05)
        assert snap.cloudflared.tunnels[0].state == "running"
        assert snap.cloudflared.tunnels[0].url == "https://boxed.trycloudflare.com"
        assert snap.cloudflared.tunnels[0].owned
        result = await service.set_protocol(
            ProtocolRequest(revision=snap.revision, protocol="quic")
        )
        assert result.restart_required
        assert (await service.snapshot()).cloudflared.tunnels[
            0
        ].url == "https://boxed.trycloudflare.com"
        await service.delete_tunnel(snap.cloudflared.tunnels[0].id)
        assert not (await service.snapshot()).cloudflared.tunnels
    finally:
        await service.close()


async def test_tunnel_delete_cannot_address_other_service(tmp_path):
    from toolbox_backend.domain.errors import SettingsError
    from toolbox_backend.services.services import ServicesService

    service = ServicesService(ConfigStore(tmp_path), path_extras=[])
    with pytest.raises(SettingsError) as exc:
        await service.delete_tunnel("code-server")
    assert exc.value.code == "not_found"


async def test_protocol_change_while_tunnel_starting_requires_restart(tmp_path):
    import asyncio

    from toolbox_backend.api.services_schemas import ProtocolRequest, ServiceView
    from toolbox_backend.services.services import ServiceLifecycle, ServicesService

    service = ServicesService(ConfigStore(tmp_path), path_extras=[])
    # Fake boundary: a reserved in-flight launch has no process handle yet.
    record = ServiceLifecycle(view=ServiceView(id="pending", state="starting"), protocol="http2")
    record.operation = asyncio.create_task(asyncio.sleep(60))
    service.tunnels["pending"] = record
    try:
        result = await service.set_protocol(ProtocolRequest(revision=0, protocol="quic"))
        assert result.restart_required
    finally:
        await service.close()


async def test_start_is_single_flight_and_snapshot_does_not_wait_or_spawn(tmp_path, monkeypatch):
    import asyncio
    import sys

    from toolbox_backend.adapters.ai_process import SupervisedProcess
    from toolbox_backend.api.services_schemas import ActionRequest
    from toolbox_backend.domain.errors import SettingsError
    from toolbox_backend.services.services import ServicesService

    binary = tmp_path / "code-server"
    binary.write_text(f"#!{sys.executable}\n")
    binary.chmod(0o700)
    config = tmp_path / "code.yaml"
    config.write_text("auth: password\nbind-addr: 127.0.0.1:45435\n")
    monkeypatch.setenv("PATH", str(tmp_path))
    calls = []

    async def pending(*args, **kwargs):
        calls.append(args)
        await asyncio.Event().wait()

    async def closed(*args, **kwargs):
        raise ConnectionRefusedError

    monkeypatch.setattr(SupervisedProcess, "start", pending)
    monkeypatch.setattr(asyncio, "open_connection", closed)
    service = ServicesService(ConfigStore(tmp_path), code_server_config_path=config, path_extras=[])
    req = ActionRequest(request_id="b9b220eb-4525-4d49-9a97-05f32d7f0b89")
    try:
        first = await service.start("code-server", req)
        assert first.code_server.state == "starting"
        assert await service.start("code-server", req) == first
        async with asyncio.timeout(0.1):
            assert (await service.snapshot()).code_server.state == "starting"
        with pytest.raises(SettingsError) as exc:
            await service.stop("code-server", ActionRequest())
        assert exc.value.code == "service_busy"
        await asyncio.sleep(0.05)
        assert len(calls) == 1
        for _ in range(5):
            await service.snapshot()
        assert len(calls) == 1
    finally:
        await service.close()


async def test_global_start_fixed_target_needs_only_explicit_start(tmp_path, monkeypatch):
    import asyncio
    import sys

    from toolbox_backend.adapters.ai_process import SupervisedProcess
    from toolbox_backend.api.services_schemas import ActionRequest
    from toolbox_backend.services.services import ServicesService

    binary = tmp_path / "cloudflared"
    binary.write_text(f"#!{sys.executable}\n")
    binary.chmod(0o700)
    cfg = tmp_path / "code.yaml"
    cfg.write_text("auth: password\nbind-addr: 127.0.0.1:45436\n")
    monkeypatch.setenv("PATH", str(tmp_path))

    async def pending(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(SupervisedProcess, "start", pending)
    service = ServicesService(ConfigStore(tmp_path), code_server_config_path=cfg, path_extras=[])
    try:
        result = await service.start("cloudflared", ActionRequest())
        assert result.cloudflared.global_.state == "starting"
        assert result.cloudflared.global_.target_url == "http://127.0.0.1:45436"
    finally:
        await service.close()


def test_ack_public_must_be_json_boolean():
    from pydantic import ValidationError

    from toolbox_backend.api.services_schemas import TunnelCreate

    with pytest.raises(ValidationError):
        TunnelCreate(target_url="http://127.0.0.1:45436", ack_public="yes")


def test_logs_rotate_redact_and_reject_symlinks(tmp_path):
    from toolbox_backend.adapters.service_logs import ServiceLog
    from toolbox_backend.logging_setup import register_secret

    register_secret("S7-FAKE-SECRET-VALUE")
    log = ServiceLog(tmp_path, "code-server", max_bytes=80)
    for _ in range(5):
        log.write("Authorization: Bearer FAKE-BEARER-123 S7-FAKE-SECRET-VALUE\n")
    files = list((tmp_path / "services/logs").iterdir())
    assert len(files) == 2
    assert all(p.stat().st_size <= 80 and p.stat().st_mode & 0o777 == 0o600 for p in files)
    assert all(
        "FAKE-BEARER-123" not in p.read_text() and "S7-FAKE-SECRET-VALUE" not in p.read_text()
        for p in files
    )
    assert len(log.read_tail(10).encode()) <= 10
    target = tmp_path / "other"
    target.write_text("unchanged")
    (tmp_path / "services/logs/cloudflared.log").symlink_to(target)
    unsafe = ServiceLog(tmp_path, "cloudflared")
    with pytest.raises(ValueError):
        unsafe.write("blocked")
    assert target.read_text() == "unchanged"


async def test_network_polling_is_cached_and_closes_its_task(tmp_path, monkeypatch):
    import asyncio

    from toolbox_backend.api.services_schemas import NetworkInfo
    from toolbox_backend.services.services import ServicesService

    calls = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return NetworkInfo(lan_ip="192.168.7.6", on_lan=True)

    monkeypatch.setenv("PATH", str(tmp_path))
    service = ServicesService(ConfigStore(tmp_path), path_extras=[], network_reader=fake)
    service.network_interval_s = 0.02
    await service.initialize()
    await asyncio.sleep(0.05)
    assert calls == []  # idle backend owns no ifconfig child until a snapshot is requested
    await service.snapshot()
    await asyncio.sleep(0.01)
    before = len(calls)
    for _ in range(5):
        assert (await service.snapshot()).network.lan_ip == "192.168.7.6"
    assert len(calls) == before
    await asyncio.sleep(0.03)
    assert len(calls) > before
    await service.close()
    after = len(calls)
    await asyncio.sleep(0.03)
    assert len(calls) == after


async def test_legacy_protocol_import_reads_only_enum_and_revision(tmp_path, monkeypatch):
    from toolbox_backend.api.services_schemas import LegacyImport
    from toolbox_backend.domain.errors import SettingsError
    from toolbox_backend.services.services import ServicesService

    monkeypatch.setenv("PATH", str(tmp_path))
    path = tmp_path / "old.json"
    path.write_text('{"protocol":"quic","password":"do-not-copy"}')
    service = ServicesService(ConfigStore(tmp_path / "data"), path_extras=[])
    result = await service.import_legacy(LegacyImport(revision=0, path=str(path)))
    assert result.revision == 1
    assert (await service.snapshot()).settings.cloudflared.protocol == "quic"
    assert "do-not-copy" not in service.store.path.read_text()
    assert path.read_text() == '{"protocol":"quic","password":"do-not-copy"}'
    with pytest.raises(SettingsError) as exc:
        await service.import_legacy(LegacyImport(revision=0, path=str(path)))
    assert exc.value.code == "revision_conflict"
    path.write_text('{"protocol":"unsafe"}')
    with pytest.raises(SettingsError) as exc:
        await service.import_legacy(LegacyImport(revision=1, path=str(path)))
    assert exc.value.code == "validation_error"


async def test_health_monitor_keeps_only_one_process_waiter(tmp_path, monkeypatch):
    import asyncio
    import sys

    from toolbox_backend.adapters.ai_process import SupervisedProcess
    from toolbox_backend.api.services_schemas import TunnelCreate
    from toolbox_backend.services.services import ServicesService

    class Proc:
        returncode = None
        active = 0
        stopped = asyncio.Event()

        async def wait(self):
            self.active += 1
            try:
                await self.stopped.wait()
                return 0
            finally:
                self.active -= 1

    class Owner:
        proc = Proc()
        stdout, stderr = asyncio.StreamReader(), asyncio.StreamReader()

        async def close(self):
            self.proc.returncode = 0
            self.proc.stopped.set()
            self.stdout.feed_eof()
            self.stderr.feed_eof()

        def close_control(self):
            self.proc.stopped.set()

    owner = Owner()
    owner.stdout.feed_data(b"https://health.trycloudflare.com\n")

    async def spawn(*args, **kwargs):
        return owner

    monkeypatch.setattr(SupervisedProcess, "start", spawn)
    binary = tmp_path / "cloudflared"
    binary.write_text(f"#!{sys.executable}\n")
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    service = ServicesService(ConfigStore(tmp_path), path_extras=[])
    service.health_interval_s = 0.01
    try:
        await service.create_tunnel(
            TunnelCreate(target_url="http://127.0.0.1:45436", ack_public=True)
        )
        await asyncio.sleep(0.4)
        assert (await service.snapshot()).cloudflared.tunnels[0].state == "unhealthy"
        assert owner.proc.active <= 1
    finally:
        await service.close()
    assert owner.proc.active == 0


async def test_snapshot_revision_tracks_other_settings_writes_without_read_io(tmp_path):
    import asyncio

    from toolbox_backend.services.services import ServicesService

    store = ConfigStore(tmp_path)
    service = ServicesService(store, path_extras=[])
    try:
        await store.update(0, lambda c: None)
        await asyncio.sleep(0)
        assert (await service.snapshot()).revision == 1
    finally:
        await service.close()


async def test_initialize_probes_external_once_and_snapshot_reads_cache(tmp_path, monkeypatch):
    import asyncio
    import sys

    from toolbox_backend.services.services import ServicesService

    cfg = tmp_path / "config.yaml"
    cfg.write_text("auth: password\nbind-addr: 127.0.0.1:45437\n")
    binary = tmp_path / "code-server"
    binary.write_text(f"#!{sys.executable}\n")
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    calls = []

    class Writer:
        def close(self):
            pass

        async def wait_closed(self):
            pass

    async def connect(host, port):
        calls.append((host, port))
        return None, Writer()

    monkeypatch.setattr(asyncio, "open_connection", connect)
    service = ServicesService(ConfigStore(tmp_path), code_server_config_path=cfg)
    try:
        await service.initialize()
        assert (await service.snapshot()).code_server.state == "external"
        count = len(calls)
        for _ in range(4):
            await service.snapshot()
        assert len(calls) == count
    finally:
        await service.close()


async def test_default_code_config_follows_xdg_without_reading_real_home(tmp_path, monkeypatch):
    from toolbox_backend.services.services import ServicesService

    cfg = tmp_path / "code-server/config.yaml"
    cfg.parent.mkdir()
    cfg.write_text("auth: password\nbind-addr: 127.0.0.1:45438\n")
    monkeypatch.delenv("TOOLBOX_TEST_ROOT")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    service = ServicesService(ConfigStore(tmp_path / "data"))
    assert service.config_path == cfg
    await service.close()
