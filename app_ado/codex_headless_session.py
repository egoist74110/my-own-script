"""Headless Codex 会话（OpenAI Codex CLI 结构化对话）。

和 Claude 的 ai_headless_session 思路相同（结构化事件 → TG 消息），但**协议完全不同**，
因为 Codex CLI 的规则和 Claude 不一样，不能照搬：

  Claude：一个常驻进程，stdin 用 stream-json 多轮喂。
  Codex ：**每一轮一个进程**——
            首轮  : codex exec --json [-m M] [-c model_reasoning_effort=E] [沙箱] -C cwd "<prompt>"
            续聊  : codex exec resume <thread_id> --json [-m M] [-c ...] "<prompt>"
          首轮在 `thread.started` 事件里拿到 thread_id，之后用它 resume 续上下文。
          复用本机 `codex` 已登录的 ChatGPT 订阅（无需 API key）。

Codex 的几条硬规则（已在本机实测，CLI 0.123.0）：
  - 模型(-m)：gpt-5.5 需要更新的 CLI；gpt-5 / gpt-5-codex 在 ChatGPT 账号下被拒；
    gpt-5.4-mini 可用。留空则不传 -m，走 codex 自己的配置默认。
  - 思考强度：`-c model_reasoning_effort=` 取 minimal|low|medium|high（**和 Claude 的档位不同**）。
  - 审计/沙箱：exec 是非交互的，**没有 Claude 那种逐条工具审批**；只能在首轮用沙箱档位定调：
      read-only          -> -s read-only（只读，不能改文件）
      workspace-write    -> --full-auto（可改工作区 + 失败时才升权）
      danger-full-access -> --dangerously-bypass-approvals-and-sandbox（完全放开）
    resume 续聊**不接受 -s**（沙箱继承首轮），所以续聊只补 -m / -c。

事件（codex exec --json，新 thread/turn/item 协议，已实测）：
  {"type":"thread.started","thread_id":"<uuid>"}
  {"type":"turn.started"}
  {"type":"item.started"/"item.completed"/"item.updated","item":{...}}
      item.type: agent_message{text} / reasoning{text} /
                 command_execution{command,aggregated_output,exit_code,status} /
                 file_change / patch / mcp_tool_call / todo_list / web_search / error
  {"type":"turn.completed","usage":{input_tokens,cached_input_tokens,output_tokens}}
  {"type":"turn.failed","error":{"message":...}}
  {"type":"error","message":...}
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

from app_ado.ai_headless_session import HeadlessEvent, _augment_path


# ----------------------------------------------------------------------------
# 配置 / 选项（Codex 自己的合法档位，和 Claude 不同）
# ----------------------------------------------------------------------------

# codex 的 model_reasoning_effort 合法档位
EFFORT_CHOICES = ("minimal", "low", "medium", "high")
# 审计/沙箱档位（本工具对外的友好键 → 实际 codex flag 在 _sandbox_args 里翻译）
AUDIT_CHOICES = ("read-only", "workspace-write", "danger-full-access")

DEFAULT_EFFORT = "medium"
DEFAULT_AUDIT = "workspace-write"   # = --full-auto：可改工作区，远程用最顺手


def resolve_codex_executable(command: str = "codex") -> Optional[str]:
    """在补全后的 PATH 里解析 codex 可执行文件路径。"""
    try:
        argv = shlex.split(command)
    except Exception:
        return None
    if not argv:
        return None
    env = _augment_path(os.environ.copy())
    return shutil.which(argv[0], path=env["PATH"])


# ----------------------------------------------------------------------------
# 会话信息
# ----------------------------------------------------------------------------

@dataclass
class CodexInfo:
    sid: str                       # 本地内部短 id
    repo_name: str
    cwd: str
    model_id: str = ""             # 留空 = 不传 -m（走 codex 配置默认）
    effort: str = DEFAULT_EFFORT   # minimal|low|medium|high；留空 = 不传
    audit: str = DEFAULT_AUDIT     # read-only|workspace-write|danger-full-access
    command: str = "codex"
    thread_id: str = ""            # 首轮 thread.started 上报，用于 resume 续聊
    pid: int = 0
    status: str = "idle"           # idle | busy | exited
    exit_code: Optional[int] = None
    started_at: float = field(default_factory=time.time)
    total_input_tokens: int = 0
    total_output_tokens: int = 0


Listener = Callable[["CodexSession", HeadlessEvent], None]


# ----------------------------------------------------------------------------
# 会话（每轮一个 codex exec 进程）
# ----------------------------------------------------------------------------

class CodexSession:
    def __init__(
        self,
        *,
        sid: str,
        repo_name: str,
        cwd: str,
        model_id: str = "",
        effort: str = DEFAULT_EFFORT,
        audit: str = DEFAULT_AUDIT,
        command: str = "codex",
        thread_id: str = "",
    ) -> None:
        if effort and effort not in EFFORT_CHOICES:
            effort = DEFAULT_EFFORT
        if audit not in AUDIT_CHOICES:
            audit = DEFAULT_AUDIT
        self.info = CodexInfo(
            sid=sid,
            repo_name=repo_name,
            cwd=cwd,
            model_id=model_id or "",
            effort=effort,
            audit=audit,
            command=command or "codex",
            thread_id=thread_id or "",
        )
        self._listeners: list[Listener] = []
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._closed = False
        self._pending: list[str] = []        # 处理中再发的提示词排队
        self._turn_saw_result = False        # 本轮是否已发过 result（区分正常结束/异常退出）

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

    def _sandbox_args(self, *, resume: bool) -> list[str]:
        """把审计档位翻译成 codex flag。resume 不接受 -s（继承首轮沙箱）。"""
        audit = self.info.audit
        if audit == "danger-full-access":
            return ["--dangerously-bypass-approvals-and-sandbox"]
        if audit == "workspace-write":
            return ["--full-auto"]
        # read-only：首轮用 -s read-only；续聊不传（继承）
        return [] if resume else ["-s", "read-only"]

    def _build_argv(self, prompt: str, *, resume: bool) -> list[str]:
        exe = resolve_codex_executable(self.info.command) or "codex"
        argv = [exe, "exec"]
        if resume and self.info.thread_id:
            argv += ["resume", self.info.thread_id]
        argv += ["--json", "--skip-git-repo-check"]
        if not resume:
            argv += ["-C", self.info.cwd or os.getcwd()]
        if self.info.model_id:
            argv += ["-m", self.info.model_id]
        if self.info.effort:
            argv += ["-c", f"model_reasoning_effort={self.info.effort}"]
        argv += self._sandbox_args(resume=resume)
        argv += [prompt]
        return argv

    # ---------- 一轮 ----------

    def _start_turn(self, prompt: str) -> bool:
        """起一个 codex exec 进程跑一轮（调用方须持 self._lock）。"""
        if self._closed:
            return False
        resume = bool(self.info.thread_id)
        argv = self._build_argv(prompt, resume=resume)
        env = _augment_path(os.environ.copy())
        env.setdefault("TERM", "xterm-256color")
        env.pop("CI", None)
        cwd = self.info.cwd or os.getcwd()
        try:
            self._proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,   # 不让它等 stdin（prompt 走 argv）
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            self._emit(HeadlessEvent(kind="error", text=f"启动 codex 失败：{e}"))
            return False
        self.info.pid = self._proc.pid
        self.info.status = "busy"
        self._turn_saw_result = False
        threading.Thread(target=self._stdout_loop, args=(self._proc,), daemon=True,
                         name=f"cx-out-{self.info.sid}").start()
        threading.Thread(target=self._stderr_loop, args=(self._proc,), daemon=True,
                         name=f"cx-err-{self.info.sid}").start()
        threading.Thread(target=self._waiter_loop, args=(self._proc,), daemon=True,
                         name=f"cx-wait-{self.info.sid}").start()
        return True

    def _stdout_loop(self, proc: subprocess.Popen) -> None:
        if proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                # codex 偶尔在 stdout 打非 JSON 提示行，忽略
                continue
            try:
                self._dispatch_event(obj)
            except Exception as e:
                self._emit(HeadlessEvent(kind="error", text=f"解析事件异常：{e}"))

    def _stderr_loop(self, proc: subprocess.Popen) -> None:
        if proc.stderr is None:
            return
        for line in proc.stderr:
            s = line.rstrip("\n").strip()
            if not s:
                continue
            # codex 配了但没起的 MCP 会刷 rmcp 噪声，过滤掉，别污染会话
            if "rmcp::" in s or "Transport channel closed" in s:
                continue
            self._emit(HeadlessEvent(kind="error", text=s[:2000]))

    def _waiter_loop(self, proc: subprocess.Popen) -> None:
        code = proc.wait()
        with self._lock:
            # 进程异常退出且本轮没收到 turn.completed/failed：补一条 result，免得 UI 卡在“运行中”
            if not self._turn_saw_result and not self._closed:
                self._emit(HeadlessEvent(
                    kind="result", is_error=(code != 0),
                    subtype="exited" if code != 0 else "ok",
                ))
            # 本轮收尾：有排队就接着跑下一条，否则置空闲
            nxt: Optional[str] = None
            if not self._closed and self._pending:
                nxt = self._pending.pop(0)
            if nxt is not None:
                self._start_turn(nxt)
            else:
                self._proc = None
                if not self._closed:
                    self.info.status = "idle"

    # ---------- 事件归一化（codex thread/turn/item → HeadlessEvent）----------

    def _dispatch_event(self, obj: dict) -> None:
        t = obj.get("type")

        if t == "thread.started":
            tid = obj.get("thread_id") or ""
            if tid:
                self.info.thread_id = tid
            self._emit(HeadlessEvent(kind="init", text=tid, raw=obj))
            return

        if t == "turn.started":
            return

        if t in ("item.started", "item.updated", "item.completed"):
            self._dispatch_item(t, obj.get("item") or {})
            return

        if t == "turn.completed":
            usage = obj.get("usage") or {}
            self.info.total_input_tokens += int(usage.get("input_tokens") or 0)
            self.info.total_output_tokens += int(usage.get("output_tokens") or 0)
            self._turn_saw_result = True
            self._emit(HeadlessEvent(kind="result", is_error=False, subtype="ok", raw=obj))
            return

        if t == "turn.failed":
            err = obj.get("error") or {}
            msg = _clean_err(err.get("message") or "")
            self._turn_saw_result = True
            self._emit(HeadlessEvent(kind="result", is_error=True, text=msg,
                                     subtype="failed", raw=obj))
            return

        if t == "error":
            self._emit(HeadlessEvent(kind="error", text=_clean_err(obj.get("message") or ""), raw=obj))
            return

        # 其它事件忽略
        return

    def _dispatch_item(self, ev_type: str, item: dict) -> None:
        it = item.get("type")

        if it == "agent_message":
            # 只在 completed 时发，避免重复
            if ev_type == "item.completed":
                txt = item.get("text") or ""
                if txt.strip():
                    self._emit(HeadlessEvent(kind="assistant", text=txt, raw=item))
            return

        if it == "reasoning":
            if ev_type == "item.completed":
                txt = item.get("text") or item.get("summary") or ""
                if txt and str(txt).strip():
                    self._emit(HeadlessEvent(kind="thinking", text=str(txt), raw=item))
            return

        if it == "command_execution":
            if ev_type == "item.started":
                self._emit(HeadlessEvent(
                    kind="tool_use", tool_name="shell",
                    tool_input={"command": item.get("command") or ""},
                    tool_use_id=item.get("id") or "", raw=item,
                ))
            elif ev_type == "item.completed":
                code = item.get("exit_code")
                self._emit(HeadlessEvent(
                    kind="tool_result", tool_use_id=item.get("id") or "",
                    text=item.get("aggregated_output") or "",
                    is_error=(code is not None and int(code) != 0), raw=item,
                ))
            return

        if it in ("file_change", "patch"):
            if ev_type in ("item.started", "item.completed"):
                files = item.get("changes") or item.get("files") or []
                summ = ", ".join(
                    str(c.get("path") or c.get("file") or "")
                    for c in files if isinstance(c, dict)
                ) if isinstance(files, list) else ""
                if ev_type == "item.started":
                    self._emit(HeadlessEvent(
                        kind="tool_use", tool_name="apply_patch",
                        tool_input={"files": summ}, tool_use_id=item.get("id") or "", raw=item,
                    ))
                else:
                    self._emit(HeadlessEvent(
                        kind="tool_result", tool_use_id=item.get("id") or "",
                        text=(f"已改：{summ}" if summ else "已应用补丁"), raw=item,
                    ))
            return

        if it == "mcp_tool_call":
            if ev_type == "item.started":
                name = item.get("tool") or item.get("name") or "mcp"
                self._emit(HeadlessEvent(
                    kind="tool_use", tool_name=f"mcp:{name}",
                    tool_input=item.get("arguments") or {},
                    tool_use_id=item.get("id") or "", raw=item,
                ))
            elif ev_type == "item.completed":
                self._emit(HeadlessEvent(
                    kind="tool_result", tool_use_id=item.get("id") or "",
                    text=_short_any(item.get("result")), is_error=bool(item.get("is_error")), raw=item,
                ))
            return

        if it == "web_search":
            if ev_type == "item.started":
                self._emit(HeadlessEvent(
                    kind="tool_use", tool_name="web_search",
                    tool_input={"query": item.get("query") or ""},
                    tool_use_id=item.get("id") or "", raw=item,
                ))
            return

        if it == "todo_list":
            if ev_type == "item.completed":
                items = item.get("items") or item.get("todos") or []
                n = len(items) if isinstance(items, list) else 0
                self._emit(HeadlessEvent(
                    kind="tool_use", tool_name="todo", tool_input={"todos": items}, raw=item,
                ))
            return

        if it == "error":
            if ev_type in ("item.completed", "item.started"):
                self._emit(HeadlessEvent(kind="error", text=_clean_err(item.get("message") or ""), raw=item))
            return

        # 未知 item 类型：completed 时给个轻提示，方便发现新事件
        if ev_type == "item.completed" and it:
            self._emit(HeadlessEvent(kind="tool_use", tool_name=str(it), raw=item))

    # ---------- 输入 ----------

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._proc is not None and self.info.status == "busy"

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def submit(self, text: str) -> tuple[str, int]:
        """提交一轮提示词。处理中则排队。

        返回 (status, queue_pos)：
          ("sent", 0)    立即起一轮
          ("queued", n)  已排队，n 是排队位次
          ("closed"/"error", 0)
        """
        with self._lock:
            if self._closed:
                return ("closed", 0)
            if self._proc is not None and self.info.status == "busy":
                self._pending.append(text)
                return ("queued", len(self._pending))
            ok = self._start_turn(text)
        return ("sent", 0) if ok else ("error", 0)

    def send_user(self, text: str) -> bool:
        status, _ = self.submit(text)
        return status in ("sent", "queued")

    def interrupt(self) -> bool:
        """中断当前轮：杀掉当前 codex 进程并清空排队。thread_id 保留，下一条会 resume 续上。"""
        with self._lock:
            self._pending.clear()
            proc = self._proc
        if proc is None:
            return False
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                proc.kill()
            return True
        except Exception:
            return False

    # ---------- 关闭 ----------

    def close(self, *, grace_seconds: float = 3.0) -> None:
        with self._lock:
            self._closed = True
            self._pending.clear()
            proc = self._proc
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=grace_seconds)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.info.status = "exited"


def _clean_err(msg: str) -> str:
    """codex 的 error.message 常是一坨 JSON，尽量抠出人话。"""
    s = (msg or "").strip()
    if not s:
        return ""
    try:
        j = json.loads(s)
        if isinstance(j, dict):
            err = j.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
            if j.get("message"):
                return str(j["message"])
    except Exception:
        pass
    return s[:2000]


def _short_any(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v[:2000]
    try:
        return json.dumps(v, ensure_ascii=False)[:2000]
    except Exception:
        return str(v)[:2000]


# ----------------------------------------------------------------------------
# 多会话注册表
# ----------------------------------------------------------------------------

class CodexSessionManager:
    """全局多 Codex 会话注册表。线程安全。接口对齐 HeadlessSessionManager。"""

    def __init__(self) -> None:
        self._sessions: dict[str, CodexSession] = {}
        self._creation_order: list[str] = []
        self._lock = threading.Lock()

    def list(self) -> list[CodexInfo]:
        with self._lock:
            return [s.info for s in self._sessions.values()]

    def get(self, sid: str) -> Optional[CodexSession]:
        with self._lock:
            return self._sessions.get(sid)

    def latest_sid(self) -> Optional[str]:
        with self._lock:
            return self._creation_order[-1] if self._creation_order else None

    def new(
        self,
        *,
        repo_name: str,
        cwd: str,
        model_id: str = "",
        effort: str = DEFAULT_EFFORT,
        audit: str = DEFAULT_AUDIT,
        command: str = "codex",
        thread_id: str = "",
    ) -> CodexSession:
        with self._lock:
            sid = f"c{int(time.time() * 1000):013d}"
            while sid in self._sessions:
                sid += "x"
        sess = CodexSession(
            sid=sid, repo_name=repo_name, cwd=cwd, model_id=model_id,
            effort=effort, audit=audit, command=command, thread_id=thread_id,
        )
        with self._lock:
            self._sessions[sid] = sess
            self._creation_order.append(sid)
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
