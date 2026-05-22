"""Claude Code PreToolUse 钩子：把危险工具调用的审批甩给 TG。

由 headless 会话经 --settings 注入（matcher=Bash 等）。claude 在执行被匹配的工具
前会以子进程方式运行本脚本，stdin 给一段 JSON（含 session_id / tool_name /
tool_input / cwd）。本脚本：
  1. 把请求原子落盘到 <approvals_dir>/<req_id>.req
  2. 轮询 <approvals_dir>/<req_id>.resp（由主程序在用户点 TG 按钮后写入）
  3. 按结果输出 PreToolUse 的 permissionDecision（allow / deny）

无 resp 或超时 → 默认 deny（安全侧）。本脚本只依赖标准库，不 import app_ado，
approvals_dir 由命令行参数传入，因此不受 cwd / PYTHONPATH 影响。

用法：python3 cc_approval_hook.py <approvals_dir>
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid


def main() -> int:
    appr_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.cc_approvals")
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    req_id = uuid.uuid4().hex[:12]
    req = {
        "req_id": req_id,
        "session_id": data.get("session_id") or "",
        "tool_name": data.get("tool_name") or "",
        "tool_input": data.get("tool_input") or {},
        "cwd": data.get("cwd") or "",
        "ts": time.time(),
    }
    try:
        os.makedirs(appr_dir, exist_ok=True)
    except Exception:
        pass

    reqp = os.path.join(appr_dir, f"{req_id}.req")
    respp = os.path.join(appr_dir, f"{req_id}.resp")
    tmp = reqp + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(req, f, ensure_ascii=False)
        os.replace(tmp, reqp)  # 原子出现，避免主程序读到半截
    except Exception:
        # 落盘失败：放行还是拒绝？保守起见拒绝，让用户感知异常
        _emit("deny", "审批钩子落盘失败")
        return 0

    decision, reason = "deny", "审批超时（默认拒绝）"
    timeout = float(os.environ.get("CC_HOOK_TIMEOUT", "540"))
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(respp):
            try:
                with open(respp, encoding="utf-8") as f:
                    r = json.load(f)
                decision = r.get("decision", "deny")
                reason = r.get("reason", "")
            except Exception:
                pass
            break
        time.sleep(0.4)

    for p in (reqp, respp):
        try:
            os.remove(p)
        except Exception:
            pass

    _emit("allow" if decision == "allow" else "deny",
          reason or ("用户允许" if decision == "allow" else "用户拒绝"))
    return 0


def _emit(decision: str, reason: str) -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
