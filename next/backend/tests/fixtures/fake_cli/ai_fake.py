#!/usr/bin/env python3
"""Offline stand-in for the claude / codex / agy headless protocols. Never contacts anything.

Behaviour is chosen by keywords inside the prompt: CRASH, BADJSON, LONGLINE, FLOODERR, SLOW,
TOOL, SECRET, FAIL, TIMEOUT (agy), APPROVE:<Tool>:<json-input> (claude), GRANDCHILD.
FAKE_AI_LOG (env) is a file that receives one JSON line per invocation / decision.
"""

import json
import os
import select
import subprocess
import sys
import time
import uuid


def log(**item):
    path = os.environ.get("FAKE_AI_LOG")
    if path:
        with open(path, "a") as stream:
            stream.write(json.dumps(item) + "\n")


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def common(prompt):
    """Prompt keywords shared by every protocol; returns True if the process should go on."""
    if "CRASH" in prompt:
        sys.stderr.write("fatal: simulated crash\n")
        sys.exit(3)
    if "FLOODERR" in prompt:
        for index in range(3000):
            sys.stderr.write(f"noise line {index}\n")
        sys.stderr.flush()
    if "SECRET" in prompt:
        secret = os.environ.get("FAKE_API_KEY", "")
        sys.stderr.write("leak " + secret + "\n")
        sys.stderr.flush()
    if "BADJSON" in prompt:
        sys.stdout.write("this is {not json\n")
        sys.stdout.flush()
    if "LONGLINE" in prompt:
        sys.stdout.write("x" * (5 * 1024 * 1024) + "\n")
        sys.stdout.flush()
    if "GRANDCHILD" in prompt and os.environ.get("FAKE_AI_PIDS"):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        log(grandchild=child.pid)


def text_of(message):
    content = message.get("message", {}).get("content", "")
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content)


def claude(argv):
    session = argv[argv.index("--session-id") + 1] if "--session-id" in argv else None
    resumed = argv[argv.index("--resume") + 1] if "--resume" in argv else None
    log(cli="claude", pid=os.getpid(), argv=argv, cwd=os.getcwd(), env=sorted(os.environ))
    sid = resumed or session or str(uuid.uuid4())
    started = False
    interrupted = False

    def read_line(timeout=None):
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return ""
        return sys.stdin.readline()

    while True:
        line = sys.stdin.readline()
        if not line:
            return
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if message.get("type") == "control_request":
            continue
        if message.get("type") != "user":
            continue
        prompt = text_of(message)
        log(prompt_received=prompt[:80], pid=os.getpid())
        common(prompt)
        if not started:
            started = True
            emit({"type": "system", "subtype": "init", "session_id": sid, "model": "fake"})
        emit({"type": "system", "subtype": "thinking_tokens", "n": 1})
        emit({"type": "rate_limit_event", "x": 1})
        emit({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "hmm"}]}})
        decision = None
        if "APPROVE:" in prompt:
            tool, raw = prompt.split("APPROVE:", 1)[1].rsplit(" go", 1)[0].split(":", 1)
            tool_input = json.loads(raw)
            if tool == "Write":  # large payload that must never reach the prompt or the DB
                tool_input["content"] = "MARKERXYZ-CONTENT"
            request_id = "req-" + uuid.uuid4().hex[:8]
            emit(
                {
                    "type": "control_request",
                    "request_id": request_id,
                    "request": {
                        "subtype": "can_use_tool",
                        "tool_name": tool,
                        "input": tool_input,
                        "tool_use_id": "tu-1",
                    },
                }
            )
            while True:
                reply = sys.stdin.readline()
                if not reply:
                    return
                body = json.loads(reply)
                if body.get("type") == "control_response":
                    decision = body["response"]["response"]
                    log(decision=decision, request_id=body["response"]["request_id"])
                    break
        if "MANYLINES" in prompt:
            for index in range(1500):
                emit({"type": "assistant", "message": {"content": [{"type": "text", "text": f"line {index}"}]}})
        if "TOOLS3" in prompt:
            for index in range(3):
                emit(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {"type": "tool_use", "id": f"tu-m{index}", "name": "Bash", "input": {"command": f"echo {index}"}}
                            ]
                        },
                    }
                )
        if "TOOLFAIL" in prompt:
            emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "tu-f", "name": "Bash", "input": {"command": "false"}}]}})
            emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tu-f", "is_error": True, "content": "command failed badly"}]}})
        if "TOOL" in prompt:
            emit(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "id": "tu-2", "name": "Bash", "input": {"command": "ls"}}
                        ]
                    },
                }
            )
            emit(
                {
                    "type": "user",
                    "message": {
                        "content": [{"type": "tool_result", "tool_use_id": "tu-2", "content": "ok"}]
                    },
                }
            )
        reply = "echo:" + prompt[:60]
        if "SECRET" in prompt:
            reply += " " + os.environ.get("FAKE_API_KEY", "")
        if decision is not None:
            reply = "decision:" + decision.get("behavior", "?")
        emit({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}})
        if "SLOW" in prompt:
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                got = read_line(0.05)
                if got and json.loads(got).get("request", {}).get("subtype") == "interrupt":
                    interrupted = True
                    break
        if interrupted:
            interrupted = False
            emit({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "interrupted"})
            continue
        emit(
            {
                "type": "result",
                "subtype": "error" if "FAIL" in prompt else "success",
                "is_error": "FAIL" in prompt,
                "result": "failed" if "FAIL" in prompt else reply,
                "total_cost_usd": 0.01,
                "num_turns": 1,
                "duration_ms": 5,
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "permission_denials": [],
            }
        )


def codex(argv):
    prompt = sys.stdin.read()
    resume = argv[argv.index("resume") + 1] if "resume" in argv else None
    log(
        cli="codex",
        pid=os.getpid(),
        argv=argv,
        cwd=os.getcwd(),
        prompt_in_argv=any(prompt[:20] in a for a in argv if prompt.strip()),
        stdin_prompt=prompt[:80],
        env=sorted(os.environ),
    )
    common(prompt)
    emit({"type": "thread.started", "thread_id": resume or "thr-" + uuid.uuid4().hex[:12]})
    emit({"type": "turn.started"})
    if "TOOL" in prompt:
        emit({"type": "item.started", "item": {"id": "i1", "type": "command_execution", "command": "ls"}})
        emit(
            {
                "type": "item.completed",
                "item": {"id": "i1", "type": "command_execution", "exit_code": 0, "aggregated_output": "a"},
            }
        )
    if "SLOW" in prompt:
        time.sleep(600)
    emit({"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": "echo:" + prompt[:60]}})
    if "FAIL" in prompt:
        emit({"type": "turn.failed", "error": {"message": "model refused"}})
        sys.exit(1)
    emit({"type": "turn.completed", "usage": {"input_tokens": 7, "output_tokens": 3}})


def agy(argv):
    if "--input-format" in argv:
        if os.environ.get("FAKE_AGY_NO_STDIN"):
            sys.stderr.write("unknown flag --input-format\n")
            sys.exit(2)
        prompt = text_of(json.loads(sys.stdin.readline()))
    else:
        prompt = next((a[len("--print=") :] for a in argv if a.startswith("--print=")), "")
    conversation = argv[argv.index("--conversation") + 1] if "--conversation" in argv else None
    log(cli="agy", pid=os.getpid(), argv=argv, cwd=os.getcwd(), env=sorted(os.environ))
    common(prompt)
    cid = conversation or "conv-" + uuid.uuid4().hex[:12]
    emit({"event": "init", "conversation_id": cid, "init": {"cwd": os.getcwd(), "permission_mode": "always-proceed"}})
    if "TOOL" in prompt:
        step = {"conversation_id": cid, "state": "ACTIVE", "step_index": 1, "step_type": "tool", "tool_name": "run_command", "tool_info": "ls"}
        emit({"event": "step_update", "conversation_id": cid, "step_update": step})
        step = dict(step, state="DONE")
        emit({"event": "step_update", "conversation_id": cid, "step_update": step})
    if "SLOW" in prompt:
        time.sleep(600)
    if "TIMEOUT" in prompt:
        sys.stderr.write("[agy] print timeout after 1s; returning partial output\n")
        emit({"event": "result", "conversation_id": cid, "result": {"status": "SUCCESS", "response": "partial", "num_turns": 1}})
        return
    for state, delta in (("ACTIVE", "echo:"), ("DONE", prompt[:60])):
        step = {"state": state, "step_index": 2, "step_type": "agent_response", "text_delta": delta}
        emit({"event": "step_update", "conversation_id": cid, "step_update": step})
    emit(
        {
            "event": "result",
            "conversation_id": cid,
            "result": {"status": "SUCCESS", "response": "echo", "num_turns": 1, "usage": {"input_tokens": 4, "output_tokens": 2}},
        }
    )


if __name__ == "__main__":
    mode, rest = sys.argv[1], sys.argv[2:]
    if "--version" in rest:
        print(f"fake-{mode} 1.0")
        sys.exit(0)
    if mode == "agy" and rest[:1] == ["models"]:
        print("fake-agy-fast\nfake-agy-pro")
        sys.exit(0)
    {"claude": claude, "codex": codex, "agy": agy}[mode](rest)
