# ruff: noqa: F811
"""S5-B: protocol adapters, framing and static boundaries (no processes)."""

import json
import re
from pathlib import Path

import pytest

from toolbox_backend.adapters.ai_cli import agy, claude, codex
from toolbox_backend.adapters.ai_cli.base import LineSplitter, Noise, Ring
from toolbox_backend.services.ai_chat import bash_word
from toolbox_backend.services.ai_prompt import build_prompt

SRC = Path(__file__).resolve().parents[1] / "src/toolbox_backend"


def test_line_splitter_chunks_and_overlong():
    s = LineSplitter(10)
    assert s.feed(b'ab') == [] and s.feed(b"c\nde") == [b"abc"] and s.feed(b"f\n") == [b"def"]
    out = s.feed(b"x" * 25)
    assert out == [] and s.feed(b"yy\nok\n") == [27, b"ok"]
    assert s.feed(b"tail") == [] and s.flush() == [b"tail"]
    big = LineSplitter(10)
    assert big.feed(b"z" * 30) == [] and big.flush() == [30]
    assert LineSplitter(10).feed(b"\n\n") == [b"", b""]


def test_noise_limits_and_merges():
    now = [0.0]
    noise = Noise(3, clock=lambda: now[0])
    assert [noise.allow()[0] for _ in range(5)] == [True, True, True, False, False]
    now[0] = 1.5
    assert noise.allow() == (True, 2)
    assert noise.drain() == 0


def test_ring_keeps_only_the_tail():
    ring = Ring(10)
    for chunk in (b"aaaa", b"bbbb", b"cccc"):
        ring.add(chunk)
    assert ring.text() == "bbbbcccc"


def test_claude_argv_and_ids():
    argv = claude.build_argv("/x/claude", permission="manual", session_id="abc-1", model="m", effort="low")
    assert argv[:3] == ["/x/claude", "--print", "--verbose"]
    assert argv[argv.index("--permission-mode") + 1] == "manual"
    assert argv[argv.index("--permission-prompt-tool") + 1] == "stdio"
    assert "--session-id" in argv and "--resume" not in argv
    assert "--resume" in claude.build_argv("/x", permission="plan", resume="abc")
    for bad in ("-x", "--evil", "a b"):
        with pytest.raises(ValueError):
            claude.build_argv("/x", permission="plan", resume=bad)


def test_claude_parse_ignores_unknown_and_shapes_known():
    for ignored in (
        {"type": "system", "subtype": "thinking_tokens"},
        {"type": "system", "subtype": "permission_denied"},
        {"type": "rate_limit_event"},
        {"type": "control_response"},
        {"type": "mystery", "x": 1},
        "text",
        [],
    ):
        assert claude.parse(ignored) == []
    result = claude.parse(
        {"type": "result", "is_error": False, "total_cost_usd": 0.5, "usage": {"input_tokens": 3}, "extra": {}}
    )[0]
    assert result.kind == "result" and result.payload["cost_usd"] == 0.5
    request = claude.parse(
        {"type": "control_request", "request_id": "r", "request": {"subtype": "can_use_tool", "tool_name": "Bash", "input": {"command": "ls"}}}
    )[0]
    assert request.kind == "can_use_tool" and request.payload["input"] == {"command": "ls"}
    assert claude.parse({"type": "control_request", "request": {"subtype": "other"}}) == []
    deny = json.loads(claude.encode_decision("r1", allow=False, message="no"))
    assert deny["response"]["response"] == {"behavior": "deny", "message": "no"}
    allow = json.loads(claude.encode_decision("r1", allow=True, updated_input={"a": 1}))
    assert allow["response"]["response"] == {"behavior": "allow", "updatedInput": {"a": 1}}


def test_codex_argv_rules():
    first = codex.build_argv("/c", cwd="/w", sandbox="workspace-write", effort="high", model="m")
    assert first == ["/c", "exec", "--json", "--skip-git-repo-check", "-C", "/w", "-m", "m",
                     "-c", "model_reasoning_effort=high", "-s", "workspace-write", "-"]  # fmt: skip
    danger = codex.build_argv("/c", cwd="/w", sandbox="danger-full-access")
    assert "--dangerously-bypass-approvals-and-sandbox" in danger and "-s" not in danger
    safe = codex.build_argv("/c", cwd="/w", sandbox="read-only", resume="t1")
    assert safe[:4] == ["/c", "exec", "resume", "t1"] and "-s" not in safe and "-C" not in safe
    assert "--dangerously-bypass-approvals-and-sandbox" not in safe
    assert "--dangerously-bypass-approvals-and-sandbox" in codex.build_argv(
        "/c", cwd="/w", sandbox="danger-full-access", resume="t1", first_turn_danger=True
    )
    with pytest.raises(ValueError):
        codex.build_argv("/c", cwd="/w", sandbox="read-only", resume="--x")
    assert codex.parse({"type": "thread.started", "thread_id": "-bad"})[0].payload["external_id"] is None
    assert codex.parse({"type": "future.event"}) == []


def test_agy_argv_modes_and_parser():
    base = dict(timeout_s=30)
    assert agy.build_argv("/a", mode="sandbox", **base)[-1] == "--sandbox"
    plan = agy.build_argv("/a", mode="plan", **base)
    assert plan[-3:] == ["--sandbox", "--mode", "plan"]
    assert agy.build_argv("/a", mode="auto", **base)[-1] == "--dangerously-skip-permissions"
    argv = agy.build_argv("/a", mode="sandbox", prompt="hi there", conversation="c1", **base)
    assert "--print=hi there" in argv and "--input-format" not in argv and "--print-timeout=30s" in argv
    assert agy.build_argv("/a", mode="sandbox")[-2:] != []  # default timeout always present
    assert any(a.startswith("--print-timeout=") for a in agy.build_argv("/a", mode="sandbox"))
    with pytest.raises(ValueError):
        agy.build_argv("/a", mode="sandbox", conversation="-x")
    with pytest.raises(ValueError):
        agy.build_argv("/a", mode="yolo")
    parser = agy.Parser()
    kinds = []
    for obj in (
        {"event": "init", "conversation_id": "c9", "init": {}},
        {"event": "step_update", "conversation_id": "c9", "step_update": {"state": "ACTIVE", "step_index": 1, "step_type": "tool", "tool_name": "run_command"}},
        {"event": "step_update", "conversation_id": "c9", "step_update": {"state": "ACTIVE", "step_index": 1, "step_type": "tool", "tool_name": "run_command"}},
        {"event": "step_update", "step_index": 2, "step_type": "agent_response", "state": "ACTIVE", "text_delta": "a"},
        {"event": "step_update", "step_index": 2, "step_type": "agent_response", "state": "DONE", "text_delta": "b"},
        {"event": "result", "result": {"status": "SUCCESS"}},
    ):
        kinds += [n.kind for n in parser.parse(obj)]
    assert kinds == ["init", "tool_use", "assistant"] and parser.agent_done
    assert parser.result["status"] == "SUCCESS"


def test_bash_word_refuses_compound_commands():
    assert bash_word("ls -la") == "ls" and bash_word("  git status") == "git"
    for bad in ("ls; id", "a && b", "a | b", "a `b`", "a $(b)", "a\nb", "a > f", "a ${X}", "FOO=1 ls", "", None, 5):
        assert bash_word(bad) is None


def test_prompt_contains_only_integer_and_names():
    text = build_prompt(
        cli="codex", work_item_id="12", library_name="Lib\nINJECT `x`", project_name="P", prefix="mcp__x__"
    )
    assert "#12" in text and "`x`" not in text and "\nINJECT" not in text
    with pytest.raises(ValueError):
        build_prompt(cli="codex", work_item_id="12; rm", library_name="a", project_name="b", prefix="p")


def test_no_fork_shell_or_pkill_in_backend_source():
    for path in SRC.rglob("*.py"):
        code = path.read_text()
        if path.name != "proc_supervisor.py":
            assert "os.fork(" not in code, path
        assert "shell=True" not in code and not re.search(r"pkill|killall", code), path
