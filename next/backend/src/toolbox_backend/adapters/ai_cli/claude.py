"""Claude Code stream-json protocol (checked against claude 2.1.308, 2026-10-23).

Unchecked against the real CLI: the `behavior: "allow"` control_response shape (only deny was
exercised); the fake follows the SDK shape {behavior, updatedInput}.
"""

import json

from toolbox_backend.adapters.ai_cli.base import Norm, clip, safe_id, tool_summary


def build_argv(exe, *, permission, session_id=None, resume=None, model=None, effort=None):
    argv = [
        exe,
        "--print",
        "--verbose",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--permission-mode",
        permission,
        "--permission-prompt-tool",
        "stdio",
    ]
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["--effort", effort]
    if resume:
        if not safe_id(resume):
            raise ValueError("invalid resume id")
        argv += ["--resume", resume]
    elif session_id:
        if not safe_id(session_id):
            raise ValueError("invalid session id")
        argv += ["--session-id", session_id]
    return argv


def encode_user(text: str) -> bytes:
    message = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    return (json.dumps(message, ensure_ascii=False) + "\n").encode()


def encode_interrupt(request_id: str) -> bytes:
    message = {
        "type": "control_request",
        "request_id": request_id,
        "request": {"subtype": "interrupt"},
    }
    return (json.dumps(message) + "\n").encode()


def encode_decision(request_id: str, *, allow: bool, updated_input=None, message="") -> bytes:
    if allow:
        body = {
            "behavior": "allow",
            "updatedInput": updated_input if updated_input is not None else {},
        }
    else:
        body = {"behavior": "deny", "message": message or "denied"}
    envelope = {
        "type": "control_response",
        "response": {"subtype": "success", "request_id": request_id, "response": body},
    }
    return (json.dumps(envelope, ensure_ascii=False) + "\n").encode()


def _blocks(obj):
    message = obj.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _stringify(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return "" if content is None else str(content)


def parse(obj) -> list[Norm]:
    """Normalize one decoded line. Unknown types/fields are ignored on purpose."""
    if not isinstance(obj, dict):
        return []
    kind = obj.get("type")
    if kind == "system":
        if obj.get("subtype") == "init":
            return [
                Norm(
                    "init",
                    {
                        "external_id": safe_id(obj.get("session_id")),
                        "model": clip(obj.get("model"), 80),
                    },
                )
            ]
        return []
    if kind == "assistant":
        out = []
        for block in _blocks(obj):
            btype = block.get("type")
            if btype == "text" and str(block.get("text") or "").strip():
                out.append(Norm("assistant", {"text": clip(block["text"], 16000)}))
            elif btype == "thinking" and str(block.get("thinking") or "").strip():
                out.append(Norm("thinking", {"text": clip(block["thinking"], 8000)}))
            elif btype == "tool_use":
                tool = clip(block.get("name"), 80)
                out.append(
                    Norm(
                        "tool_use",
                        {
                            "tool": tool,
                            "tool_use_id": clip(block.get("id"), 80),
                            "summary": tool_summary(tool, block.get("input")),
                        },
                    )
                )
        return out
    if kind == "user":
        return [
            Norm(
                "tool_result",
                {
                    "tool_use_id": clip(b.get("tool_use_id"), 80),
                    "is_error": bool(b.get("is_error")),
                    "text": clip(_stringify(b.get("content")), 2000),
                },
            )
            for b in _blocks(obj)
            if b.get("type") == "tool_result"
        ]
    if kind == "control_request":
        request = obj.get("request")
        if isinstance(request, dict) and request.get("subtype") == "can_use_tool":
            data = request.get("input")
            return [
                Norm(
                    "can_use_tool",
                    {
                        "request_id": clip(obj.get("request_id"), 128),
                        "tool": clip(request.get("tool_name"), 80),
                        "input": data if isinstance(data, dict) else {},
                    },
                )
            ]
        return []
    if kind == "result":
        usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
        cost = obj.get("total_cost_usd")
        return [
            Norm(
                "result",
                {
                    "is_error": bool(obj.get("is_error")),
                    "subtype": clip(obj.get("subtype"), 40),
                    "message": clip(obj.get("result"), 500),
                    "cost_usd": float(cost) if isinstance(cost, (int, float)) else 0.0,
                    "input_tokens": _int(usage.get("input_tokens")),
                    "output_tokens": _int(usage.get("output_tokens")),
                    "duration_ms": _int(obj.get("duration_ms")),
                    "num_turns": _int(obj.get("num_turns")),
                },
            )
        ]
    return []  # control_response, rate_limit_event, stream_event, ... are not surfaced


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
