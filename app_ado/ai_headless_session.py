"""Headless Claude Code 会话（CC Pocket 式结构化对话）。

和旧的 ai_dev_session（PTY 截屏镜像）完全不同：这里用 `claude` 的 headless
stream-json 协议跑——

    claude --print --verbose \
           --input-format stream-json --output-format stream-json \
           --model <m> --effort <e> --permission-mode <p>

往 stdin 按行写 user 消息 JSON、从 stdout 按行读结构化事件，再把事件归一化成
HeadlessEvent 派发给监听者。复用本机 `claude` 已登录的订阅 OAuth（不需要 API key）。

只用普通管道，不需要 PTY，Windows 也能跑。一个进程内可多轮对话（stdin 不关就一直
读），claude 自动把会话写到 ~/.claude/projects/<encoded-cwd>/<session-id>.jsonl，
供之后 --resume 续聊。

Phase 0 已实证：多轮上下文保持、flag 生效、OAuth 可用、user 消息 JSON 形如
  {"type":"user","message":{"role":"user","content":[{"type":"text","text":...}]}}
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


# ----------------------------------------------------------------------------
# 配置 / 选项
# ----------------------------------------------------------------------------

# claude --effort 的合法档位
EFFORT_CHOICES = ("low", "medium", "high", "xhigh", "max")
# claude --permission-mode 的合法档位
PERMISSION_CHOICES = ("default", "acceptEdits", "auto", "dontAsk", "bypassPermissions", "plan")

# 默认审批模式：默认放行（编辑自动应用），危险操作交由上层（PreToolUse hook）推 TG 审批。
DEFAULT_PERMISSION_MODE = "acceptEdits"
DEFAULT_EFFORT = "medium"


def _augment_path(env: dict[str, str]) -> dict[str, str]:
    """GUI app 子进程 PATH 不全是 macOS 老坑，补回常见 bin 目录。"""
    extras = [
        "/usr/local/bin",
        "/opt/homebrew/bin",
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / "bin"),
    ]
    parts = env.get("PATH", "").split(":") if env.get("PATH") else []
    for p in extras:
        if p and p not in parts and Path(p).exists():
            parts.append(p)
    env["PATH"] = ":".join(parts) if parts else env.get("PATH", "")
    return env


def resolve_claude_executable(command: str = "claude") -> Optional[str]:
    """在补全后的 PATH 里解析 claude 可执行文件路径。"""
    try:
        argv = shlex.split(command)
    except Exception:
        return None
    if not argv:
        return None
    env = _augment_path(os.environ.copy())
    return shutil.which(argv[0], path=env["PATH"])


# ----------------------------------------------------------------------------
# 归一化事件
# ----------------------------------------------------------------------------

@dataclass
class HeadlessEvent:
    """从 claude stream-json 归一化出来的一条事件。

    kind:
      "init"         系统初始化（拿到 session_id / model / permissionMode）
      "thinking"     助手思考块（text 放 thinking）
      "assistant"    助手正文文本（text）
      "tool_use"     助手发起工具调用（tool_name / tool_input / tool_use_id）
      "tool_result"  工具返回（tool_use_id / text / is_error）
      "result"       一轮结束（is_error / text=最终结果 / cost_usd / num_turns / subtype）
      "rate_limit"   限流提示（raw 里有原始数据）
      "error"        进程/解析层错误（text）
      "exit"         进程退出（exit_code）
    """
    kind: str
    text: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_use_id: str = ""
    is_error: bool = False
    cost_usd: float = 0.0
    num_turns: int = 0
    subtype: str = ""
    exit_code: Optional[int] = None
    raw: Optional[dict] = None


@dataclass
class HeadlessInfo:
    sid: str                       # 本地内部短 id（不是 claude 的 session_id）
    model_id: str                  # claude 模型别名/全名（如 sonnet / opus / haiku）
    repo_name: str
    cwd: str
    effort: str = DEFAULT_EFFORT
    permission_mode: str = DEFAULT_PERMISSION_MODE
    command: str = "claude"        # claude 可执行（可带前缀，shlex 解析）
    resume_session_id: str = ""    # 非空则 --resume 续聊
    claude_session_id: str = ""    # 进程上报的真实 session_id（init 后填）
    pid: int = 0
    status: str = "starting"       # starting | idle | busy | exited
    exit_code: Optional[int] = None
    started_at: float = field(default_factory=time.time)
    last_cost_usd: float = 0.0
    total_cost_usd: float = 0.0


Listener = Callable[["HeadlessSession", HeadlessEvent], None]


# ----------------------------------------------------------------------------
# 会话
# ----------------------------------------------------------------------------

class HeadlessSession:
    def __init__(
        self,
        *,
        sid: str,
        model_id: str,
        repo_name: str,
        cwd: str,
        effort: str = DEFAULT_EFFORT,
        permission_mode: str = DEFAULT_PERMISSION_MODE,
        command: str = "claude",
        resume_session_id: str = "",
        extra_args: Optional[list[str]] = None,
        settings_path: str = "",
    ) -> None:
        # effort/model 留空表示「不传该 flag」（续聊时让 claude 沿用原会话设置）
        if effort and effort not in EFFORT_CHOICES:
            effort = DEFAULT_EFFORT
        if permission_mode not in PERMISSION_CHOICES:
            permission_mode = DEFAULT_PERMISSION_MODE
        self.info = HeadlessInfo(
            sid=sid,
            model_id=model_id,
            repo_name=repo_name,
            cwd=cwd,
            effort=effort,
            permission_mode=permission_mode,
            command=command,
            resume_session_id=resume_session_id or "",
        )
        self._extra_args = list(extra_args or [])
        self._settings_path = settings_path or ""
        self._proc: Optional[subprocess.Popen] = None
        self._listeners: list[Listener] = []
        self._lock = threading.Lock()
        self._stdin_lock = threading.Lock()
        self._closed = False
        # busy：已发出一轮、还没收到对应 result
        self._inflight = 0
        self._pending: list[str] = []   # 处理中再发的提示词排队
        self._ctrl_seq = 0              # control_request 自增 id

    # ---------- listeners ----------

    def add_listener(self, cb: Listener) -> None:
        if cb not in self._listeners:
            self._listeners.append(cb)

    def remove_listener(self, cb: Listener) -> None:
        try:
            self._listeners.remove(cb)
        except ValueError:
            pass

    def _emit(self, ev: HeadlessEvent) -> None:
        for cb in list(self._listeners):
            try:
                cb(self, ev)
            except Exception:
                pass

    # ---------- argv ----------

    def _build_argv(self) -> list[str]:
        exe = resolve_claude_executable(self.info.command) or "claude"
        argv = [
            exe,
            "--print",
            "--verbose",  # stream-json + print 必须 --verbose 才吐 per-message 事件
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--permission-mode", self.info.permission_mode,
        ]
        # model / effort 留空时不传（续聊场景沿用原会话设置）
        if self.info.model_id:
            argv += ["--model", self.info.model_id]
        if self.info.effort:
            argv += ["--effort", self.info.effort]
        if self.info.resume_session_id:
            argv += ["--resume", self.info.resume_session_id]
        if self._settings_path:
            argv += ["--settings", self._settings_path]
        argv += self._extra_args
        return argv

    # ---------- lifecycle ----------

    def start(self) -> None:
        argv = self._build_argv()
        env = _augment_path(os.environ.copy())
        env.setdefault("TERM", "xterm-256color")
        env.pop("CI", None)
        cwd = self.info.cwd or os.getcwd()
        try:
            self._proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            self.info.status = "exited"
            self.info.exit_code = 127
            self._emit(HeadlessEvent(kind="error", text=f"启动 claude 失败：{e}"))
            self._emit(HeadlessEvent(kind="exit", exit_code=127))
            return
        self.info.pid = self._proc.pid
        self.info.status = "idle"
        threading.Thread(target=self._stdout_loop, daemon=True,
                         name=f"hs-out-{self.info.sid}").start()
        threading.Thread(target=self._stderr_loop, daemon=True,
                         name=f"hs-err-{self.info.sid}").start()
        threading.Thread(target=self._waiter_loop, daemon=True,
                         name=f"hs-wait-{self.info.sid}").start()

    def _stdout_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                # 非 JSON 行：当作纯文本错误/提示
                self._emit(HeadlessEvent(kind="error", text=line[:2000]))
                continue
            try:
                self._dispatch_event(obj)
            except Exception as e:
                self._emit(HeadlessEvent(kind="error", text=f"解析事件异常：{e}"))

    def _stderr_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            s = line.rstrip("\n")
            if s.strip():
                self._emit(HeadlessEvent(kind="error", text=s[:2000]))

    def _waiter_loop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        code = proc.wait()
        self._closed = True
        self.info.status = "exited"
        self.info.exit_code = code
        self._emit(HeadlessEvent(kind="exit", exit_code=code))

    # ---------- 事件归一化 ----------

    def _dispatch_event(self, obj: dict) -> None:
        t = obj.get("type")
        if t == "system":
            if obj.get("subtype") == "init":
                sid = obj.get("session_id") or ""
                if sid:
                    self.info.claude_session_id = sid
                self._emit(HeadlessEvent(kind="init", text=sid, raw=obj))
            return

        if t == "assistant":
            for block in (obj.get("message", {}) or {}).get("content", []) or []:
                bt = block.get("type")
                if bt == "text":
                    txt = block.get("text") or ""
                    if txt.strip():
                        self._emit(HeadlessEvent(kind="assistant", text=txt, raw=block))
                elif bt == "thinking":
                    txt = block.get("thinking") or ""
                    if txt.strip():
                        self._emit(HeadlessEvent(kind="thinking", text=txt, raw=block))
                elif bt == "tool_use":
                    self._emit(HeadlessEvent(
                        kind="tool_use",
                        tool_name=block.get("name") or "",
                        tool_input=block.get("input") or {},
                        tool_use_id=block.get("id") or "",
                        raw=block,
                    ))
            return

        if t == "user":
            # 工具结果以 user 消息回流
            for block in (obj.get("message", {}) or {}).get("content", []) or []:
                if block.get("type") == "tool_result":
                    content = block.get("content")
                    self._emit(HeadlessEvent(
                        kind="tool_result",
                        tool_use_id=block.get("tool_use_id") or "",
                        text=_stringify_tool_result(content),
                        is_error=bool(block.get("is_error")),
                        raw=block,
                    ))
            return

        if t == "control_response":
            return  # interrupt 等控制应答，无需对外暴露

        if t == "result":
            with self._lock:
                if self._inflight > 0:
                    self._inflight -= 1
                # 本轮收尾后，若有排队的下一条就接着发；否则置空闲
                if self._inflight <= 0 and not self._closed:
                    if self._pending:
                        self._send_now(self._pending.pop(0))
                    else:
                        self.info.status = "idle"
            cost = float(obj.get("total_cost_usd") or 0.0)
            self.info.last_cost_usd = cost
            self.info.total_cost_usd += cost
            self._emit(HeadlessEvent(
                kind="result",
                text=obj.get("result") or "",
                is_error=bool(obj.get("is_error")),
                cost_usd=cost,
                num_turns=int(obj.get("num_turns") or 0),
                subtype=obj.get("subtype") or "",
                raw=obj,
            ))
            return

        if t == "rate_limit_event":
            self._emit(HeadlessEvent(kind="rate_limit", raw=obj))
            return

        # 其它（stream_event 等）忽略
        return

    # ---------- 输入 ----------

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._inflight > 0

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def _send_now(self, text: str) -> bool:
        """直接把一轮用户消息写进 stdin（调用方须持 self._lock）。"""
        proc = self._proc
        if proc is None or proc.stdin is None or self._closed:
            return False
        msg = {
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        }
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        try:
            with self._stdin_lock:
                proc.stdin.write(line)
                proc.stdin.flush()
        except Exception:
            return False
        self._inflight += 1
        if not self._closed:
            self.info.status = "busy"
        return True

    def submit(self, text: str) -> tuple[str, int]:
        """提交一轮提示词。处理中则排队。

        返回 (status, queue_pos)：
          ("sent", 0)     立即发出
          ("queued", n)   已排队，前面还有 n-1 条（n 是它的排队位次）
          ("closed"/"error", 0)
        """
        with self._lock:
            if self._closed or self._proc is None:
                return ("closed", 0)
            if self._inflight > 0:
                self._pending.append(text)
                return ("queued", len(self._pending))
            ok = self._send_now(text)
        return ("sent", 0) if ok else ("error", 0)

    def send_user(self, text: str) -> bool:
        """兼容旧调用：等价 submit（成功/排队都算 True）。"""
        status, _ = self.submit(text)
        return status in ("sent", "queued")

    def interrupt(self) -> bool:
        """中断当前轮但保留会话：走 stream-json control 协议（不关 stdin）。"""
        proc = self._proc
        if proc is None or proc.stdin is None or self._closed:
            return False
        self._ctrl_seq += 1
        msg = {
            "type": "control_request",
            "request_id": f"int-{self._ctrl_seq}",
            "request": {"subtype": "interrupt"},
        }
        # 中断后清空排队，避免被打断了还接着跑后续
        with self._lock:
            self._pending.clear()
        try:
            with self._stdin_lock:
                proc.stdin.write(json.dumps(msg) + "\n")
                proc.stdin.flush()
            return True
        except Exception:
            return False

    # ---------- 关闭 ----------

    def close(self, *, grace_seconds: float = 3.0) -> None:
        self._closed = True
        proc = self._proc
        if proc is None:
            self.info.status = "exited"
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=grace_seconds)
        except Exception:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.info.status = "exited"


def _stringify_tool_result(content) -> str:
    """工具结果 content 可能是 str 或 [{"type":"text","text":...}, ...]。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text") or "")
                else:
                    parts.append(json.dumps(b, ensure_ascii=False))
            else:
                parts.append(str(b))
        return "\n".join(p for p in parts if p)
    return str(content)


# ----------------------------------------------------------------------------
# 多会话注册表
# ----------------------------------------------------------------------------

class HeadlessSessionManager:
    """全局多 headless 会话注册表。线程安全。"""

    def __init__(self) -> None:
        self._sessions: dict[str, HeadlessSession] = {}
        self._creation_order: list[str] = []
        self._lock = threading.Lock()

    def list(self) -> list[HeadlessInfo]:
        with self._lock:
            return [s.info for s in self._sessions.values()]

    def get(self, sid: str) -> Optional[HeadlessSession]:
        with self._lock:
            return self._sessions.get(sid)

    def latest_sid(self) -> Optional[str]:
        with self._lock:
            return self._creation_order[-1] if self._creation_order else None

    def new(
        self,
        *,
        model_id: str,
        repo_name: str,
        cwd: str,
        effort: str = DEFAULT_EFFORT,
        permission_mode: str = DEFAULT_PERMISSION_MODE,
        command: str = "claude",
        resume_session_id: str = "",
        settings_path: str = "",
    ) -> HeadlessSession:
        with self._lock:
            sid = f"h{int(time.time() * 1000):013d}"
            while sid in self._sessions:
                sid += "x"
        sess = HeadlessSession(
            sid=sid,
            model_id=model_id,
            repo_name=repo_name,
            cwd=cwd,
            effort=effort,
            permission_mode=permission_mode,
            command=command,
            resume_session_id=resume_session_id,
            settings_path=settings_path,
        )
        with self._lock:
            self._sessions[sid] = sess
            self._creation_order.append(sid)
        sess.start()
        return sess

    def remove(self, sid: str) -> bool:
        with self._lock:
            sess = self._sessions.pop(sid, None)
            if sid in self._creation_order:
                self._creation_order.remove(sid)
        if sess is None:
            return False
        sess.close()
        return True

    def shutdown(self) -> None:
        with self._lock:
            sids = list(self._sessions.keys())
        for sid in sids:
            self.remove(sid)


# ----------------------------------------------------------------------------
# 自测：python3 -m app_ado.ai_headless_session  或  python3 ai_headless_session.py
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    scratch = tempfile.mkdtemp(prefix="hs_smoke_")
    done = threading.Event()
    results = {"n": 0}

    def on_event(sess: HeadlessSession, ev: HeadlessEvent) -> None:
        if ev.kind == "init":
            print(f"[init] claude_session_id={ev.text}")
        elif ev.kind == "assistant":
            print(f"[assistant] {ev.text!r}")
        elif ev.kind == "thinking":
            print(f"[thinking] {ev.text[:60]!r}...")
        elif ev.kind == "tool_use":
            print(f"[tool_use] {ev.tool_name} {ev.tool_input}")
        elif ev.kind == "tool_result":
            print(f"[tool_result err={ev.is_error}] {ev.text[:80]!r}")
        elif ev.kind == "result":
            results["n"] += 1
            print(f"[result#{results['n']}] err={ev.is_error} cost={ev.cost_usd} "
                  f"subtype={ev.subtype}")
            if results["n"] == 1:
                sess.send_user("What token did I ask for? Reply with exactly that token.")
            else:
                done.set()
        elif ev.kind == "error":
            print(f"[error] {ev.text}")
        elif ev.kind == "exit":
            print(f"[exit] code={ev.exit_code}")
            done.set()

    mgr = HeadlessSessionManager()
    sess = mgr.new(model_id="haiku", repo_name="smoke", cwd=scratch)
    sess.add_listener(on_event)
    sess.send_user("Reply with exactly the token PONG-BETA and nothing else.")
    done.wait(timeout=90)
    print(f"[smoke] results_seen={results['n']} claude_session_id={sess.info.claude_session_id}")
    mgr.shutdown()
