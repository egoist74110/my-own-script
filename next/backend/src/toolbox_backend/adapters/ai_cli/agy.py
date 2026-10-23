"""agy --output-format stream-json protocol (checked against agy 1.4.6, 2026-10-23).

Checked: init/step_update/result event kinds, conversation_id in the first event, --print=,
--conversation, --sandbox, --mode plan, --effort, the print-timeout trap.
NOT checked against the real CLI: `--input-format stream-json` line format on stdin (the fake
accepts a Claude-style user message) and whether the init/step_update/result payload is nested
under its event name or flat; both are parsed. If stdin input fails, the service falls back to
--print=<prompt> and marks the session warning.
"""

import json

from toolbox_backend.adapters.ai_cli.base import Norm, clip, safe_id

TIMEOUT_MARKER = "[agy] print timeout"
DEFAULT_TIMEOUT_S = 600


def mode_flags(mode):
    if mode == "sandbox":
        return ["--sandbox"]
    if mode == "plan":
        return ["--sandbox", "--mode", "plan"]
    if mode == "auto":
        return ["--dangerously-skip-permissions"]
    raise ValueError("invalid mode")


def build_argv(
    exe,
    *,
    mode,
    prompt=None,
    model=None,
    effort=None,
    conversation=None,
    timeout_s=DEFAULT_TIMEOUT_S,
):
    """prompt=None means stdin stream-json input; a prompt string means the argv fallback."""
    argv = [exe]
    if prompt is None:
        argv += ["--print", "--input-format", "stream-json"]
    else:
        argv.append("--print=" + prompt)
    argv += ["--output-format", "stream-json", f"--print-timeout={int(timeout_s)}s"]
    argv += mode_flags(mode)
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["--effort", effort]
    if conversation:
        if not safe_id(conversation):
            raise ValueError("invalid conversation id")
        argv += ["--conversation", conversation]
    return argv


def encode_prompt(text: str) -> bytes:
    message = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    return (json.dumps(message, ensure_ascii=False) + "\n").encode()


class Parser:
    """Stateful: assistant text deltas are joined per step; tool steps are reported once."""

    def __init__(self):
        self.conversation_id = None
        self.deltas = {}
        self.tools_seen = set()
        self.agent_done = False
        self.result = None

    def parse(self, obj) -> list[Norm]:
        if not isinstance(obj, dict):
            return []
        out = []
        conv = safe_id(obj.get("conversation_id"))
        if conv and self.conversation_id is None:
            self.conversation_id = conv
            out.append(Norm("init", {"external_id": conv}))
        event = obj.get("event")
        body = (
            obj.get(event) if isinstance(event, str) and isinstance(obj.get(event), dict) else obj
        )
        if event == "step_update":
            out.extend(self._step(body))
        elif event == "result":
            usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
            self.result = {
                "status": clip(body.get("status"), 40),
                "response": clip(body.get("response"), 16000),
                "input_tokens": _int(usage.get("input_tokens")),
                "output_tokens": _int(usage.get("output_tokens")),
            }
        return out

    def _step(self, step):
        kind, state, index = step.get("step_type"), step.get("state"), step.get("step_index", 0)
        if kind == "tool":
            tool = clip(step.get("tool_name") or "tool", 80)
            key = ("tool", index)
            out = []
            if key not in self.tools_seen:
                self.tools_seen.add(key)
                info = step.get("tool_info")
                summary = clip(
                    info
                    if isinstance(info, str)
                    else json.dumps(info, ensure_ascii=False)
                    if info
                    else "",
                    200,
                )
                out.append(
                    Norm(
                        "tool_use",
                        {"tool": tool, "tool_use_id": f"step-{index}", "summary": summary},
                    )
                )
            if state in ("DONE", "ERROR"):
                out.append(
                    Norm(
                        "tool_result",
                        {"tool_use_id": f"step-{index}", "is_error": state == "ERROR", "text": ""},
                    )
                )
            return out
        if kind == "agent_response":
            if isinstance(step.get("text_delta"), str):
                self.deltas.setdefault(index, []).append(step["text_delta"])
            if state == "DONE":
                self.agent_done = True
                text = "".join(self.deltas.pop(index, []))
                if text.strip():
                    return [Norm("assistant", {"text": clip(text, 16000)})]
            return []
        return []


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
