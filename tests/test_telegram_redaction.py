"""WP-12 / D02: Telegram 错误脱敏。全离线：httpx.MockTransport，无真实网络/Keychain/用户配置。"""

import json
import socket
import threading
from types import SimpleNamespace

import httpx
import keyring
import pytest

from app_ado import notifier_telegram, notifier_telegram_meta, store, tg_control
from app_ado.redact import redact_exception, redact_text

FAKE_TOKEN = "123456:FAKE-TELEGRAM-TOKEN-only"


@pytest.fixture(autouse=True)
def reject_real_side_effects(monkeypatch):
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append("unexpected network, credential or config access")
        raise AssertionError(attempts[-1])

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    for name in ("get_password", "set_password", "delete_password", "get_credential"):
        monkeypatch.setattr(keyring, name, forbidden)
    for module in (store, tg_control):
        for name in ("config_dir", "load_ui_settings", "load_task_settings", "save_ui_settings"):
            monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(tg_control, "get_telegram_token", forbidden)
    yield
    assert attempts == [], "A forbidden real side effect was attempted"


def _patch_client(monkeypatch, module, handler):
    real_client = httpx.Client
    monkeypatch.setattr(module.httpx, "Client", lambda *a, **kw: real_client(*a, **kw, transport=httpx.MockTransport(handler)))


def run_one_poll(monkeypatch, handler, token=FAKE_TOKEN):
    c = object.__new__(tg_control.TelegramController)
    c._stop = threading.Event()
    c._token_fn = lambda: token
    c._webhook_cleared = True
    c._update_offset = None
    logs, states, sleeps, deletes = [], [], [], []
    monkeypatch.setattr(c, "_log", logs.append)
    monkeypatch.setattr(c, "_write_state", lambda **s: states.append(s))
    monkeypatch.setattr(c, "_save_offset", lambda *_: None)
    monkeypatch.setattr(c, "_delete_webhook", lambda t: deletes.append(t))
    monkeypatch.setattr(tg_control, "load_ui_settings", lambda: SimpleNamespace(telegram_control_enabled=True))

    def finish(seconds):
        sleeps.append(seconds)
        c._stop.set()

    monkeypatch.setattr(tg_control, "time", SimpleNamespace(sleep=finish, strftime=lambda *_: "fixture-time"))
    _patch_client(monkeypatch, tg_control, handler)
    c._run_loop()
    return logs, states, sleeps, deletes


def assert_no_token(*blobs):
    for b in blobs:
        assert FAKE_TOKEN not in json.dumps(b, ensure_ascii=False, default=str)
        assert "FAKE-TELEGRAM-TOKEN" not in json.dumps(b, ensure_ascii=False, default=str)


def test_401_redacts_log_and_state_but_keeps_diagnostics(monkeypatch):
    logs, states, sleeps, deletes = run_one_poll(
        monkeypatch, lambda r: httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
    )
    assert_no_token(logs, states)
    assert "401" in logs[0] and "/bot***/getUpdates" in logs[0]
    assert "401" in states[-1]["last_error"] and "/bot***/getUpdates" in states[-1]["last_error"]
    assert sleeps == [2.0] and deletes == []


def test_409_branch_unchanged_and_redacted(monkeypatch):
    logs, states, sleeps, deletes = run_one_poll(
        monkeypatch, lambda r: httpx.Response(409, json={"ok": False, "description": "Conflict: terminated by other getUpdates"})
    )
    assert_no_token(logs, states)
    assert "409" in states[-1]["last_error"]
    assert deletes == [FAKE_TOKEN]  # 仍走 delete_webhook 分支
    assert sleeps == [5.0]


def test_timeout_branch_unchanged_and_redacted(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout(f"The read operation timed out while calling {request.url}", request=request)

    logs, states, sleeps, deletes = run_one_poll(monkeypatch, handler)
    assert_no_token(logs, states)
    assert "timed out" in logs[0] and "/bot***/getUpdates" in logs[0]
    assert sleeps == [1.0] and deletes == []  # 超时短睡眠


def test_chained_exception_is_redacted_and_keeps_types(monkeypatch):
    def handler(request):
        try:
            raise httpx.ConnectError(f"boom {request.url}", request=request)
        except httpx.ConnectError as inner:
            raise RuntimeError("wrapper failure") from inner

    logs, states, sleeps, _ = run_one_poll(monkeypatch, handler)
    assert_no_token(logs, states)
    assert "wrapper failure" in logs[0] and "ConnectError" in logs[0]
    assert sleeps == [2.0]


def test_error_text_with_authorization_header_is_redacted():
    out = redact_text("headers={'Authorization': 'Bearer SECRET-ABC'} status 500")
    assert "SECRET-ABC" not in out and "500" in out
    assert "SECRET-ABC" not in redact_text("authorization: Basic SECRET-ABC")


def test_known_token_redacted_anywhere_without_url():
    out = redact_text(f"bad value {FAKE_TOKEN} in body", FAKE_TOKEN)
    assert FAKE_TOKEN not in out and "bad value" in out


def test_missing_token_does_not_raise(monkeypatch):
    assert redact_text("plain 404 /bot***/x", None, "") == "plain 404 /bot***/x"
    assert redact_text(None, None) == "None"

    assert "ValueError" not in redact_exception(ValueError("x"), None) and redact_exception(ValueError("x"), None) == "x"


def test_write_state_and_log_defense_in_depth(tmp_path):
    c = object.__new__(tg_control.TelegramController)
    c._state_path = tmp_path / "state.json"
    c._log_path = tmp_path / "log.txt"
    url = f"https://api.telegram.org/bot{FAKE_TOKEN}/getUpdates"
    c._write_state(state="x", last_error=f"Client error 401 for url '{url}'")
    c._log(f"error {url}")
    assert_no_token(c._state_path.read_text("utf-8"), c._log_path.read_text("utf-8"))
    assert "/bot***/getUpdates" in c._state_path.read_text("utf-8")


@pytest.mark.parametrize("status", [401, 400, 500])
def test_notifier_message_error_has_no_token(monkeypatch, status):
    _patch_client(monkeypatch, notifier_telegram, lambda r: httpx.Response(status, json={"ok": False, "description": "Unauthorized"}))
    with pytest.raises(RuntimeError) as ei:
        notifier_telegram.send_telegram_message(bot_token=FAKE_TOKEN, chat_id="1", text="hi")
    msg = str(ei.value)
    assert_no_token(msg, repr(ei.value))
    assert str(status) in msg and "Unauthorized" in msg and "/bot***/sendMessage" in msg and "POST" in msg
    assert ei.value.__cause__ is None


def test_notifier_photo_error_has_no_token(monkeypatch):
    _patch_client(monkeypatch, notifier_telegram, lambda r: httpx.Response(401, json={"ok": False, "description": "Unauthorized"}))
    with pytest.raises(RuntimeError) as ei:
        notifier_telegram.send_telegram_photo(bot_token=FAKE_TOKEN, chat_id="1", photo=b"x")
    assert_no_token(str(ei.value))
    assert "401" in str(ei.value) and "/bot***/sendPhoto" in str(ei.value)


def test_notifier_ok_false_payload_echoing_token_is_redacted(monkeypatch):
    _patch_client(monkeypatch, notifier_telegram, lambda r: httpx.Response(200, json={"ok": False, "description": f"echo {FAKE_TOKEN}"}))
    with pytest.raises(RuntimeError) as ei:
        notifier_telegram.send_telegram_message(bot_token=FAKE_TOKEN, chat_id="1", text="hi")
    assert_no_token(str(ei.value))


@pytest.mark.parametrize("status", [401, 404, 500])
def test_get_me_http_error_has_no_token(monkeypatch, status):
    """CR-NEXT-002：get_me 的 HTTP 错误不携带 bot URL，保留状态码与路径。"""
    _patch_client(monkeypatch, notifier_telegram_meta, lambda r: httpx.Response(status, json={"ok": False, "description": "Unauthorized"}))
    with pytest.raises(RuntimeError) as ei:
        notifier_telegram_meta.get_me(bot_token=FAKE_TOKEN)
    assert_no_token(str(ei.value), repr(ei.value))
    assert str(status) in str(ei.value) and "/bot***/getMe" in str(ei.value)
    assert ei.value.__cause__ is None and ei.value.__context__ is None


def test_get_me_transport_error_has_no_token(monkeypatch):
    def boom(request):
        raise httpx.ConnectError(f"connect failed for {request.url}", request=request)

    _patch_client(monkeypatch, notifier_telegram_meta, boom)
    with pytest.raises(RuntimeError) as ei:
        notifier_telegram_meta.get_me(bot_token=FAKE_TOKEN)
    assert_no_token(str(ei.value))
    assert "connect failed" in str(ei.value) and ei.value.__context__ is None


def test_get_me_ok_false_payload_echoing_token_is_redacted(monkeypatch):
    _patch_client(monkeypatch, notifier_telegram_meta, lambda r: httpx.Response(200, json={"ok": False, "description": f"echo {FAKE_TOKEN}"}))
    with pytest.raises(RuntimeError) as ei:
        notifier_telegram_meta.get_me(bot_token=FAKE_TOKEN)
    assert_no_token(str(ei.value))
    assert "getMe failed" in str(ei.value)


def test_get_me_success_unchanged(monkeypatch):
    _patch_client(monkeypatch, notifier_telegram_meta, lambda r: httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "bot", "first_name": "B"}}))
    info = notifier_telegram_meta.get_me(bot_token=FAKE_TOKEN)
    assert (info.id, info.username, info.first_name) == ("1", "bot", "B")


# ---------------------------------------------------------------------------
# 独立补充用例（WP-12 独立测试者）：从不同角度尝试打破脱敏。全部离线。
# ---------------------------------------------------------------------------

ALT_TOKEN = "987654:AAE_x-Y_z-Q-FAKE-ALT"


def test_token_with_dash_underscore_redacted_in_poll_error_and_state(monkeypatch):
    logs, states, sleeps, _ = run_one_poll(
        monkeypatch,
        lambda r: httpx.Response(401, json={"ok": False, "description": "Unauthorized"}),
        token=ALT_TOKEN,
    )
    blob = json.dumps([logs, states], ensure_ascii=False)
    assert "AAE_x-Y_z-Q-FAKE-ALT" not in blob and ALT_TOKEN not in blob
    assert "/bot***/getUpdates" in logs[0] and "401" in logs[0]
    assert sleeps == [2.0]


def test_percent_encoded_colon_in_bot_path_is_redacted():
    out = redact_text("GET https://api.telegram.org/bot123456%3AFAKE-TELEGRAM-TOKEN-only/getUpdates 401")
    assert "FAKE-TELEGRAM-TOKEN" not in out and "/bot***/getUpdates" in out and "401" in out


def test_json_escaped_bot_url_in_telegram_body_is_redacted():
    body = '{"ok":false,"description":"see https:\\/\\/api.telegram.org\\/bot123456:FAKE-TELEGRAM-TOKEN-only\\/getUpdates"}'
    out = redact_text(body)
    assert "FAKE-TELEGRAM-TOKEN" not in out and "/bot***" in out and "description" in out


def test_known_token_that_is_prefix_of_another_token_fully_masked():
    out = redact_text("a 123:AB and 123:ABCD and 123:ABCDEF end", "123:AB", "123:ABCD")
    assert "123:AB" not in out and "ABCD" not in out
    assert out.startswith("a ") and out.endswith(" end")


def test_duplicate_known_tokens_all_occurrences_replaced():
    t = FAKE_TOKEN
    out = redact_text(f"{t} | /bot{t}/x | {t} | {t}", t, t, "", None)
    assert t not in out and "FAKE-TELEGRAM-TOKEN" not in out
    assert out.count("***") >= 4


def test_known_token_with_dash_underscore_in_plain_text_replaced():
    out = redact_text(f"value={ALT_TOKEN};next", ALT_TOKEN)
    assert ALT_TOKEN not in out and "value=" in out and ";next" in out


def test_idempotent_redaction():
    once = redact_text(f"https://x/bot{FAKE_TOKEN}/getUpdates {FAKE_TOKEN}", FAKE_TOKEN)
    assert redact_text(once, FAKE_TOKEN) == once


def test_non_string_unprintable_object_does_not_raise():
    class Bad:
        def __str__(self):
            raise ValueError("no str")

    assert redact_text(Bad(), None) == "<unprintable>"


def test_deep_cause_and_context_chain_redacts_every_level_in_budget():
    # 第 1 层为 head，其余层最多 5 层；token 位于深层 cause/context 中
    e4 = httpx.ConnectError(f"deep {FAKE_TOKEN}")
    e3 = RuntimeError("level3")
    e3.__cause__ = e4
    e2 = ValueError("level2")
    e2.__context__ = e3
    e1 = KeyError("level1")
    e1.__cause__ = e2
    out = redact_exception(e1, FAKE_TOKEN)
    assert FAKE_TOKEN not in out and "FAKE-TELEGRAM-TOKEN" not in out
    assert "ConnectError" in out and "level3" in out


def test_cyclic_exception_chain_terminates_and_redacts():
    a = RuntimeError(f"a {FAKE_TOKEN}")
    b = RuntimeError(f"b /bot{FAKE_TOKEN}/getUpdates")
    a.__context__ = b
    b.__context__ = a
    out = redact_exception(a, FAKE_TOKEN)
    assert FAKE_TOKEN not in out and "b /bot***/getUpdates" in out


def test_token_beyond_chain_budget_is_omitted_not_leaked():
    # 超过 6 层的异常文本被整体丢弃（不泄露）
    tail = httpx.ConnectError(f"very deep {FAKE_TOKEN}")
    cur = tail
    for i in range(8):
        nxt = RuntimeError(f"mid{i}")
        nxt.__cause__ = cur
        cur = nxt
    out = redact_exception(cur, FAKE_TOKEN)
    assert FAKE_TOKEN not in out and "very deep" not in out


@pytest.mark.parametrize(
    "raw",
    [
        "Proxy-Authorization: Basic SECRET-ABC",
        "authorization = 'Bearer SECRET-ABC'",
        '{"Authorization": "Bearer SECRET-ABC"}',
        "headers={'authorization': 'token SECRET-ABC'}",
    ],
)
def test_authorization_header_variants_are_redacted(raw):
    out = redact_text(raw)
    assert "SECRET-ABC" not in out
    assert "Authorization" in out or "authorization" in out


def test_authorization_header_with_other_scheme_is_redacted():
    assert "SECRET-XYZ" not in redact_text("Authorization: ApiKey SECRET-XYZ")


def test_custom_token_header_is_redacted():
    assert "SECRET-XYZ" not in redact_text("X-Telegram-Bot-Api-Secret-Token: SECRET-XYZ")


def test_percent_encoded_known_token_in_query_string_is_redacted():
    out = redact_text("https://x/cb?token=123456%3AFAKE-TELEGRAM-TOKEN-only", FAKE_TOKEN)
    assert "FAKE-TELEGRAM-TOKEN" not in out


def test_run_loop_500_keeps_status_and_redacts(monkeypatch):
    logs, states, sleeps, deletes = run_one_poll(
        monkeypatch, lambda r: httpx.Response(500, text=f"upstream echo /bot{FAKE_TOKEN}/getUpdates")
    )
    assert_no_token(logs, states)
    assert "500" in logs[0] and "/bot***/getUpdates" in logs[0]
    assert sleeps == [2.0] and deletes == []


def test_run_loop_ok_false_200_echoing_token_is_redacted(monkeypatch):
    logs, states, sleeps, deletes = run_one_poll(
        monkeypatch, lambda r: httpx.Response(200, json={"ok": False, "description": f"Unauthorized {FAKE_TOKEN}"})
    )
    assert_no_token(logs, states)
    assert "Unauthorized" in logs[0] and "telegram getUpdates failed" in logs[0]
    assert sleeps == [2.0] and deletes == []


def test_run_loop_200_conflict_description_keeps_409_branch(monkeypatch):
    logs, states, sleeps, deletes = run_one_poll(
        monkeypatch,
        lambda r: httpx.Response(200, json={"ok": False, "description": f"Conflict: other getUpdates {FAKE_TOKEN}"}),
    )
    assert_no_token(logs, states)
    assert "Conflict" in states[-1]["last_error"]
    assert deletes == [FAKE_TOKEN] and sleeps == [5.0]


@pytest.mark.parametrize("token", [None, ""])
def test_run_loop_missing_token_sleeps_without_error(monkeypatch, token):
    def forbidden_handler(request):
        raise AssertionError("getUpdates must not be called without a token")

    logs, states, sleeps, deletes = run_one_poll(monkeypatch, forbidden_handler, token=token)
    assert logs == [] and deletes == []
    assert sleeps == [2.0]


def test_run_loop_403_redacts_and_uses_default_sleep(monkeypatch):
    logs, states, sleeps, deletes = run_one_poll(
        monkeypatch, lambda r: httpx.Response(403, json={"ok": False, "description": "Forbidden"})
    )
    assert_no_token(logs, states)
    assert "403" in states[-1]["last_error"] and "/bot***/getUpdates" in states[-1]["last_error"]
    assert sleeps == [2.0] and deletes == []


def test_wrapped_exception_with_timeout_cause_still_uses_default_sleep(monkeypatch):
    def handler(request):
        try:
            raise httpx.ReadTimeout("timed out", request=request)
        except httpx.ReadTimeout as inner:
            raise RuntimeError("wrapper failure") from inner

    logs, states, sleeps, deletes = run_one_poll(monkeypatch, handler)
    assert_no_token(logs, states)
    assert sleeps == [2.0] and deletes == []


def test_wrapped_exception_with_409_cause_still_uses_default_branch(monkeypatch):
    def handler(request):
        try:
            raise httpx.HTTPStatusError(
                "Client error '409 Conflict' for url 'https://api.telegram.org/bot/getUpdates'",
                request=request,
                response=httpx.Response(409, request=request),
            )
        except httpx.HTTPStatusError as inner:
            raise RuntimeError("wrapper failure") from inner

    logs, states, sleeps, deletes = run_one_poll(monkeypatch, handler)
    assert_no_token(logs, states)
    assert sleeps == [2.0] and deletes == []


def test_notifier_500_body_echoing_token_and_url_is_redacted(monkeypatch):
    body = f"internal {FAKE_TOKEN} https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage"
    _patch_client(monkeypatch, notifier_telegram, lambda r: httpx.Response(500, text=body))
    with pytest.raises(RuntimeError) as ei:
        notifier_telegram.send_telegram_message(bot_token=FAKE_TOKEN, chat_id="1", text="hi")
    msg = str(ei.value)
    assert_no_token(msg, repr(ei.value))
    assert "500" in msg and "POST" in msg and "/bot***/sendMessage" in msg and "internal" in msg


def test_notifier_parse_mode_retry_second_failure_is_redacted(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(400, json={"ok": False, "description": "Bad Request: can't parse entities"})

    _patch_client(monkeypatch, notifier_telegram, handler)
    with pytest.raises(RuntimeError) as ei:
        notifier_telegram.send_telegram_message(bot_token=FAKE_TOKEN, chat_id="1", text="hi", parse_mode="Markdown")
    assert len(calls) == 2
    msg = str(ei.value)
    assert_no_token(msg)
    assert "400" in msg and "can't parse entities" in msg and "/bot***/sendMessage" in msg


def test_notifier_ok_false_with_200_redacts_token(monkeypatch):
    _patch_client(
        monkeypatch,
        notifier_telegram,
        lambda r: httpx.Response(200, json={"ok": False, "description": f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage {FAKE_TOKEN}"}),
    )
    with pytest.raises(RuntimeError) as ei:
        notifier_telegram.send_telegram_message(bot_token=FAKE_TOKEN, chat_id="1", text="hi")
    assert_no_token(str(ei.value))
    assert "telegram send failed" in str(ei.value)


def test_notifier_photo_500_and_ok_false_paths_have_no_token(monkeypatch):
    _patch_client(monkeypatch, notifier_telegram, lambda r: httpx.Response(500, text=f"x {FAKE_TOKEN}"))
    with pytest.raises(RuntimeError) as ei:
        notifier_telegram.send_telegram_photo(bot_token=FAKE_TOKEN, chat_id="1", photo=b"x")
    assert_no_token(str(ei.value), repr(ei.value))
    assert "500" in str(ei.value) and "/bot***/sendPhoto" in str(ei.value)


def test_notifier_photo_ok_false_path_has_no_token(monkeypatch):
    _patch_client(monkeypatch, notifier_telegram, lambda r: httpx.Response(200, json={"ok": False, "description": FAKE_TOKEN}))
    with pytest.raises(RuntimeError) as ei:
        notifier_telegram.send_telegram_photo(bot_token=FAKE_TOKEN, chat_id="1", photo=b"x")
    assert_no_token(str(ei.value))
    assert "telegram sendPhoto failed" in str(ei.value)


def test_notifier_empty_token_does_not_raise(monkeypatch):
    _patch_client(monkeypatch, notifier_telegram, lambda r: httpx.Response(401, json={"ok": False, "description": "Unauthorized"}))
    with pytest.raises(RuntimeError) as ei:
        notifier_telegram.send_telegram_message(bot_token="", chat_id="1", text="hi")
    assert "401" in str(ei.value) and "Unauthorized" in str(ei.value)


def test_notifier_context_suppressed_in_formatted_traceback(monkeypatch):
    import traceback

    _patch_client(monkeypatch, notifier_telegram, lambda r: httpx.Response(401, json={"ok": False, "description": "Unauthorized"}))
    with pytest.raises(RuntimeError) as ei:
        notifier_telegram.send_telegram_message(bot_token=FAKE_TOKEN, chat_id="1", text="hi")
    rendered = "".join(traceback.format_exception(ei.value))
    assert_no_token(rendered)
    assert ei.value.__suppress_context__ is True


def test_notifier_context_attribute_does_not_retain_token(monkeypatch):
    _patch_client(monkeypatch, notifier_telegram, lambda r: httpx.Response(401, json={"ok": False, "description": "Unauthorized"}))
    with pytest.raises(RuntimeError) as ei:
        notifier_telegram.send_telegram_message(bot_token=FAKE_TOKEN, chat_id="1", text="hi")
    assert FAKE_TOKEN not in repr(ei.value.__context__)
