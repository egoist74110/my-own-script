"""Final S4-B security and ownership checks, with no sockets or real credentials."""

import asyncio
import json
import sqlite3
import threading
from types import SimpleNamespace
from urllib.parse import quote

import httpx
import pytest

from tests.independent.s4a.conftest import BOT_TOKEN, open_telegram_app
from tests.test_s4a_boundaries import message, prepare
from toolbox_backend.adapters.telegram_http import TelegramError, TelegramHTTP
from toolbox_backend.domain.settings import DynamicTask, Library, Project
from toolbox_backend.logging_setup import register_secret


@pytest.mark.parametrize("boundary", ["service", "store"])
@pytest.mark.parametrize("variant", ["pat", "encoded", "bot_url"])
async def test_button_labels_never_leak_credentials(tmp_path, caplog, boundary, variant):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        pat = "S4B_FINAL_FAKE_PAT_no_remote_123456"
        register_secret(pat)
        register_secret(BOT_TOKEN)
        label = {
            "pat": pat,
            "encoded": quote(BOT_TOKEN, safe=""),
            "bot_url": "https://api.telegram.org/bot987654:unregistered_fake_token/method",
        }[variant]
        tg = ctx.app.state.telegram_service
        markup = {"inline_keyboard": [[{"text": label, "callback_data": "A" * 22}]]}
        if boundary == "service":
            await tg.enqueue("6001", "secret-label", "请选择任务", reply_markup=markup)
        else:
            await tg.store.enqueue(
                tg.bot_id, "6001", "secret-label", "请选择任务", reply_markup=markup
            )
        forbidden = [
            pat,
            BOT_TOKEN,
            quote(BOT_TOKEN, safe=""),
            "/bot987654:",
            "unregistered_fake_token",
        ]
        # Check before sending: clearing a sent row must not conceal a WAL leak.
        for path in ctx.data_dir.glob("telegram.sqlite3*"):
            content = path.read_bytes()
            assert all(value.encode() not in content for value in forbidden)
        tg.client = TelegramHTTP(BOT_TOKEN, transport=httpx.MockTransport(ctx.bot))
        assert await tg.send_once()
        sent = [
            json.loads(r.content) for r in ctx.bot.requests if r.url.path.endswith("/sendMessage")
        ]
        assert len(sent) == 1
        output = json.dumps(sent) + caplog.text
        assert all(value not in output for value in forbidden)


@pytest.mark.parametrize("count", [4, 5])
async def test_media_total_twenty_mib_limit_before_network(count):
    calls = []

    async def send(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": []})

    client = TelegramHTTP(BOT_TOKEN, transport=httpx.MockTransport(send))
    body = b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024 - 8)
    images = [(f"{i}.png", body, "image/png") for i in range(count)]
    try:
        if count == 4:
            await client.upload_media("6001", images)
            assert len(calls) == 1
        else:
            with pytest.raises(TelegramError, match="bad_response"):
                await client.upload_media("6001", images)
            assert calls == []
    finally:
        await client.close()
    assert client._client.is_closed


async def test_work_item_cache_expires_and_shutdown_releases_state(tmp_path, monkeypatch):
    import toolbox_backend.services.telegram_work_items as module

    clock = [0.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    async with open_telegram_app(tmp_path) as ctx:
        config = await prepare(ctx)

        def seed(c):
            c.ado.libraries = [Library(id="lib:p", name="p", base_url="https://ado.test")]
            c.ado.projects = [
                Project(id="project:p", library_id="lib:p", collection="c", project="p")
            ]

        await ctx.app.state.config_store.update(config.revision, seed)
        tg = ctx.app.state.telegram_service
        wi = tg.dispatcher.work_items
        calls = []

        async def listing(*args):
            calls.append(args)
            return SimpleNamespace(items=[], truncated=False)

        ctx.app.state.work_items_service.listing = listing
        payload = {"project_id": "project:p", "column": "开发中"}
        await wi.listing(message(1), payload)
        clock[0] = 59
        await wi.listing(message(2), payload)
        assert len(calls) == 1
        clock[0] = 61
        await wi.listing(message(3), payload)
        assert len(calls) == 2 and len(wi.cache) == 1
        assert len(wi.state) == 1
        await tg.close()
        assert wi.cache == wi.state == {}
        assert tg.store._db is None and tg.store._fd is None
        assert tg._notification_task is None and tg._work is None


async def test_shutdown_cancels_inflight_album_and_closes_every_owner(tmp_path):
    started, cancelled = asyncio.Event(), asyncio.Event()
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service

        async def remote(request):
            if request.url.path.endswith("/sendPhoto"):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return await ctx.bot._default(request)

        client = TelegramHTTP(BOT_TOKEN, transport=httpx.MockTransport(remote))
        tg.client = client

        async def upload(_):
            await client.upload_media(
                "6001", [("image.png", b"\x89PNG\r\n\x1a\ndata", "image/png")]
            )
            return "handled"

        tg.handle_update = upload
        await tg.store.baseline(tg.bot_id, 0)
        tg.task = asyncio.create_task(tg._session())
        try:
            async with asyncio.timeout(2):
                await asyncio.sleep(0)  # Session initializes its queue before its first await.
                assert tg._work is not None
                await tg.process_updates([message(1)], queued=True)
                await started.wait()
            async with asyncio.timeout(6):
                await tg.close()
            assert cancelled.is_set() and client._client.is_closed
            assert tg._handlers == set() and tg._chat_locks == {}
            assert tg._work is None and tg._poll_task is None and tg.client is None
            assert tg.store._db is None and tg.store._fd is None
        finally:
            await tg.close()


async def test_expired_confirmation_still_prompts_after_another_menu_opens(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        config = await prepare(ctx)
        await ctx.app.state.config_store.update(
            config.revision,
            lambda c: c.tasks.items.append(DynamicTask(id="task:expiry", name="expiry")),
        )
        tg = ctx.app.state.telegram_service
        token = await tg.store.action(
            tg.bot_id,
            "6001",
            "6001",
            "run_confirm",
            {"task_id": "task:expiry", "operation": "sync_build_release", "plan_id": "expired"},
            ttl=-1,
        )
        await tg.store.action(tg.bot_id, "6001", "6001", "menu", {"page": "tasks"})
        await tg.process_updates(
            [
                {
                    "update_id": 1,
                    "callback_query": {
                        "id": "expired",
                        "data": token,
                        "from": {"id": 6001},
                        "message": {"chat": {"id": 6001, "type": "private"}},
                    },
                }
            ]
        )
        with sqlite3.connect(tg.store.path) as db:
            texts = [r[0] for r in db.execute("SELECT text FROM tg_outbox")]
        assert any("计划已过期" in text for text in texts)
        assert (await tg.runs.store.list())["items"] == []


@pytest.mark.parametrize("late", ["return", "reply", "error"])
async def test_shutdown_bound_includes_s2_cancellation_resistant_read(tmp_path, caplog, late):
    from toolbox_backend.services.work_items import OUTBOUND, outbound

    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    unhandled = []
    old_exception_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _, context: unhandled.append(context))
    permits = OUTBOUND._value
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service
        tg.client = TelegramHTTP(BOT_TOKEN, transport=httpx.MockTransport(ctx.bot))

        def slow_read():
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(10), "test must release its owned S2 thread"

        async def read(_):
            try:
                await outbound(slow_read)
            except asyncio.CancelledError:
                # A late adapter result/error must remain isolated even if an
                # intermediary suppresses cancellation after the read finishes.
                if late == "error":
                    raise RuntimeError("S4B_LATE_FAKE_PAT_123456789") from None
                if late == "reply":
                    await tg.reply(message(1), "late response must be discarded")
            return "handled"

        tg.handle_update = read
        await tg.store.baseline(tg.bot_id, 0)
        tg.task = asyncio.create_task(tg._session())
        closing = None
        handler = None
        try:
            await asyncio.sleep(0)
            await tg.process_updates([message(1)], queued=True)
            await asyncio.wait_for(entered.wait(), 2)
            handler = next(iter(tg._handlers))
            closing = asyncio.create_task(tg.close())
            done, _ = await asyncio.wait([closing], timeout=6)
            assert closing in done, "Telegram shutdown exceeded 5s while waiting for an S2 read"
            await closing
            assert not handler.done() and OUTBOUND._value == permits - 1
            assert handler in tg._detached
            assert tg.client is None and tg.store._db is None and tg.store._fd is None
            assert not tg._handlers and not tg._chat_locks and tg._work is None
            fresh_lock = None
            if late == "reply":
                # An old detached scope stays fenced even when service state is
                # reset and a newer session has acquired the same chat identity.
                tg._closing = False
                fresh_lock = asyncio.Lock()
                tg._chat_locks["6001"] = (fresh_lock, 1)
            before = {p.name: p.read_bytes() for p in ctx.data_dir.glob("telegram.sqlite3*")}
            sent = len(ctx.bot.requests)
            db_calls = []
            call = tg.store.call

            async def watched_call(fn, *args, **kwargs):
                db_calls.append(fn.__name__)
                return await call(fn, *args, **kwargs)

            tg.store.call = watched_call
            release.set()
            await asyncio.wait_for(asyncio.gather(handler, return_exceptions=True), 2)
            await asyncio.sleep(0)  # Let the result-observing done callback run.
            assert not tg._detached and not tg._handler_scopes
            assert OUTBOUND._value == permits
            assert db_calls == [] and len(ctx.bot.requests) == sent
            if fresh_lock is not None:
                assert tg._chat_locks["6001"] == (fresh_lock, 1)
            assert {
                p.name: p.read_bytes() for p in ctx.data_dir.glob("telegram.sqlite3*")
            } == before
            assert unhandled == [] and "S4B_LATE_FAKE_PAT" not in caplog.text
            assert caplog.text.count("detached_after_close") <= 1
        finally:
            release.set()
            if closing is not None:
                await closing
            if handler is not None:
                await asyncio.gather(handler, return_exceptions=True)
            await tg.close()
            loop.set_exception_handler(old_exception_handler)


async def test_retry_probe_queues_slow_updates_without_holding_control_lock(tmp_path):
    from toolbox_backend.services.work_items import outbound

    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    async with open_telegram_app(tmp_path) as ctx:
        config = await prepare(ctx)

        def enabled(c):
            c.telegram.control.enabled = True
            c.telegram.control.bot_id = "123456789"

        config = await ctx.app.state.config_store.update(config.revision, enabled)
        ctx.credentials.set("telegram_bot_token", BOT_TOKEN)
        tg = ctx.app.state.telegram_service
        await tg.store.baseline(tg.bot_id, 0)
        tg.status("conflict")
        delivered = False

        async def remote(request):
            nonlocal delivered
            if request.url.path.endswith("/getUpdates") and not delivered:
                delivered = True
                return httpx.Response(200, json={"ok": True, "result": [message(15)]})
            return await ctx.bot._default(request)

        def slow_read():
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(10)

        async def read(_):
            await outbound(slow_read)
            return "handled"

        ctx.bot.handler = remote
        tg.handle_update = read
        retry = asyncio.create_task(tg.retry(config.revision))
        try:
            done, _ = await asyncio.wait([retry], timeout=1)
            assert retry in done, "retry held the control lock while processing a slow update"
            await retry
            await asyncio.wait_for(entered.wait(), 2)
            async with asyncio.timeout(6):
                await tg.disable(config.revision)
            assert tg.state == "disabled" and tg.client is None and tg.store._db is None
        finally:
            release.set()
            await retry
            await tg.close()
            if tg._detached:
                await asyncio.gather(*tg._detached, return_exceptions=True)


async def test_lifespan_closes_runs_before_waiting_for_telegram_reads(tmp_path):
    from toolbox_backend.services.work_items import OUTBOUND, outbound

    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    permits = OUTBOUND._value
    context = open_telegram_app(tmp_path)
    ctx = await context.__aenter__()
    closing, handler = None, None
    runs_closed = asyncio.Event()
    tg = ctx.app.state.telegram_service
    try:
        await prepare(ctx)
        tg.client = TelegramHTTP(BOT_TOKEN, transport=httpx.MockTransport(ctx.bot))
        run_close = ctx.app.state.run_service.close

        async def close_runs():
            await run_close()
            runs_closed.set()

        ctx.app.state.run_service.close = close_runs

        def slow_read():
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(10)

        async def read(_):
            await outbound(slow_read)
            return "handled"

        tg.handle_update = read
        await tg.store.baseline(tg.bot_id, 0)
        tg.task = asyncio.create_task(tg._session())
        await asyncio.sleep(0)
        await tg.process_updates([message(1)], queued=True)
        await asyncio.wait_for(entered.wait(), 2)
        handler = next(iter(tg._handlers))
        closing = asyncio.create_task(context.__aexit__(None, None, None))
        await asyncio.wait_for(runs_closed.wait(), 1)
        done, _ = await asyncio.wait([closing], timeout=6)
        assert closing in done
        await closing
        assert tg.store._db is None and ctx.app.state.run_store._db is None
        assert not handler.done() and OUTBOUND._value == permits - 1
    finally:
        release.set()
        if closing is not None:
            await closing
        else:
            await context.__aexit__(None, None, None)
        if handler is not None:
            await asyncio.gather(handler, return_exceptions=True)
    assert OUTBOUND._value == permits and not tg._detached
