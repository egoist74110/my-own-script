"""Offline current_behavior evidence: passing means these defects still exist.

Stage 1 MUST replace the corresponding defect assertions with correct contracts:
D01/WP-11: external image origins must never receive PAT authorization.
D02/WP-12: Telegram errors retain diagnostics but redact tokens in log/state.
D04/WP-13: an explicitly empty tasks list must stay empty despite legacy flows.
D06/WP-15: unknown branch/detail failure must never authorize build adoption.
D08/WP-14: handshake must be bounded, status lock available, failed child fully
reaped and pipes closed. These are characterization tests, not safety acceptance.
"""

import base64
import io
import socket
import threading
from copy import deepcopy
from types import SimpleNamespace

import httpx
import keyring
import pytest

from app_ado import ado_build_http, ado_work_item_http, mcp_server_manager, store
from app_ado import tg_control, work_item_view
from app_ado.task_migrate import migrate_task_settings


@pytest.fixture(autouse=True)
def reject_real_side_effects(monkeypatch):
    """Record even swallowed attempts; restore every patch after each test."""
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append("unexpected network, credential, process or config access")
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
    monkeypatch.setattr(mcp_server_manager.subprocess, "Popen", forbidden)
    yield
    assert attempts == [], "A forbidden real side effect was attempted"


def test_current_behavior_d01_external_inline_image_receives_fake_pat(monkeypatch):
    external = "https://external-image.invalid/screenshot.png"
    fake_pat = "FAKE-ADO-PAT-characterization-only"
    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.host == "external-image.invalid"
        return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nfixture", headers={"content-type": "image/png"})

    real_client = httpx.Client

    def offline_client(*args, **kwargs):
        return real_client(*args, **kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(ado_work_item_http.httpx, "Client", offline_client)
    item = ado_work_item_http.WorkItem(
        id=1, rev=1, title="fixture", state=None, work_item_type=None,
        assigned_to=None, board_column=None, board_column_done=None, url=None,
        fields={"System.Description": f'<img src="{external}">'}, relations=[],
    )
    urls = work_item_view.collect_image_urls(item)
    assert urls == [external]
    blobs = work_item_view.fetch_image_blobs(urls, pat=fake_pat)
    assert len(requests) == 1
    expected = "Basic " + base64.b64encode(f":{fake_pat}".encode()).decode()
    assert requests[0].headers["authorization"] == expected, "current_behavior D01: external origin receives PAT"
    assert blobs == [("screenshot.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")]


def test_current_behavior_d02_fake_401_token_enters_log_and_state(monkeypatch):
    controller = object.__new__(tg_control.TelegramController)
    fake_token = "123456:FAKE-TELEGRAM-TOKEN-only"
    controller._stop = threading.Event()
    controller._token_fn = lambda: fake_token
    controller._webhook_cleared = True
    controller._update_offset = None
    logs, states, requests = [], [], []
    monkeypatch.setattr(controller, "_log", logs.append)
    monkeypatch.setattr(controller, "_write_state", lambda **state: states.append(state))
    monkeypatch.setattr(controller, "_save_offset", lambda *_: pytest.fail("no update should be saved"))
    monkeypatch.setattr(controller, "_delete_webhook", lambda *_: pytest.fail("webhook must be bypassed"))
    polls = []

    def settings_for_one_poll():
        polls.append(True)
        if len(polls) > 1:
            pytest.fail("poll loop exceeded its one-iteration test budget")
        return SimpleNamespace(telegram_control_enabled=True)

    monkeypatch.setattr(tg_control, "load_ui_settings", settings_for_one_poll)
    sleeps = []

    def finish_loop(seconds):
        sleeps.append(seconds)
        controller._stop.set()

    # Replace only this module's time reference, never stdlib time.sleep.
    monkeypatch.setattr(tg_control, "time", SimpleNamespace(sleep=finish_loop, strftime=lambda *_: "fixture-time"))

    def respond(request):
        requests.append(request)
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    real_client = httpx.Client
    monkeypatch.setattr(tg_control.httpx, "Client", lambda *a, **kw: real_client(*a, **kw, transport=httpx.MockTransport(respond)))
    controller._run_loop()
    assert polls == [True]
    assert controller._stop.is_set() and sleeps == [2.0]
    assert len(requests) == 1 and requests[0].url.path == f"/bot{fake_token}/getUpdates"
    assert len(logs) == 1 and fake_token in logs[0] and "401" in logs[0], "current_behavior D02: log leaks token"
    assert len(states) == 2
    assert fake_token in states[-1]["last_error"] and "401" in states[-1]["last_error"], "current_behavior D02: state leaks token"


def test_current_behavior_d04_clearing_tasks_with_retained_flows_resurrects_tasks():
    legacy = {"flows": [{"id": "sync_build_release", "target_branch": "main"}]}
    original = deepcopy(legacy)
    migrated, changed = migrate_task_settings(legacy)
    assert changed and len(migrated.tasks) == 1
    saved = migrated.model_dump(mode="json")
    saved["tasks"] = []  # User deliberately deleted the migrated tasks.
    before = deepcopy(saved)
    resurrected, changed_again = migrate_task_settings(saved)
    assert changed_again and len(resurrected.tasks) == 1, "current_behavior D04: explicit empty tasks repopulated"
    assert resurrected.tasks[0].legacy_flow_id == "sync_build_release"
    assert resurrected.tasks[0].id != migrated.tasks[0].id
    assert saved == before and legacy == original


def test_current_behavior_d06_unknown_branch_is_adopted_after_detail_failure(monkeypatch):
    run = ado_build_http.PipelineRun("definition-fixture", "run-fixture", "inProgress", None)
    calls = []

    def list_runs(*args, **kwargs):
        calls.append(("list", args, kwargs))
        return [run]

    def failed_detail(*args, **kwargs):
        calls.append(("detail", args, kwargs))
        raise RuntimeError("fixture detail unavailable")

    monkeypatch.setattr(ado_build_http, "list_pipeline_runs", list_runs)
    monkeypatch.setattr(ado_build_http, "get_pipeline_run", failed_detail)
    adopted = ado_build_http.find_matching_run(
        "https://ado.invalid", "collection", "project", "pipeline", "definition-fixture",
        branch="release/fixture", pat="FAKE-PAT-only",
    )
    assert [call[0] for call in calls] == ["list", "detail"]
    assert adopted is run and adopted.branch is None, "current_behavior D06: unavailable branch still adopted"


def test_current_behavior_d08_handshake_holds_status_lock_and_failure_only_terminates(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls, results, errors = [], [], []

    class WaitingOutput(io.StringIO):
        def readline(self, *args):
            entered.set()
            if not release.wait(2.0):
                raise TimeoutError("test handshake release deadline exceeded")
            return ""  # EOF handshake failure; no actual process exists.

    class FakeProcess:
        stdin = io.StringIO()
        stdout = WaitingOutput()
        stderr = io.StringIO()

        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, *args, **kwargs):
            calls.append("wait")
            return 0

        def kill(self):
            calls.append("kill")

    process = FakeProcess()
    lock = threading.Lock()
    monkeypatch.setattr(mcp_server_manager, "_lock", lock)
    monkeypatch.setattr(mcp_server_manager, "_process", None)
    monkeypatch.setattr(mcp_server_manager, "ado_work_items_mcp_python", lambda: "fake-python")
    monkeypatch.setattr(mcp_server_manager, "ado_work_items_mcp_server_script", lambda: "fake-server")
    monkeypatch.setattr(mcp_server_manager, "tool_workspace_root", lambda: "/fixture-not-used")

    def fake_popen(*args, **kwargs):
        calls.append("Popen")
        return process

    monkeypatch.setattr(mcp_server_manager.subprocess, "Popen", fake_popen)

    def start():
        try:
            results.append(mcp_server_manager.start_ado_work_items_mcp())
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=start, name="characterization-fake-handshake")
    try:
        worker.start()
        assert entered.wait(1.0), "fake handshake was never entered"
        acquired = lock.acquire(timeout=0.05)
        if acquired:
            lock.release()
        assert not acquired, "current_behavior D08: status lock held during blocking readline"
        release.set()
        worker.join(timeout=2.0)
        assert not worker.is_alive() and errors == []
        assert results == [(False, "server 无响应")]
        assert calls == ["Popen", "terminate"], "current_behavior D08: no wait/reap on failed handshake"
        assert mcp_server_manager._process is None
        assert not any(pipe.closed for pipe in (process.stdin, process.stdout, process.stderr)), "current_behavior D08: failed child pipes unclosed"
    finally:
        release.set()
        if worker.ident is not None:
            worker.join(timeout=3.0)
        for pipe in (process.stdin, process.stdout, process.stderr):
            pipe.close()
        assert not worker.is_alive(), "test-owned handshake thread did not exit"
