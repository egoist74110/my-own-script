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
from app_ado.store import config_dir, load_ui_settings


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
        on_run: Callable[[str], None],
        on_stop: Callable[[], None],
        on_status: Callable[[], str],
    ) -> None:
        self._on_run = on_run
        self._on_stop = on_stop
        self._on_status = on_status

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._offset_path = config_dir() / "tg_offset.json"
        self._update_offset = self._load_offset()

    def _load_offset(self) -> int | None:
        try:
            if self._offset_path.exists():
                j = json.loads(self._offset_path.read_text("utf-8"))
                v = j.get("last_update_id")
                return int(v) if v is not None else None
        except Exception:
            return None
        return None

    def _save_offset(self, last_update_id: int) -> None:
        try:
            self._offset_path.parent.mkdir(parents=True, exist_ok=True)
            self._offset_path.write_text(json.dumps({"last_update_id": last_update_id}, indent=2), "utf-8")
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

    def _allowed(self, chat_id: str, username: str | None) -> bool:
        s = load_ui_settings()
        # main chat id always allowed
        if s.telegram_chat_id and str(chat_id) == str(s.telegram_chat_id):
            return True
        # whitelist ids or @username
        wl = set(str(x).strip() for x in (s.telegram_whitelist or []) if str(x).strip())
        if str(chat_id) in wl:
            return True
        if username and ("@" + username) in wl:
            return True
        return False

    def _bot_token(self) -> str | None:
        return get_telegram_token()

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

    def _handle(self, token: str, ctx: TgCommandContext) -> None:
        t = (ctx.text or "").strip()
        if not t.startswith("/"):
            return

        parts = t.split()
        cmd = parts[0].lower()

        if cmd in ("/help", "/start"):
            self._reply(
                token,
                ctx.chat_id,
                "可用命令：\n"
                "/run sync_build_release\n"
                "/run sync_merge_build_release\n"
                "/status\n"
                "/stop",
            )
            return

        if cmd == "/status":
            msg = self._on_status()
            self._reply(token, ctx.chat_id, msg)
            return

        if cmd == "/stop":
            self._on_stop()
            self._reply(token, ctx.chat_id, "已发送停止请求")
            return

        if cmd == "/run":
            if len(parts) < 2:
                self._reply(token, ctx.chat_id, "用法：/run sync_build_release 或 /run sync_merge_build_release")
                return
            task_id = parts[1].strip()
            if task_id not in ("sync_build_release", "sync_merge_build_release"):
                self._reply(token, ctx.chat_id, f"未知任务：{task_id}")
                return
            self._on_run(task_id)
            self._reply(token, ctx.chat_id, f"收到，开始执行：{task_id}")
            return

        self._reply(token, ctx.chat_id, f"未知命令：{cmd}，发 /help 查看")

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            s = load_ui_settings()
            if not s.telegram_control_enabled:
                time.sleep(1.0)
                continue

            token = self._bot_token()
            if not token:
                time.sleep(2.0)
                continue

            try:
                data = self._get_updates(token, timeout=20)
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

                    if not self._allowed(chat_id, username):
                        continue

                    ctx = TgCommandContext(chat_id=chat_id, username=username, text=text)
                    self._handle(token, ctx)

                if last_id is not None:
                    self._update_offset = int(last_id) + 1
                    self._save_offset(int(last_id))

            except Exception:
                # avoid noisy loop
                time.sleep(2.0)
