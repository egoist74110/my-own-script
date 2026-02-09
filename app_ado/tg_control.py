from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

import httpx

from app_ado.notifier_telegram import send_telegram_message
from app_ado.secrets import get_telegram_token
from app_ado.store import config_dir, load_ui_settings, load_task_settings


@dataclass
class TgCommandContext:
    chat_id: str
    username: str | None
    text: str


class TelegramController:
    """Poll Telegram updates and trigger app actions.

    Designed for: app running -> polling thread active.
    """

    def __init__(
        self,
        *,
        on_run: Callable[[str, str, str | None], tuple[bool, str]],
        on_stop: Callable[[str, str | None], None],
        on_status: Callable[[], str],
    ) -> None:
        self._on_run = on_run
        self._on_stop = on_stop
        self._on_status = on_status

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._offset_path = config_dir() / "tg_offset.json"
        self._log_path = config_dir() / "tg_control.log"
        self._state_path = config_dir() / "tg_control_state.json"
        self._update_offset = self._load_offset()

    def _load_offset(self) -> int | None:
        try:
            if self._offset_path.exists():
                j = json.loads(self._offset_path.read_text("utf-8"))
                v = j.get("next_offset")
                return int(v) if v is not None else None
        except Exception:
            return None
        return None

    def _save_offset(self, next_offset: int) -> None:
        try:
            self._offset_path.parent.mkdir(parents=True, exist_ok=True)
            self._offset_path.write_text(json.dumps({"next_offset": int(next_offset)}, indent=2), "utf-8")
        except Exception:
            pass

    def _write_state(self, **kv) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            import json

            self._state_path.write_text(json.dumps(kv, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass

    def _log(self, text: str) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(text.rstrip() + "\n")
        except Exception:
            pass

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _resolve_acl(self, chat_id: str, username: str | None) -> tuple[str, dict | None]:
        """Return (role, group) where role is 'owner'|'group'|'none'."""
        s = load_ui_settings()

        # owner
        if s.telegram_chat_id and str(chat_id) == str(s.telegram_chat_id):
            return "owner", None

        # legacy whitelist treated as viewer group
        wl = set(str(x).strip() for x in (s.telegram_whitelist or []) if str(x).strip())
        if str(chat_id) in wl or (username and ("@" + username) in wl):
            return "group", {"id": "legacy", "name": "白名单", "can_run": False, "can_stop": False, "can_status": True, "task_ids": []}

        # ACL members
        for m in s.telegram_acl_members or []:
            if m.get("chat_id") and str(m.get("chat_id")) == str(chat_id):
                gid = m.get("group_id")
                g = next((x for x in (s.telegram_acl_groups or []) if x.get("id") == gid), None)
                return ("group", g) if g else ("none", None)
            if username and m.get("username") and str(m.get("username")).lower() == ("@" + username).lower():
                gid = m.get("group_id")
                g = next((x for x in (s.telegram_acl_groups or []) if x.get("id") == gid), None)
                return ("group", g) if g else ("none", None)

        return "none", None

    def _can(self, role: str, group: dict | None, action: str, task_id: str | None = None) -> bool:
        if role == "owner":
            return True
        if role != "group" or not group:
            return False
        if action == "status":
            return bool(group.get("can_status", True))
        if action == "run":
            if not bool(group.get("can_run")):
                return False
            if task_id is None:
                return False
            return task_id in (group.get("task_ids") or [])
        if action == "stop":
            return bool(group.get("can_stop"))
        return False

    def _bot_token(self) -> str | None:
        return get_telegram_token()

    def _delete_webhook(self, token: str) -> None:
        """Ensure polling works by removing webhook if it was set elsewhere."""
        try:
            url = f"https://api.telegram.org/bot{token}/deleteWebhook"
            with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False) as c:
                r = c.post(url, data={"drop_pending_updates": "false"})
                r.raise_for_status()
        except Exception:
            return

    def _get_updates(self, token: str, *, timeout: int = 20) -> dict[str, Any]:
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        params: dict[str, Any] = {
            "timeout": int(timeout),
            "allowed_updates": json.dumps(["message"], ensure_ascii=False),
        }
        if self._update_offset is not None:
            params["offset"] = int(self._update_offset)
        with httpx.Client(timeout=httpx.Timeout(timeout + 5.0, connect=5.0), follow_redirects=False) as c:
            r = c.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"telegram getUpdates failed: {data}")
        return data

    def _reply(self, token: str, chat_id: str, text: str) -> None:
        send_telegram_message(bot_token=token, chat_id=chat_id, text=text)

    def _handle(self, token: str, ctx: TgCommandContext, *, role: str, group: dict | None) -> None:
        t = (ctx.text or "").strip()
        if not t.startswith("/"):
            return

        parts = t.split()
        cmd = parts[0].lower()

        if cmd in ("/help", "/start"):
            ts = load_task_settings()
            tasks = list(getattr(ts, "tasks", []) or [])
            tasks.sort(key=lambda t: (int(getattr(t, "sort_order", 0) or 0), (t.tg_command or "").lower()))

            def fmt_direct(t) -> str:
                # Keep command clickable by putting description on the next line
                cmd_line = f"/{(t.tg_command or '').strip()}"
                desc = (t.tg_desc or "").strip()
                return cmd_line + (f"\n  - {desc}" if desc else "")

            lines: list[str] = []
            if role == "owner":
                for t in tasks:
                    if not (t.tg_command or "").strip():
                        continue
                    lines.append(fmt_direct(t))
            else:
                for t in tasks:
                    if not (t.tg_command or "").strip():
                        continue
                    if self._can(role, group, "run", task_id=str(t.id)):
                        lines.append(fmt_direct(t))

            if role == "owner":
                msg = "可用命令（点击即可执行）：\n" + ("\n".join(lines) if lines else "（暂无任务）")
                msg += "\n/status  # 查看当前运行状态\n/stop  # 停止任务（非超级管理员只能停止自己触发的任务）\n/help"
            else:
                if not lines:
                    msg = "当前无可运行任务权限。请联系管理员分配权限。"
                else:
                    msg = "可用任务命令：\n" + "\n".join(lines)
                if self._can(role, group, "stop"):
                    msg += "\n/stop  # 停止自己触发的任务"

            self._reply(token, ctx.chat_id, msg)
            return

        if cmd == "/status":
            if not self._can(role, group, "status"):
                self._reply(token, ctx.chat_id, "无权限：status")
                return
            msg = self._on_status()
            self._reply(token, ctx.chat_id, msg)
            return

        if cmd == "/stop":
            if not self._can(role, group, "stop"):
                self._reply(token, ctx.chat_id, "无权限：stop")
                return
            self._on_stop(ctx.chat_id, ctx.username)
            self._reply(token, ctx.chat_id, "已发送停止请求")
            return

        # Direct task commands (tap-to-run): /<tg_command>
        ts = load_task_settings()
        tasks = list(getattr(ts, "tasks", []) or [])
        tasks.sort(key=lambda t: (int(getattr(t, "sort_order", 0) or 0), (t.tg_command or "").lower()))
        cmd_key = cmd.lstrip("/")
        hit = next((t for t in tasks if (t.tg_command or "").strip().lower() == cmd_key), None)
        if hit is not None:
            if not self._can(role, group, "run", task_id=str(hit.id)):
                self._reply(token, ctx.chat_id, f"无权限：/{cmd_key}")
                return
            ok, msg = self._on_run(str(hit.id), ctx.chat_id, ctx.username)
            self._reply(token, ctx.chat_id, msg if msg else (f"收到，开始执行：{(hit.tg_desc or hit.tg_command)}" if ok else "执行失败"))
            return

        if cmd == "/run":
            # Back-compat helper: /run <tg_command>
            ts = load_task_settings()
            tasks = list(getattr(ts, "tasks", []) or [])
            tasks.sort(key=lambda t: (int(getattr(t, "sort_order", 0) or 0), (t.tg_command or "").lower()))

            if len(parts) < 2:
                self._reply(token, ctx.chat_id, "请直接点击任务命令执行：\n发 /help 查看")
                return

            key = parts[1].strip().lstrip("/").lower()
            hit = next((t for t in tasks if (t.tg_command or "").strip().lower() == key), None)
            if not hit:
                self._reply(token, ctx.chat_id, f"未知任务：{key}")
                return
            if not self._can(role, group, "run", task_id=str(hit.id)):
                self._reply(token, ctx.chat_id, f"无权限：run {key}")
                return

            ok, msg = self._on_run(str(hit.id), ctx.chat_id, ctx.username)
            self._reply(token, ctx.chat_id, msg if msg else (f"收到，开始执行：{(hit.tg_desc or hit.tg_command)}" if ok else "执行失败"))
            return

        self._reply(token, ctx.chat_id, f"未知命令：{cmd}，发 /help 查看")

    def _run_loop(self) -> None:
        self._write_state(state="启动中", last_poll="-", last_error="-")
        while not self._stop.is_set():
            s = load_ui_settings()
            if not s.telegram_control_enabled:
                self._write_state(state="未启用", last_poll="-", last_error="-")
                time.sleep(1.0)
                continue

            token = self._bot_token()
            if not token:
                time.sleep(2.0)
                continue

            # Make sure webhook is not set (getUpdates will 409 if webhook is active)
            if getattr(self, "_webhook_cleared", False) is False:
                self._delete_webhook(token)
                self._webhook_cleared = True

            try:
                data = self._get_updates(token, timeout=20)
                self._write_state(state="运行中", last_poll=time.strftime('%Y-%m-%d %H:%M:%S'), last_error="-")
                items = data.get("result") or []
                last_id: int | None = None

                for u in items:
                    last_id = u.get("update_id")
                    msg = u.get("message") or {}
                    chat = msg.get("chat") or {}
                    chat_id = str(chat.get("id") or "")
                    if not chat_id:
                        continue
                    frm = msg.get("from") or {}
                    username = frm.get("username")
                    text = msg.get("text") or ""

                    role, group = self._resolve_acl(chat_id, username)
                    if role == "none":
                        continue

                    ctx = TgCommandContext(chat_id=chat_id, username=username, text=text)
                    self._handle(token, ctx, role=role, group=group)

                if last_id is not None:
                    self._update_offset = int(last_id) + 1
                    self._save_offset(self._update_offset)

            except Exception as e:
                msg = str(e)
                self._log(f"{time.strftime('%Y-%m-%d %H:%M:%S')} tg_control error: {msg}")
                self._write_state(state="错误", last_poll=time.strftime('%Y-%m-%d %H:%M:%S'), last_error=msg)

                # 409 can happen if webhook is set or another poller is active.
                if "409" in msg or "Conflict" in msg:
                    self._delete_webhook(token)
                    time.sleep(5.0)
                else:
                    time.sleep(2.0)
