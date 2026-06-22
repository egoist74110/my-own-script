"""Headless Antigravity CLI 会话（谷歌 Gemini CLI 废弃后的继任者，命令 `agy`）。

和 Claude(ai_headless_session)/Codex(codex_headless_session) 思路一致（一轮对话 → TG 消息），
但 **agy 的协议比那两个都简单**，因为本机实测 `agy --help` 没有任何 `--json`/流式输出：

  Claude：常驻进程 + stream-json 多轮；逐条工具事件 + PreToolUse 审批。
  Codex ：每轮一个 `codex exec --json` 进程；thread/turn/item 结构化事件。
  agy   ：每轮一个 `agy --print` 进程，**只在 stdout 打印最终回答纯文本**，没有结构化
          工具/思考事件。所以本会话只产出 `assistant`(最终回答) + `result`(完成/失败)，
          不会有 tool_use/thinking。

多轮续聊（本机实测）：
  - agy 把"会话"按 **工作目录(cwd)** 归档，映射写在
    ``~/.gemini/antigravity-cli/cache/last_conversations.json``（{cwd: conversation_id}）。
  - 首轮  : agy --print --dangerously-skip-permissions [--model "<名字>"] "<prompt>"  (cwd=工作目录)
  - 首轮跑完后从 last_conversations.json[cwd] 取到 conversation_id 存下来。
  - 续聊  : 同上再加 ``--conversation <conversation_id>``，精确续上（不用 --continue，
            因为 --continue 续的是"全局最近一次"，多会话交叉时会串）。

模型：`agy models` 动态列出（如 "Gemini 3.1 Pro (High)" / "Claude Sonnet 4.6 (Thinking)"），
      --model 传这个显示名即可；留空则走 agy 默认。

审计/沙箱（agy 只有两个相关开关，没有 codex 那种三档）：
  - auto    -> --dangerously-skip-permissions（自动批准所有工具，print 非交互必须，推荐）
  - sandbox -> --sandbox --dangerously-skip-permissions（终端受限沙箱 + 自动批准）
  注：print 模式无法交互应答权限弹窗，所以两档都带 --dangerously-skip-permissions，否则会卡住。
"""

from __future__ import annotations

import json
import os
import re
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
# 配置 / 选项
# ----------------------------------------------------------------------------

# 审计/沙箱档位（对外友好键 → 实际 agy flag 在 _sandbox_args 里翻译）
AUDIT_CHOICES = ("auto", "sandbox")
DEFAULT_AUDIT = "auto"

# print 模式每轮等待上限（秒）。传给 agy 的 --print-timeout，communicate 再多给 60s 兜底。
# 注：编码/分析任务可能更久，按需调大（agy 自己默认是 5m）。
PRINT_TIMEOUT_SEC = 120

# `agy models` 的结果缓存（同一进程内只查一次；列表很稳定，不值得每次开向导都 spawn）
_MODELS_CACHE: list[str] = []
_MODELS_LOCK = threading.Lock()

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s or "")


def resolve_antigravity_executable(command: str = "agy") -> Optional[str]:
    """在补全后的 PATH 里解析 agy 可执行文件路径。"""
    try:
        argv = shlex.split(command)
    except Exception:
        return None
    if not argv:
        return None
    env = _augment_path(os.environ.copy())
    return shutil.which(argv[0], path=env["PATH"])


def list_antigravity_models(command: str = "agy", *, force: bool = False) -> list[str]:
    """跑 `agy models` 取可用模型显示名列表（缓存）。失败返回空表（向导回退到"仅默认"）。"""
    global _MODELS_CACHE
    with _MODELS_LOCK:
        if _MODELS_CACHE and not force:
            return list(_MODELS_CACHE)
    exe = resolve_antigravity_executable(command) or "agy"
    try:
        env = _augment_path(os.environ.copy())
        cp = subprocess.run(
            [exe, "models"], capture_output=True, text=True, timeout=20, env=env,
        )
        models = [ln.strip() for ln in (cp.stdout or "").splitlines() if ln.strip()]
    except Exception:
        models = []
    with _MODELS_LOCK:
        if models:
            _MODELS_CACHE = list(models)
    return models


def _conversations_home() -> Path:
    # agy 废弃 Gemini CLI 后仍沿用 ~/.gemini 这个 home，会话状态在 antigravity-cli 子目录下。
    return Path.home() / ".gemini" / "antigravity-cli"


def _lookup_conversation_id(cwd: str) -> str:
    """从 last_conversations.json 里按 cwd 取 agy 分配的 conversation_id（取不到返回空串）。"""
    path = _conversations_home() / "cache" / "last_conversations.json"
    try:
        data = json.loads(path.read_text("utf-8") or "{}")
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    ap = os.path.abspath(os.path.expanduser(cwd or ""))
    val = data.get(ap) or data.get(cwd)
    return str(val) if val else ""


# ----------------------------------------------------------------------------
# 会话信息
# ----------------------------------------------------------------------------

@dataclass
class AntigravityInfo:
    sid: str                       # 本地内部短 id
    repo_name: str
    cwd: str
    model_id: str = ""             # 留空 = 不传 --model（走 agy 默认）
    audit: str = DEFAULT_AUDIT     # auto | sandbox
    command: str = "agy"
    conversation_id: str = ""      # 首轮后从 last_conversations.json[cwd] 取，用于 --conversation 续聊
    pid: int = 0
    status: str = "idle"           # idle | busy | exited
    exit_code: Optional[int] = None
    started_at: float = field(default_factory=time.time)


Listener = Callable[["AntigravitySession", HeadlessEvent], None]


# ----------------------------------------------------------------------------
# 会话（每轮一个 agy --print 进程）
# ----------------------------------------------------------------------------

class AntigravitySession:
    def __init__(
        self,
        *,
        sid: str,
        repo_name: str,
        cwd: str,
        model_id: str = "",
        audit: str = DEFAULT_AUDIT,
        command: str = "agy",
        conversation_id: str = "",
    ) -> None:
        if audit not in AUDIT_CHOICES:
            audit = DEFAULT_AUDIT
        self.info = AntigravityInfo(
            sid=sid,
            repo_name=repo_name,
            cwd=cwd,
            model_id=model_id or "",
            audit=audit,
            command=command or "agy",
            conversation_id=conversation_id or "",
        )
        self._listeners: list[Listener] = []
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._closed = False
        self._pending: list[str] = []   # 处理中再发的提示词排队

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

    def _sandbox_args(self) -> list[str]:
        if self.info.audit == "sandbox":
            return ["--sandbox", "--dangerously-skip-permissions"]
        return ["--dangerously-skip-permissions"]

    def _build_argv(self, prompt: str) -> list[str]:
        exe = resolve_antigravity_executable(self.info.command) or "agy"
        argv = [exe, "--print", f"--print-timeout={PRINT_TIMEOUT_SEC}s"]
        argv += self._sandbox_args()
        if self.info.model_id:
            argv += ["--model", self.info.model_id]
        if self.info.conversation_id:
            argv += ["--conversation", self.info.conversation_id]
        argv += [prompt]
        return argv

    # ---------- 一轮 ----------

    def _start_turn(self, prompt: str) -> bool:
        """起一个 agy --print 进程跑一轮（调用方须持 self._lock）。"""
        if self._closed:
            return False
        argv = self._build_argv(prompt)
        env = _augment_path(os.environ.copy())
        env.setdefault("TERM", "xterm-256color")
        env.pop("CI", None)
        cwd = self.info.cwd or os.getcwd()
        try:
            self._proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,   # prompt 走 argv，不等 stdin
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as e:
            self._emit(HeadlessEvent(kind="error", text=f"启动 agy 失败：{e}"))
            return False
        self.info.pid = self._proc.pid
        self.info.status = "busy"
        threading.Thread(target=self._turn_worker, args=(self._proc,), daemon=True,
                         name=f"agy-turn-{self.info.sid}").start()
        return True

    def _turn_worker(self, proc: subprocess.Popen) -> None:
        """读完一轮的 stdout/stderr，归一化成 assistant + result 事件，再处理排队。"""
        out, err = "", ""
        try:
            out, err = proc.communicate(timeout=PRINT_TIMEOUT_SEC + 60)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                out, err = proc.communicate(timeout=5)
            except Exception:
                pass
            self._emit(HeadlessEvent(kind="result", is_error=True,
                                     text="agy 超时未返回（已终止本轮）", subtype="timeout"))
            self._after_turn(code=-1)
            return
        except Exception as e:
            self._emit(HeadlessEvent(kind="error", text=f"读取 agy 输出异常：{e}"))
            self._after_turn(code=proc.returncode or -1)
            return

        code = proc.returncode
        answer = _strip_ansi(out or "").strip()
        stderr_msg = _strip_ansi(err or "").strip()

        if code == 0:
            if answer:
                self._emit(HeadlessEvent(kind="assistant", text=answer))
            self._emit(HeadlessEvent(kind="result", is_error=False, subtype="ok"))
        else:
            # 失败：优先把 stderr 当错因；stdout 偶尔也有用，兜底带上
            msg = stderr_msg or answer or f"agy 退出码 {code}"
            self._emit(HeadlessEvent(kind="result", is_error=True, text=msg, subtype="failed"))

        self._after_turn(code=code)

    def _after_turn(self, *, code: int) -> None:
        with self._lock:
            self.info.exit_code = code
            # 首轮跑完补抓 conversation_id（agy 按 cwd 归档），用于后续 --conversation 续聊
            if not self.info.conversation_id and not self._closed:
                cid = _lookup_conversation_id(self.info.cwd)
                if cid:
                    self.info.conversation_id = cid
            nxt: Optional[str] = None
            if not self._closed and self._pending:
                nxt = self._pending.pop(0)
            if nxt is not None:
                self._start_turn(nxt)
            else:
                self._proc = None
                if not self._closed:
                    self.info.status = "idle"

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
        """中断当前轮：杀掉当前 agy 进程并清空排队。conversation_id 保留，下条会续上。"""
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


# ----------------------------------------------------------------------------
# 多会话注册表
# ----------------------------------------------------------------------------

class AntigravitySessionManager:
    """全局多 Antigravity 会话注册表。线程安全。接口对齐 Codex/Claude 的 Manager。"""

    def __init__(self) -> None:
        self._sessions: dict[str, AntigravitySession] = {}
        self._creation_order: list[str] = []
        self._lock = threading.Lock()

    def list(self) -> list[AntigravityInfo]:
        with self._lock:
            return [s.info for s in self._sessions.values()]

    def get(self, sid: str) -> Optional[AntigravitySession]:
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
        audit: str = DEFAULT_AUDIT,
        command: str = "agy",
        conversation_id: str = "",
    ) -> AntigravitySession:
        with self._lock:
            sid = f"a{int(time.time() * 1000):013d}"
            while sid in self._sessions:
                sid += "x"
        sess = AntigravitySession(
            sid=sid, repo_name=repo_name, cwd=cwd, model_id=model_id,
            audit=audit, command=command, conversation_id=conversation_id,
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
