"""S7 lifecycle acceptance against Python doubles; sandbox restrictions are explicit skips."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from tests.s7_helpers import gone, make_service, process_capability, settled  # noqa: F401
from toolbox_backend.api.services_schemas import ActionRequest, SettingsPatch, TunnelCreate
from toolbox_backend.domain.errors import SettingsError

pytestmark = pytest.mark.usefixtures("process_capability")


@pytest.mark.parametrize("mode", ["listen", "ignore", "grandchild"])
async def test_code_server_stop_reaps_all_owned_descendants(tmp_path, monkeypatch, mode):
    service, store, port, _, _ = make_service(tmp_path, monkeypatch, mode=mode)
    try:
        await service.start("code-server", ActionRequest())
        assert (await settled(service)).state == "running"
        assert (await service.snapshot()).code_server.port == port
        await service.stop("code-server", ActionRequest())
        assert (await settled(service)).state == "stopped"
        await gone((tmp_path / "code-pid").read_text())
        if mode == "grandchild":
            await gone((tmp_path / "grandchild-pid").read_text())
    finally:
        await service.close()


@pytest.mark.parametrize("mode,error", [("timeout", "start_timeout"), ("exit", "exited")])
async def test_code_start_failure_reclaims_process(tmp_path, monkeypatch, mode, error):
    service, store, _, _, _ = make_service(tmp_path, monkeypatch, mode=mode)
    config = await store.read()
    config.services.code_server.start_timeout_s = 0.5 if mode == "timeout" else 10
    await service.patch_settings(SettingsPatch(revision=0, services=config.services))
    try:
        await service.start("code-server", ActionRequest())
        view = await settled(service)
        assert view.state == "failed"
        assert view.last_error == error
        # Under load the interpreter may be reclaimed before it writes its pid (timeout mode).
        pid_file = tmp_path / "code-pid"
        if pid_file.exists():
            await gone(pid_file.read_text())
    finally:
        await service.close()


async def test_external_port_is_never_stopped(tmp_path, monkeypatch):
    service, _, port, _, _ = make_service(tmp_path, monkeypatch)
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", port)
    try:
        with pytest.raises(SettingsError) as exc:
            await service.start("code-server", ActionRequest())
        assert exc.value.code == "service_port_in_use"
        assert (await service.snapshot()).code_server.state == "external"
        await service.stop("code-server", ActionRequest())
        await settled(service)
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        await writer.wait_closed()
        assert not (tmp_path / "code-pid").exists()
    finally:
        server.close()
        await server.wait_closed()
        await service.close()


@pytest.mark.parametrize(
    "mode,state", [("domains", "running"), ("none", "running"), ("exit", "failed")]
)
async def test_quick_tunnel_domain_and_no_domain_and_early_exit(tmp_path, monkeypatch, mode, state):
    service, _, port, _, _ = make_service(tmp_path, monkeypatch, cloud=mode)
    try:
        await service.start("cloudflared", ActionRequest(ack_public=True))
        view = await settled(service, tunnel="global")
        assert view.state == state
        assert view.target_url == f"http://127.0.0.1:{port}"
        assert view.url == ("https://last.trycloudflare.com" if mode == "domains" else None)
        if state == "running":
            raw = json.loads((tmp_path / "cloud-argv-env.json").read_text())
            assert raw["argv"][1:] == [
                "tunnel",
                "--url",
                f"http://127.0.0.1:{port}",
                "--protocol",
                "http2",
            ]
    finally:
        await service.close()


async def test_service_logs_and_child_environment_never_contain_parent_keys(tmp_path, monkeypatch):
    service, _, _, _, _ = make_service(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_API_TOKEN", "ENV-SECRET-FAKE-123")
    monkeypatch.setenv("PASSWORD", "PASSWORD-FAKE-123")
    try:
        snap = await service.create_tunnel(
            TunnelCreate(target_url="http://127.0.0.1:45435", ack_public=True)
        )
        identifier = snap.cloudflared.tunnels[0].id
        assert (await settled(service, tunnel=identifier)).state == "running"
        logs = await service.logs("cloudflared-" + identifier)
        assert "FAKE-LOG-SECRET-123" not in logs.text
        raw = (tmp_path / "cloud-argv-env.json").read_text()
        assert "ENV-SECRET-FAKE-123" not in raw and "PASSWORD-FAKE-123" not in raw
        path = service.store.data_dir / "services/logs" / ("cloudflared-" + identifier + ".log")
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
    finally:
        await service.close()


async def test_code_health_three_failed_probes_becomes_unhealthy(tmp_path, monkeypatch):
    service, _, _, _, _ = make_service(tmp_path, monkeypatch)
    service.health_interval_s = 0.05
    try:
        await service.start("code-server", ActionRequest())
        assert (await settled(service)).state == "running"
        service.health_interval_s = 0.05

        async def refused(*args, **kwargs):
            raise ConnectionRefusedError

        monkeypatch.setattr(asyncio, "open_connection", refused)
        async with asyncio.timeout(2):
            for _ in range(100):
                if (await service.snapshot()).code_server.state == "unhealthy":
                    break
                await asyncio.sleep(0.02)
            assert (await service.snapshot()).code_server.state == "unhealthy"
    finally:
        await service.close()


async def test_services_shutdown_with_mcp_ai_is_parallel_and_within_budget(tmp_path, monkeypatch):
    from toolbox_backend.adapters.ai_store import AIStore
    from toolbox_backend.adapters.credentials import MemoryCredentials
    from toolbox_backend.services.ai_sessions import AISessionService
    from toolbox_backend.services.events import EventHub
    from toolbox_backend.services.mcp import McpService

    service, store, _, _, _ = make_service(tmp_path, monkeypatch, mode="ignore", cloud="ignore")
    hub = EventHub()
    mcp = McpService(store, MemoryCredentials(), MemoryCredentials(), hub=hub, path_extras=[])
    ai = AISessionService(store, AIStore(store.data_dir, hub.publish_ai), hub)
    try:
        await service.start("code-server", ActionRequest())
        assert (await settled(service)).state == "running"
        await service.create_tunnel(
            TunnelCreate(target_url="http://127.0.0.1:45435", ack_public=True)
        )
        # No-domain tunnel still has an owned process during its 15 second discovery window.
        await asyncio.sleep(0.5)
        started = time.monotonic()
        await asyncio.gather(service.close(), mcp.close(), ai.close())
        assert time.monotonic() - started < 5
    finally:
        await asyncio.gather(service.close(), mcp.close(), ai.close())


async def test_backend_sigkill_reclaims_code_tunnels_and_grandchild(tmp_path, monkeypatch):
    service, _, _, bin_dir, config = make_service(
        tmp_path, monkeypatch, mode="grandchild", cloud="ignore"
    )
    await service.close()
    script = """import asyncio,sys
from pathlib import Path
from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.services.services import ServicesService
from toolbox_backend.api.services_schemas import ActionRequest,TunnelCreate
async def main():
 s=ServicesService(ConfigStore(Path(sys.argv[1])),code_server_config_path=Path(sys.argv[2]),path_extras=[])
 await s.start('code-server',ActionRequest())
 await s.create_tunnel(TunnelCreate(target_url='http://127.0.0.1:45435',ack_public=True))
 await s.create_tunnel(TunnelCreate(target_url='http://[::1]:45436',ack_public=True))
 await asyncio.sleep(1)
 Path(sys.argv[3]).write_text('ready')
 await asyncio.Event().wait()
asyncio.run(main())
"""
    proc = await asyncio.to_thread(
        subprocess.Popen,
        [
            sys.executable,
            "-c",
            script,
            str(tmp_path / "data"),
            str(config),
            str(tmp_path / "ready"),
        ],
        env={**os.environ, "PATH": str(bin_dir)},
    )
    try:
        async with asyncio.timeout(10):
            while not (tmp_path / "ready").exists():
                assert proc.poll() is None
                await asyncio.sleep(0.05)
        pids = [(tmp_path / "code-pid").read_text(), (tmp_path / "grandchild-pid").read_text()]
        pids += [p.read_text() for p in tmp_path.glob("cloud-*-pid")]
        assert len(pids) == 4
        proc.send_signal(signal.SIGKILL)
        await asyncio.to_thread(proc.wait, 5)
        await asyncio.gather(*(gone(pid) for pid in pids))
    finally:
        if proc.poll() is None:
            proc.kill()
        await asyncio.to_thread(proc.wait, 5)
