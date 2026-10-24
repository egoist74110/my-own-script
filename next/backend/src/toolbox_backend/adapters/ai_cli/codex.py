"""Codex exec --json protocol.

Checked with codex-cli 0.163.0 (2026-10-24): stdin prompts, thread.started IDs,
command/agent items, turn usage and JSON-encoded API errors; resume preserves thread ID
and uses the process cwd without -s/-C. File/MCP/reasoning items remain tolerant mappings.
"""

import json

from toolbox_backend.adapters.ai_cli.base import Norm, clip, safe_id, tool_summary

BYPASS = "--dangerously-bypass-approvals-and-sandbox"


def build_argv(exe, *, cwd, sandbox, effort=None, model=None, resume=None, first_turn_danger=False):
    """First turn defines the sandbox. Resume never passes -s/-C; only a danger first turn
    may pass the bypass flag again."""
    argv = [exe, "exec"]
    if resume:
        if not safe_id(resume):
            raise ValueError("invalid thread id")
        argv += ["resume", resume]
    argv += ["--json", "--skip-git-repo-check"]
    if not resume:
        argv += ["-C", cwd]
    if model:
        argv += ["-m", model]
    if effort:
        argv += ["-c", f"model_reasoning_effort={effort}"]
    if resume:
        if first_turn_danger:
            argv.append(BYPASS)
    elif sandbox == "danger-full-access":
        argv.append(BYPASS)
    else:
        argv += ["-s", sandbox]
    argv.append("-")  # prompt via stdin
    return argv


def encode_prompt(text: str) -> bytes:
    return text.encode()


def parse(obj) -> list[Norm]:
    if not isinstance(obj, dict):
        return []
    kind = obj.get("type")
    if kind == "thread.started":
        return [Norm("init", {"external_id": safe_id(obj.get("thread_id"))})]
    if kind in ("item.started", "item.updated", "item.completed"):
        item = obj.get("item")
        return _item(kind, item) if isinstance(item, dict) else []
    if kind == "turn.completed":
        usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
        return [
            Norm(
                "result",
                {
                    "is_error": False,
                    "input_tokens": _int(usage.get("input_tokens")),
                    "output_tokens": _int(usage.get("output_tokens")),
                    "cached_input_tokens": _int(usage.get("cached_input_tokens")),
                    "reasoning_output_tokens": _int(usage.get("reasoning_output_tokens")),
                },
            )
        ]
    if kind == "turn.failed":
        error = obj.get("error") if isinstance(obj.get("error"), dict) else {}
        return [Norm("result", {"is_error": True, "message": _error_message(error.get("message"))})]
    if kind == "error":
        return [
            Norm("error", {"category": "cli_error", "text": _error_message(obj.get("message"))})
        ]
    return []


def _item(event, item):
    itype, ident = item.get("type"), clip(item.get("id"), 80)
    done = event == "item.completed"
    if itype == "agent_message":
        text = item.get("text")
        return (
            [Norm("assistant", {"text": clip(text, 16000)})]
            if done and str(text or "").strip()
            else []
        )
    if itype == "reasoning":
        text = item.get("text") or item.get("summary")
        return (
            [Norm("thinking", {"text": clip(text, 8000)})]
            if done and str(text or "").strip()
            else []
        )
    if itype == "command_execution":
        if event == "item.started":
            return [
                Norm(
                    "tool_use",
                    {
                        "tool": "shell",
                        "tool_use_id": ident,
                        "summary": tool_summary("shell", {"command": item.get("command")}),
                    },
                )
            ]
        if done:
            code = item.get("exit_code")
            return [
                Norm(
                    "tool_result",
                    {
                        "tool_use_id": ident,
                        "is_error": isinstance(code, int) and code != 0,
                        "text": clip(item.get("aggregated_output"), 2000),
                    },
                )
            ]
        return []
    if itype in ("file_change", "patch"):
        changes = item.get("changes") or item.get("files") or []
        names = (
            ", ".join(
                clip(c.get("path") or c.get("file"), 80) for c in changes if isinstance(c, dict)
            )
            if isinstance(changes, list)
            else ""
        )
        if event == "item.started":
            return [
                Norm(
                    "tool_use",
                    {"tool": "apply_patch", "tool_use_id": ident, "summary": clip(names, 300)},
                )
            ]
        if done:
            return [
                Norm(
                    "tool_result",
                    {"tool_use_id": ident, "is_error": False, "text": clip(names, 300)},
                )
            ]
        return []
    if itype == "mcp_tool_call":
        if event == "item.started":
            tool = "mcp:" + clip(item.get("tool") or item.get("name") or "mcp", 70)
            return [Norm("tool_use", {"tool": tool, "tool_use_id": ident, "summary": ""})]
        if done:
            return [
                Norm(
                    "tool_result",
                    {
                        "tool_use_id": ident,
                        "is_error": bool(item.get("is_error")),
                        "text": clip(item.get("result"), 2000),
                    },
                )
            ]
        return []
    if itype == "web_search" and event == "item.started":
        return [
            Norm(
                "tool_use",
                {
                    "tool": "web_search",
                    "tool_use_id": ident,
                    "summary": tool_summary("WebSearch", {"query": item.get("query")}),
                },
            )
        ]
    if itype == "error" and event in ("item.started", "item.completed"):
        return [Norm("error", {"category": "cli_error", "text": clip(item.get("message"), 500)})]
    return []


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _error_message(value) -> str:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError, RecursionError:
            decoded = None
        if isinstance(decoded, dict):
            error = decoded.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            if not isinstance(message, str):
                message = decoded.get("message")
            if isinstance(message, str):
                value = message
    return clip(value, 500)
