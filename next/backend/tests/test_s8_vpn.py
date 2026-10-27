import asyncio
import plistlib

import httpx
import pytest

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.adapters.vpn_client import ClientController
from toolbox_backend.api.middleware import BodyLimit
from toolbox_backend.api.services_schemas import NetworkInfo
from toolbox_backend.app import create_app
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.services.events import EventHub
from toolbox_backend.services.vpn import VpnService
from toolbox_backend.settings import Settings


class FakeClient:
    def __init__(self):
        self.opened = asyncio.Event()
        self.release = asyncio.Event()

    def resolve(self, bundle):
        return object()

    async def status(self, bundle):
        return {"installed": True, "running": False, "app_name": "Fake", "version": "1"}

    async def open(self, bundle):
        self.opened.set()
        await self.release.wait()

    async def restart(self, bundle, *, allow_term=True):
        pass


class FakeLegacy:
    def get(self, account):
        return None


@pytest.mark.asyncio
async def test_cancel_interrupts_blocked_client_action_and_releases_single_flight(tmp_path):
    store = ConfigStore(tmp_path)
    await store.initialize()
    client = FakeClient()
    service = VpnService(
        store,
        MemoryCredentials(),
        FakeLegacy(),
        client,
        EventHub(),
        network_reader=lambda **kwargs: asyncio.sleep(0, result=NetworkInfo()),
    )
    run = await service.start(max_rung=1)
    await client.opened.wait()
    cancelled = await service.cancel(run.run_id)
    assert cancelled.state == "cancelling"
    for _ in range(50):
        if service._task is None:
            break
        await asyncio.sleep(0.01)
    assert service.get_run(run.run_id).state == "cancelled"
    next_run = await service.start(max_rung=0)
    assert next_run.state == "queued"
    await service.close()


@pytest.mark.asyncio
async def test_second_run_is_rejected_while_first_is_active(tmp_path):
    store = ConfigStore(tmp_path)
    await store.initialize()
    client = FakeClient()
    service = VpnService(
        store,
        MemoryCredentials(),
        FakeLegacy(),
        client,
        EventHub(),
        network_reader=lambda **kwargs: asyncio.sleep(0, result=NetworkInfo()),
    )
    await service.start(max_rung=1)
    await client.opened.wait()
    with pytest.raises(SettingsError, match="VPN 运行正在进行"):
        await service.start(max_rung=1)
    await service.close()


@pytest.mark.asyncio
async def test_run_completion_notifies_result_callback(tmp_path):
    store = ConfigStore(tmp_path)
    await store.initialize()
    service = VpnService(
        store,
        MemoryCredentials(),
        FakeLegacy(),
        FakeClient(),
        EventHub(),
        network_reader=lambda **kwargs: asyncio.sleep(
            0, result=NetworkInfo(vpn_ip="10.254.0.2")
        ),
    )
    completed = []

    async def on_complete(result):
        completed.append(result)

    service.on_complete = on_complete
    run = await service.start(max_rung=0)
    for _ in range(100):
        if service._task is None:
            break
        await asyncio.sleep(0.01)
    assert service.get_run(run.run_id).state == "succeeded"
    assert len(completed) == 1 and completed[0].run_id == run.run_id
    await service.close()


@pytest.mark.asyncio
async def test_totp_import_body_can_exceed_general_request_limit():
    seen = []

    async def endpoint(scope, receive, send):
        body = await receive()
        seen.append(body["body"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = BodyLimit(endpoint, max_body_bytes=65536, path_limits={"/api/vpn/totp/import": 1 << 20})
    body = b"x" * 70000
    scope = {"type": "http", "method": "POST", "path": "/api/vpn/totp/import", "headers": []}
    messages = iter([{"type": "http.request", "body": body, "more_body": False}])
    sent = []

    async def send(message):
        sent.append(message)

    await app(scope, lambda: asyncio.sleep(0, result=next(messages)), send)
    assert seen == [body]
    assert sent[0]["status"] == 204


@pytest.mark.asyncio
async def test_restart_never_terms_same_named_unrelated_process(tmp_path):
    app = tmp_path / "Fake VPN.app"
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": "test.fake.vpn",
                "CFBundleExecutable": "FakeVPN",
                "CFBundleName": "Fake VPN",
            }
        )
    )
    unrelated = tmp_path / "Other.app" / "Contents" / "MacOS" / "FakeVPN"
    ps = (
        "PID STARTED COMMAND\n"
        f"777 Mon Jan 1 00:00:00 2024 {unrelated}\n"
        f"778 Mon Jan 1 00:00:00 2024 {app}/Contents/MacOS/Helpers/FakeVPN\n"
    )
    calls = []
    terms = []

    async def command(argv, *, timeout_s):
        calls.append(argv)
        return (0, ps, "") if argv[0] == "ps" else (0, "", "")

    controller = ClientController(
        app_roots=[tmp_path], command_runner=command, term=lambda *args: terms.append(args)
    )
    await controller.restart("test.fake.vpn")
    assert terms == []
    assert calls[0] == ["ps", "-axo", "pid,lstart,command"]
    assert calls[1] == ["osascript", "-e", 'tell application id "test.fake.vpn" to quit']


@pytest.mark.asyncio
async def test_credential_route_only_reports_configured(tmp_path):
    credentials = MemoryCredentials()
    app = create_app(
        Settings(token="s8-test-token", port=12345, data_dir=tmp_path / "data"),
        credentials=credentials,
        legacy_credentials=FakeLegacy(),
        vpn_client=FakeClient(),
        vpn_network_reader=lambda **kwargs: asyncio.sleep(0, result=NetworkInfo()),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:12345",
        headers={"Authorization": "Bearer s8-test-token"},
    ) as client:
        secret = "FAKE_VPN_PASSWORD_NEVER_ECHO_123"
        response = await client.put("/api/vpn/credentials/vpn_password", json={"value": secret})
        assert response.status_code == 200 and response.json() == {"configured": True}
        snapshot = await client.get("/api/vpn")
        assert snapshot.status_code == 200
        assert snapshot.json()["credentials"]["password"] is True
        assert secret not in snapshot.text and secret not in response.text
        assert credentials.values["vpn_password"] == secret


@pytest.mark.asyncio
async def test_manual_mfa_requires_matching_pending_run_and_accepts_code(tmp_path):
    store = ConfigStore(tmp_path)
    await store.initialize()
    credentials = MemoryCredentials()
    credentials.set("vpn_password", "fake-password")

    class WaitingLogin:
        def __init__(self):
            self.code = None

        async def run(self, config, password, seed, cancel, request_mfa):
            self.code = await request_mfa()

    class ImmediateClient(FakeClient):
        async def open(self, bundle):
            pass

    login = WaitingLogin()
    service = VpnService(
        store,
        credentials,
        FakeLegacy(),
        ImmediateClient(),
        EventHub(),
        login_runner=login,
        network_reader=lambda **kwargs: asyncio.sleep(0, result=NetworkInfo()),
    )
    service._wait_connected = lambda record, deadline: asyncio.sleep(0, result=None)
    run = await service.start(max_rung=3)
    for _ in range(100):
        if service._active and service._active.get("mfa_future"):
            break
        await asyncio.sleep(0.01)
    assert service._active is not None
    with pytest.raises(SettingsError) as exc:
        await service.submit_mfa("unrelated-run", "123456")
    assert exc.value.code == "vpn_mfa_required"
    result = await service.submit_mfa(run.run_id, "123456")
    assert result == {"accepted": True}
    for _ in range(100):
        if service._task is None:
            break
        await asyncio.sleep(0.01)
    assert login.code == "123456"
    assert service.get_run(run.run_id).error_code == "vpn_not_connected"
    await service.close()
