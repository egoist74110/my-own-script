"""S6-B regression tests for WS `mcp` topic, Telegram `/mcp` & menu, and parallel lifespan shutdown budget."""

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.independent.s4b.conftest import (
    buttons,
    message,
    open_telegram_app,
    outbox_texts,
    prepare,
    tap,
)
from tests.test_s6b_lark import _make_lark_prober, _setup_fake_lark_env
from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.api.mcp_schemas import (
    LarkOwnershipRequest,
    McpJobEvent,
    McpJobView,
    McpStatusEvent,
)
from toolbox_backend.api.ws import _drain_incoming, _subscribe_mcp
from toolbox_backend.app import create_app
from toolbox_backend.services.events import EventHub
from toolbox_backend.services.mcp import McpService
from toolbox_backend.settings import Settings


@pytest.mark.asyncio
async def test_mcp_ws_subscribe_replay_live_unsubscribe_and_overflow(tmp_path: Path):
    hub = EventHub(queue_size=16)
    store = ConfigStore(tmp_path / "ws_data")
    await store.initialize()
    svc = McpService(store, MemoryCredentials(), MemoryCredentials(), events=hub)
    snap0 = await svc.snapshot()

    unsubscribed = hub.subscribe()
    sub = hub.subscribe()

    # Publish 2 historical MCP events before subscription
    s1 = hub.publish_mcp(McpStatusEvent, snap0)
    s2 = hub.publish_mcp(
        McpJobEvent,
        McpJobView(
            job_id="job-1",
            state="running",
            started_at="2026-10-26T00:00:00Z",
            output="downloading...",
        ),
    )
    assert s1 == 1
    assert s2 == 2
    assert unsubscribed.queue.empty()

    ws = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(hub=hub)))
    await _subscribe_mcp(ws, sub, {"type": "subscribe", "topic": "mcp", "after_seq": 0})

    frames = []
    while not sub.queue.empty():
        frames.append(json.loads(await sub.queue.get()))

    assert [f["type"] for f in frames] == ["mcp.status", "mcp.job", "mcp.subscribed"]
    assert frames[0]["topic"] == "mcp"
    assert frames[1]["topic"] == "mcp"
    assert frames[2]["topic"] == "mcp"
    assert frames[2]["data"]["last_seq"] == 2

    # Live event after subscribe
    hub.publish_mcp(
        McpJobEvent,
        McpJobView(
            job_id="job-1",
            state="completed",
            started_at="2026-10-26T00:00:00Z",
            finished_at="2026-10-26T00:00:01Z",
            output="ok",
        ),
    )
    live = json.loads(await asyncio.wait_for(sub.queue.get(), timeout=1))
    assert live["type"] == "mcp.job"
    assert live["data"]["state"] == "completed"
    assert live["seq"] > frames[-1]["seq"]
    assert unsubscribed.queue.empty()

    # Unsubscribe via _drain_incoming stops delivery
    class _UnsubSocket:
        def __init__(self, app):
            self.app = app
            self._msgs = iter(
                [
                    {
                        "type": "websocket.receive",
                        "text": json.dumps({"type": "unsubscribe", "topic": "mcp"}),
                    },
                    {"type": "websocket.disconnect"},
                ]
            )

        async def receive(self):
            return next(self._msgs)

        async def close(self, code):
            pass

    await _drain_incoming(_UnsubSocket(ws.app), sub)
    hub.publish_mcp(McpStatusEvent, snap0)
    assert sub.queue.empty()
    hub.unsubscribe(sub)
    hub.unsubscribe(unsubscribed)

    # Slow subscriber overflow on mcp topic
    small_hub = EventHub(queue_size=2)
    slow = small_hub.subscribe()
    fast = small_hub.subscribe()
    slow.mcp_after = 0
    fast.mcp_after = 0
    for i in range(3):
        small_hub.publish_mcp(
            McpJobEvent,
            McpJobView(
                job_id="job-overflow",
                state="running",
                started_at="2026-10-26T00:00:00Z",
                output=f"s{i}",
            ),
        )
        if i == 0:
            _ = fast.queue.get_nowait()
    assert slow.overflowed.is_set()
    assert not fast.overflowed.is_set()
    small_hub.unsubscribe(fast)


@pytest.mark.asyncio
async def test_telegram_mcp_owner_only_menu_status_and_lark_start_stop(
    monkeypatch, tmp_path: Path
):
    # Patch supervisor process_identity for sandbox compatibility
    original = asyncio.create_subprocess_exec

    async def spawn(*argv, **kwargs):
        if len(argv) >= 3 and argv[1:3] == ("-m", "toolbox_backend.adapters.proc_supervisor"):
            argv = (
                argv[0],
                "-c",
                "import sys; from toolbox_backend.adapters import proc_supervisor as m; "
                "m.process_identity=lambda pid: {}; sys.exit(m.main())",
            )
        return await original(*argv, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx, owner="6001")
        tg = ctx.app.state.telegram_service
        mcp = ctx.app.state.mcp_service

        # 1. Non-owner /mcp is ignored without reply or side effect
        before_texts = list(await outbox_texts(ctx))
        await tg.process_updates([message(300, text="/mcp", chat=6002)])
        after_texts = list(await outbox_texts(ctx))
        assert after_texts == before_texts

        # 2. Owner /start menu contains single "MCP" button (without status suffix)
        await tg.process_updates([message(301, text="/start", chat=6001)])
        menu_labels = [b["text"] for b in await buttons(ctx)]
        assert "🧩 MCP" in menu_labels

        # 3. Owner /mcp displays status summary and Lark start button (no ADO/Figma start or CLI inject)
        mcp.path_extras = []
        await tg.process_updates([message(302, text="/mcp", chat=6001)])
        mcp_texts = await outbox_texts(ctx)
        latest_text = mcp_texts[-1]
        assert "MCP" in latest_text
        assert "ADO" in latest_text
        assert "Figma" in latest_text
        assert "Lark" in latest_text
        panel_buttons = [b["text"] for b in await buttons(ctx)]
        assert any("启动 Lark" in b for b in panel_buttons)
        assert not any("启动 ADO" in b or "启动 Figma" in b or "注入" in b for b in panel_buttons)

        # 4. Tapping "启动 Lark MCP" before ownership confirmed -> fixed Chinese error message
        await tap(ctx, 303, "启动 Lark", chat=6001)
        err_texts = await outbox_texts(ctx)
        assert any("所有权" in t for t in err_texts)

        # 5. Setup fake Lark runtime + secret + confirm ownership, then start & stop via TG buttons
        lark_tg = tmp_path / "lark_tg"
        lark_tg.mkdir(parents=True, exist_ok=True)
        saved_cfg = await ctx.app.state.config_store.read()
        _, fake_creds, _, _ = _setup_fake_lark_env(
            ctx.data_dir, lark_tg, owner_confirmed=True
        )
        new_cfg = await ctx.app.state.config_store.read()
        new_cfg.telegram = saved_cfg.telegram
        new_cfg.tasks = saved_cfg.tasks
        ctx.app.state.config_store._write(new_cfg)
        ctx.app.state.settings_service.credentials.set(
            "lark_app_secret:cli_test_app",
            fake_creds.get("lark_app_secret:cli_test_app"),
        )
        mcp.path_extras = [lark_tg / "fake_lark_bin"]
        mcp.lark_http_prober = _make_lark_prober(lark_tg)
        await mcp.confirm_lark_ownership(LarkOwnershipRequest(ack_old_app_stopped=True))

        await tg.process_updates([message(304, text="/mcp", chat=6001)])
        await tap(ctx, 305, "启动 Lark", chat=6001)
        assert (await mcp.snapshot()).lark.state == "running"
        running_buttons = [b["text"] for b in await buttons(ctx)]
        assert any("停止 Lark" in b for b in running_buttons)

        await tap(ctx, 306, "停止 Lark", chat=6001)
        assert (await mcp.snapshot()).lark.state == "stopped"


@pytest.mark.asyncio
async def test_lifespan_parallel_shutdown_budget_under_5s(tmp_path: Path):
    data_dir = tmp_path / "data"
    app = create_app(
        Settings(token="tok-life", port=59998, data_dir=data_dir),
        credentials=MemoryCredentials(),
        legacy_credentials=MemoryCredentials(),
    )

    async def slow_ai_close():
        await asyncio.sleep(3.2)

    async def slow_mcp_close():
        await asyncio.sleep(3.2)

    app.state.ai_service.close = slow_ai_close
    app.state.mcp_service.close = slow_mcp_close

    async with app.router.lifespan_context(app):
        t0 = time.monotonic()
    elapsed = time.monotonic() - t0
    # Parallel asyncio.gather(ai.close(), mcp.close()) takes ~3.2s (< 5.0s budget), not 6.4s!
    assert elapsed < 4.8
