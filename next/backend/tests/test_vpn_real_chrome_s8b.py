"""Opt-in acceptance: system Chrome, loopback page, s8probe scheme, temporary profile only."""

import asyncio
import shutil
import sys

import pytest

from toolbox_backend.adapters.vpn_browser import ChromeRegistry, inspect_process
from toolbox_backend.vpn import login_worker

pytestmark = [
    pytest.mark.real_chrome,
    pytest.mark.skipif(sys.platform != "darwin", reason="macOS Chrome"),
]


@pytest.mark.parametrize("headless", [True, False])
async def test_loopback_cdp_first_callback_cookie_persistence_and_reclaim(
    tmp_path, monkeypatch, headless
):
    body = b"<!doctype html><title>S8 local fixture</title><p>loopback only</p>"

    async def serve(reader, writer):
        try:
            await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 3)
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    table = {**login_worker.SELECTORS["perimeter81"], "entry": f"http://127.0.0.1:{port}/"}
    monkeypatch.setitem(login_worker.SELECTORS, "perimeter81", table)
    # All non-loopback browser traffic is sent to a closed local proxy, including background services.
    monkeypatch.setattr(
        login_worker,
        "CHROME_ARGS",
        [
            *login_worker.CHROME_ARGS,
            "--proxy-server=http://127.0.0.1:9",
            "--proxy-bypass-list=127.0.0.1",
            "--disable-quic",
        ],
    )
    registry = ChromeRegistry(tmp_path)
    identities = []
    driver = None

    def emit(event, **fields):
        assert event == "chrome_started"
        registry.record(fields)
        identities.append(fields)

    try:
        for round_ in range(2):
            driver = login_worker.PlaywrightDriver(
                dict(data_dir=str(tmp_path), scheme="s8probe", headless=headless, has_seed=True),
                emit,
            )
            await driver.start()
            await driver.page.goto(f"http://127.0.0.1:{port}/")
            if round_:
                assert "s8probe=retained" in await driver.page.evaluate("document.cookie")
            assert await driver.page.evaluate("navigator.webdriver") is False
            await driver.page.evaluate("document.cookie='s8probe=retained;path=/;max-age=3600'")
            await driver.page.evaluate(
                "setTimeout(() => { location.href='S8Probe://callback#id_token=S8_FAKE_TOKEN'; }, 0)"
            )
            # Chrome canonicalises the scheme to lower case in the navigation event.
            assert await driver.callback() == "s8probe://callback#id_token=S8_FAKE_TOKEN"
            await driver.close()
            driver = None
            await registry.cleanup()
        for identity in identities:
            row = await inspect_process(identity["pid"])
            assert row is None or row["lstart"] != identity["lstart"]
    finally:
        try:
            if driver:
                await driver.close()
        finally:
            try:
                await registry.cleanup()
            finally:
                server.close()
                await server.wait_closed()
                if (tmp_path / "vpn").exists():
                    shutil.rmtree(tmp_path / "vpn")
