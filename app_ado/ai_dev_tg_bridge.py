"""AI 开发 ↔ Telegram 桥。

把 AiDevSession 的屏幕快照推送到 TG（每个会话一条可编辑的消息 + 软键盘按钮），
并把 TG 端的文字消息 / inline callback 注入到对应的 PTY。

设计：
- 每个 (chat_id, sid) 维护一条 TG 消息（首次 sendMessage，后续 editMessageText）。
- 一个统一的 flusher 线程做节流刷新（避免 TUI 重绘把 TG 刷爆）。
- 路由：TG 用户消息默认走"该 chat 当前活跃会话"（创建顺序最新者）。
  用户在 TG 上 reply 某条会话输出消息 → 自动路由到该会话。
- 权限：role == 'owner' 全通；role == 'group' 看 group 字典里的 can_dev 标志（默认放行）。

仅在 POSIX 下可用；Windows 不会被注入到主程序的远程开发流程。
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import httpx

from app_ado.ai_dev_session import (
    KEY_CODES,
    AiDevSession,
    AiDevSessionManager,
    resolve_command_executable,
)


_MAX_LINES_TO_SEND = 24
_MAX_LINE_WIDTH = 100
_FLUSH_MIN_INTERVAL = 0.4  # 同一会话两次 TG 编辑之间最少间隔（秒）
_TG_HTTP_TIMEOUT = 12.0


def _truncate_for_tg(snapshot: str) -> str:
    lines = snapshot.splitlines()
    if len(lines) > _MAX_LINES_TO_SEND:
        lines = lines[-_MAX_LINES_TO_SEND:]
    out = []
    for ln in lines:
        if len(ln) > _MAX_LINE_WIDTH:
            out.append(ln[: _MAX_LINE_WIDTH - 1] + "…")
        else:
            out.append(ln)
    text = "\n".join(out).rstrip()
    return text or "(无输出)"


def _format_screen_message(sess: AiDevSession) -> str:
    head = f"[#{sess.info.sid} · {sess.info.model_label} · {sess.info.repo_name}]"
    status_line = {
        "starting": "状态：启动中",
        "running": "状态：运行中",
        "waiting": "状态：等待 Y/N",
        "exited": f"状态：已退出（exit={sess.info.exit_code}）",
    }.get(sess.info.status, f"状态：{sess.info.status}")
    body = _truncate_for_tg(sess.snapshot_text())
    return f"{head}\n{status_line}\n```\n{body}\n```"


def _keyboard_for_session(sess: AiDevSession) -> dict:
    sid = sess.info.sid
    if sess.info.status == "exited":
        return {"inline_keyboard": [[{"text": "🗑 删除", "callback_data": f"dev_kill:{sid}"}]]}
    rows: list[list[dict]] = []
    if sess.info.awaiting_yn:
        rows.append([
            {"text": "✅ 是", "callback_data": f"dev_key:{sid}:y"},
            {"text": "❌ 否", "callback_data": f"dev_key:{sid}:n"},
        ])
    rows.append([
        {"text": "↑", "callback_data": f"dev_key:{sid}:up"},
        {"text": "↓", "callback_data": f"dev_key:{sid}:down"},
        {"text": "←", "callback_data": f"dev_key:{sid}:left"},
        {"text": "→", "callback_data": f"dev_key:{sid}:right"},
    ])
    rows.append([
        {"text": "Enter", "callback_data": f"dev_key:{sid}:enter"},
        {"text": "Esc", "callback_data": f"dev_key:{sid}:esc"},
        {"text": "Tab", "callback_data": f"dev_key:{sid}:tab"},
    ])
    rows.append([
        {"text": "⌫", "callback_data": f"dev_key:{sid}:backspace"},
        {"text": "Space", "callback_data": f"dev_key:{sid}:space"},
        {"text": "Ctrl+C", "callback_data": f"dev_key:{sid}:ctrl_c"},
    ])
    rows.append([
        {"text": "🗑 删除", "callback_data": f"dev_kill:{sid}"},
    ])
    return {"inline_keyboard": rows}


class AiDevTgBridge:
    def __init__(
        self,
        *,
        manager: AiDevSessionManager,
        bot_token_fn: Callable[[], Optional[str]],
        owner_chat_id_fn: Callable[[], Optional[str]],
    ) -> None:
        self._manager = manager
        self._bot_token_fn = bot_token_fn
        self._owner_chat_id_fn = owner_chat_id_fn

        # (chat_id, sid) -> TG message_id
        self._msg_ids: dict[tuple[str, str], int] = {}
        # msg_id -> sid（用于 reply-to 反查）
        self._msg_to_sid: dict[int, str] = {}
        # chat_id -> sid（当前活跃会话；优先使用 reply-to 覆盖）
        self._chat_focus: dict[str, str] = {}
        # sid -> last sent screen + last flush time
        self._last_sent: dict[str, str] = {}
        self._last_flush: dict[str, float] = {}
        # sid -> set(chat_id)：哪些 chat 已订阅这个会话的输出
        self._sid_to_chats: dict[str, set[str]] = {}
        # sid -> last awaiting_yn flag sent
        self._last_yn: dict[str, bool] = {}

        # dirty 标记：sid 集合
        self._dirty: set[str] = set()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._flusher: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._flusher and self._flusher.is_alive():
            return
        self._stop.clear()
        self._flusher = threading.Thread(target=self._flush_loop, daemon=True, name="ai_dev_tg_flush")
        self._flusher.start()

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()

    # ------------------------------------------------------------------
    # 权限：复用 owner/group 的 ACL，不引入新机制
    # ------------------------------------------------------------------

    @staticmethod
    def can_dev(role: str, group: Optional[dict], action: str) -> bool:
        """AI 开发模块的权限：默认 owner-only。

        非 owner 一律拒绝，除非 group 字典显式打开对应 flag：
          can_dev_run / can_dev_message / can_dev_stop
        这是为了避免白名单成员意外获得"在 owner 机器上起 AI 会话 / 发消息进入 PTY"的能力。
        """
        if role == "owner":
            return True
        if role != "group" or not group:
            return False
        flag_map = {
            "dev_status": "can_dev_status",
            "dev_run": "can_dev_run",
            "dev_message": "can_dev_message",
            "dev_stop": "can_dev_stop",
        }
        flag = flag_map.get(action)
        if flag is None:
            return False
        # 默认 False：必须显式开关才放行
        return bool(group.get(flag, False))

    # ------------------------------------------------------------------
    # TelegramController 调用入口
    # ------------------------------------------------------------------

    def handle_list(self, chat_id: str, role: str, group: Optional[dict]) -> str:
        if not self.can_dev(role, group, "dev_status"):
            return "无权限：dev"
        infos = self._manager.list()
        focus = self._chat_focus.get(str(chat_id)) or self._manager.latest_sid()
        if not infos:
            return "当前没有 AI 开发会话。\n用 /devnew <gemini|claude|codex> <repo_name> 新开一个。"
        lines = ["AI 开发会话列表："]
        for info in infos:
            mark = "★" if info.sid == focus else " "
            status_zh = {
                "starting": "启动中",
                "running": "运行中",
                "waiting": "等Y/N",
                "exited": f"已退出({info.exit_code})",
            }.get(info.status, info.status)
            lines.append(f"{mark} #{info.sid} {info.model_label} | {info.repo_name} | {status_zh}")
        lines.append("")
        lines.append("/devfocus <sid> 切换活跃会话；/devkill <sid> 删除会话。")
        return "\n".join(lines)

    def handle_new(
        self,
        *,
        model_id: str,
        repo_path: str,
        repo_name: str,
        repo_id: str,
        command: str,
        chat_id: str,
        role: str,
        group: Optional[dict],
    ) -> tuple[bool, str]:
        if not self.can_dev(role, group, "dev_run"):
            return False, "无权限：dev_run"
        if not resolve_command_executable(command):
            return False, f"命令不可用：{command}（请检查 AI 配置和 PATH）"
        label = {"codex": "Codex", "gemini": "Gemini CLI", "claude_code": "Claude Code"}.get(model_id, model_id)
        sess = self._manager.new(
            model_id=model_id,
            model_label=label,
            repo_id=repo_id,
            repo_name=repo_name,
            cwd=repo_path,
            command=command,
        )
        self._attach_session(sess, chat_id)
        self._chat_focus[str(chat_id)] = sess.info.sid
        return True, f"已启动会话 #{sess.info.sid}（{label} / {repo_name}）"

    def handle_kill(self, sid: str, chat_id: str, role: str, group: Optional[dict]) -> tuple[bool, str]:
        if not self.can_dev(role, group, "dev_stop"):
            return False, "无权限：dev_stop"
        if not self._manager.get(sid):
            return False, f"会话不存在：{sid}"
        self._manager.remove(sid)
        # 清掉关联状态
        with self._lock:
            kill_keys = [k for k in self._msg_ids if k[1] == sid]
            for k in kill_keys:
                mid = self._msg_ids.pop(k, None)
                if mid is not None:
                    self._msg_to_sid.pop(mid, None)
            self._last_sent.pop(sid, None)
            self._last_flush.pop(sid, None)
            self._sid_to_chats.pop(sid, None)
            self._last_yn.pop(sid, None)
            self._dirty.discard(sid)
            for cid, focused in list(self._chat_focus.items()):
                if focused == sid:
                    self._chat_focus.pop(cid, None)
        return True, f"已删除会话 #{sid}"

    def handle_focus(self, sid: str, chat_id: str, role: str, group: Optional[dict]) -> tuple[bool, str]:
        if not self.can_dev(role, group, "dev_message"):
            return False, "无权限：dev_message"
        if not self._manager.get(sid):
            return False, f"会话不存在：{sid}"
        self._chat_focus[str(chat_id)] = sid
        return True, f"当前活跃会话已切换为 #{sid}"

    def handle_text(
        self,
        *,
        text: str,
        chat_id: str,
        reply_to_msg_id: Optional[int],
        role: str,
        group: Optional[dict],
    ) -> tuple[bool, str]:
        if not self.can_dev(role, group, "dev_message"):
            return False, "无权限：dev_message"
        sid = self._resolve_target_sid(chat_id, reply_to_msg_id)
        if not sid:
            return False, "没有活跃会话。先用 /devnew 或 /devfocus。"
        sess = self._manager.get(sid)
        if not sess:
            return False, f"会话不存在：{sid}"
        if sess.info.status == "exited":
            return False, f"会话 #{sid} 已退出。"
        ok = sess.write_text(text, append_enter=True)
        if not ok:
            return False, "写入失败（会话可能已关闭）"
        return True, ""  # 静默：不另发"已发送"，等屏幕自然刷出来

    def handle_key(
        self,
        *,
        key: str,
        sid: str,
        chat_id: str,
        role: str,
        group: Optional[dict],
    ) -> tuple[bool, str]:
        if not self.can_dev(role, group, "dev_message"):
            return False, "无权限"
        sess = self._manager.get(sid)
        if not sess:
            return False, f"会话不存在：{sid}"
        if sess.info.status == "exited":
            return False, "会话已退出"
        if key not in KEY_CODES:
            return False, f"未知按键：{key}"
        sess.send_key(key)
        return True, ""

    # 反查：TG reply-to 的目标消息是否属于某个远程开发会话
    def msg_id_to_sid(self, msg_id: int) -> Optional[str]:
        return self._msg_to_sid.get(int(msg_id))

    def should_consume_text(self, chat_id: str, reply_to_msg_id: Optional[int]) -> bool:
        """controller 用：判断这条非 / 文字消息是否应该送到远程开发会话。

        规则：reply-to 命中 dev 会话消息 → True；该 chat 已经显式 focus 过 → True；
        否则不消费（避免吃掉用户的闲聊）。
        """
        if reply_to_msg_id is not None:
            sid = self._msg_to_sid.get(int(reply_to_msg_id))
            if sid and self._manager.get(sid):
                return True
        sid = self._chat_focus.get(str(chat_id))
        if sid and self._manager.get(sid):
            return True
        return False

    def attach_chat_to_session(self, chat_id: str, sid: str) -> None:
        """桌面端创建会话后，把 owner chat 自动挂上来；这样 owner 直接发文字就到这个会话。"""
        if not chat_id or not sid:
            return
        if not self._manager.get(sid):
            return
        with self._lock:
            self._sid_to_chats.setdefault(sid, set()).add(str(chat_id))
            self._chat_focus[str(chat_id)] = sid
        self._mark_dirty(sid)

    # ------------------------------------------------------------------
    # 内部：订阅会话、节流刷新
    # ------------------------------------------------------------------

    def _attach_session(self, sess: AiDevSession, chat_id: str) -> None:
        sid = sess.info.sid
        with self._lock:
            self._sid_to_chats.setdefault(sid, set()).add(str(chat_id))
        sess.add_listener(lambda snap, yn, _s=sid: self._on_session_update(_s, snap, yn))
        self._mark_dirty(sid)

    def _on_session_update(self, sid: str, snapshot: str, awaiting_yn: bool) -> None:
        self._mark_dirty(sid)

    def _mark_dirty(self, sid: str) -> None:
        with self._cond:
            self._dirty.add(sid)
            self._cond.notify_all()

    def _resolve_target_sid(self, chat_id: str, reply_to_msg_id: Optional[int]) -> Optional[str]:
        if reply_to_msg_id is not None:
            sid = self._msg_to_sid.get(int(reply_to_msg_id))
            if sid and self._manager.get(sid):
                return sid
        sid = self._chat_focus.get(str(chat_id))
        if sid and self._manager.get(sid):
            return sid
        return self._manager.latest_sid()

    def _flush_loop(self) -> None:
        while not self._stop.is_set():
            with self._cond:
                while not self._dirty and not self._stop.is_set():
                    self._cond.wait(timeout=1.0)
                if self._stop.is_set():
                    return
                pending = list(self._dirty)
                self._dirty.clear()
            for sid in pending:
                try:
                    self._flush_one(sid)
                except Exception:
                    pass

    def _flush_one(self, sid: str) -> None:
        sess = self._manager.get(sid)
        if sess is None:
            return
        now = time.time()
        last = self._last_flush.get(sid, 0.0)
        if now - last < _FLUSH_MIN_INTERVAL:
            time.sleep(_FLUSH_MIN_INTERVAL - (now - last))
        text = _format_screen_message(sess)
        kb = _keyboard_for_session(sess)
        last_text = self._last_sent.get(sid)
        last_yn = self._last_yn.get(sid)
        if last_text == text and last_yn == sess.info.awaiting_yn:
            return  # nothing changed
        token = self._bot_token_fn()
        if not token:
            return
        with self._lock:
            chats = list(self._sid_to_chats.get(sid, set()))
        if not chats:
            owner = self._owner_chat_id_fn()
            if owner:
                chats = [str(owner)]
                with self._lock:
                    self._sid_to_chats.setdefault(sid, set()).add(str(owner))
        for chat_id in chats:
            self._send_or_edit(token, chat_id, sid, text, kb)
        self._last_sent[sid] = text
        self._last_yn[sid] = sess.info.awaiting_yn
        self._last_flush[sid] = time.time()

    def _send_or_edit(self, token: str, chat_id: str, sid: str, text: str, kb: dict) -> None:
        key = (str(chat_id), sid)
        mid = self._msg_ids.get(key)
        if mid is not None:
            ok = self._tg_edit(token, chat_id, mid, text, kb)
            if ok:
                return
            # 编辑失败（可能消息被删/过期），重发一条
            with self._lock:
                self._msg_to_sid.pop(mid, None)
                self._msg_ids.pop(key, None)
        new_mid = self._tg_send(token, chat_id, text, kb)
        if new_mid is not None:
            with self._lock:
                self._msg_ids[key] = new_mid
                self._msg_to_sid[new_mid] = sid

    @staticmethod
    def _tg_send(token: str, chat_id: str, text: str, kb: dict) -> Optional[int]:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": str(chat_id),
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
            "reply_markup": kb,
        }
        try:
            with httpx.Client(timeout=httpx.Timeout(_TG_HTTP_TIMEOUT, connect=5.0)) as c:
                r = c.post(url, json=payload)
                if r.status_code != 200:
                    # Markdown 解析失败时退化为纯文本
                    payload.pop("parse_mode", None)
                    r = c.post(url, json=payload)
                if r.status_code != 200:
                    return None
                data = r.json()
                if not data.get("ok"):
                    return None
                return int(data.get("result", {}).get("message_id") or 0) or None
        except Exception:
            return None

    @staticmethod
    def _tg_edit(token: str, chat_id: str, message_id: int, text: str, kb: dict) -> bool:
        url = f"https://api.telegram.org/bot{token}/editMessageText"
        payload = {
            "chat_id": str(chat_id),
            "message_id": int(message_id),
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
            "reply_markup": kb,
        }
        try:
            with httpx.Client(timeout=httpx.Timeout(_TG_HTTP_TIMEOUT, connect=5.0)) as c:
                r = c.post(url, json=payload)
                if r.status_code != 200:
                    payload.pop("parse_mode", None)
                    r = c.post(url, json=payload)
                if r.status_code != 200:
                    return False
                data = r.json()
                # "message is not modified" 也算成功；不需要重发
                if not data.get("ok"):
                    desc = str(data.get("description") or "")
                    return "not modified" in desc.lower()
                return True
        except Exception:
            return False
