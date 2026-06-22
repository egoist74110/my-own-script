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
from app_ado.store import config_dir, load_ui_settings, load_task_settings, save_ui_settings


@dataclass
class TgCommandContext:
    chat_id: str
    username: str | None
    text: str
    # AI 开发模块：reply-to 的目标消息 id（如有），用于路由到具体会话
    reply_to_msg_id: int | None = None


class TelegramController:
    """Poll Telegram updates and trigger app actions.

    Designed for: app running -> polling thread active.

    Note: Telegram long-polling may legitimately time out or disconnect.
    We treat occasional timeouts as normal noise and only surface problems
    when they repeat.
    """

    def __init__(
        self,
        *,
        on_run: Callable[[str, str, str | None], tuple[bool, str]],
        on_deploy_only: Callable[[str, str, str | None], tuple[bool, str]],
        on_rollback: Callable[[str, int, str, str | None], tuple[bool, str]],
        on_stop_menu: Callable[[str, str | None], list[tuple[str, str]]],
        on_stop_one: Callable[[str, str, str | None], tuple[bool, str]],
        on_status: Callable[[], str],
        wi_bridge: Any = None,
        headless_bridge: Any = None,
        token_fn: Callable[[], str | None] | None = None,
        mode: str = "main",
        name: str = "",
    ) -> None:
        self._on_run = on_run
        self._on_deploy_only = on_deploy_only
        self._on_rollback = on_rollback
        self._on_stop_menu = on_stop_menu
        self._on_stop_one = on_stop_one
        self._on_status = on_status
        # 工单模块的 TG 桥（可选，owner-only）；不传则禁用 /wi 相关功能
        self._wi_bridge = wi_bridge
        # Claude headless 结构化会话桥（CC Pocket 式）；不传则禁用 /cc 相关功能
        self._headless_bridge = headless_bridge
        # 机器人 token 来源：默认主机器人；AI 专属机器人传各自的 token_fn。
        self._token_fn = token_fn or get_telegram_token
        # mode="main"：完整工具箱（任务/工单/服务/MCP），不含 AI 对话；
        # mode="ai"：只处理 Claude 会话（/cc、cc:* 回调、文字投递），任务等一律不出现。
        self._mode = mode

        self._rollback_wizard: dict[str, dict] = {}  # chat_id -> state

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        # 多机器人各自独立的轮询 offset / 状态 / 日志文件，避免互相覆盖。
        suffix = f"_{name}" if name else ""
        self._offset_path = config_dir() / f"tg_offset{suffix}.json"
        self._log_path = config_dir() / f"tg_control{suffix}.log"
        self._state_path = config_dir() / f"tg_control_state{suffix}.json"
        self._update_offset = self._load_offset()

        # health tracking
        self._consecutive_errors: int = 0
        self._first_error_ts: float = 0.0
        self._last_error_ts: float = 0.0
        self._last_alert_ts: float = 0.0

    def _answer_callback(self, token: str, callback_query_id: str, *, text: str = "") -> None:
        try:
            url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
            payload = {"callback_query_id": callback_query_id}
            if text:
                payload["text"] = text
            with httpx.Client(timeout=httpx.Timeout(8.0, connect=5.0), follow_redirects=False) as c:
                c.post(url, data=payload)
        except Exception:
            return

    def _strip_inline_keyboard(self, token: str, chat_id: str, message_id: int) -> None:
        """点完一次性按钮（如审批 ✅/❌）后，去掉那条消息的按钮，避免重复点。"""
        try:
            url = f"https://api.telegram.org/bot{token}/editMessageReplyMarkup"
            payload = {"chat_id": str(chat_id), "message_id": int(message_id),
                       "reply_markup": {"inline_keyboard": []}}
            with httpx.Client(timeout=httpx.Timeout(8.0, connect=5.0)) as c:
                c.post(url, json=payload)
        except Exception:
            return

    def _handle_rollback_pick_task(self, token: str, ctx: TgCommandContext, *, role: str, group: dict | None, task_id: str) -> None:
        ts = load_task_settings()
        tasks = list(getattr(ts, "tasks", []) or [])
        tasks.sort(key=lambda x: (int(getattr(x, "sort_order", 0) or 0), (x.tg_command or "").lower()))
        hit = next((x for x in tasks if str(x.id) == str(task_id)), None)
        if not hit:
            self._reply(token, ctx.chat_id, "任务不存在，请重新发 /rollback")
            self._rollback_wizard.pop(str(ctx.chat_id), None)
            return
        if not self._can(role, group, "rollback", task_id=str(hit.id)):
            self._reply(token, ctx.chat_id, "无权限：rollback")
            self._rollback_wizard.pop(str(ctx.chat_id), None)
            return

        # build offset options by querying ADO releases
        try:
            from datetime import datetime, timezone

            from app_ado.store import load_ui_settings
            from app_ado.secrets import get_pat
            from app_ado.ado_release_http import list_recent_releases
            from app_ado.tg_rollback_inline import offset_buttons

            ui = load_ui_settings()
            proj = next((p for p in ui.projects if p.id == hit.project_id), None)
            if not proj:
                raise RuntimeError("找不到项目配置（project_id）")
            lib = next((l for l in ui.libraries if l.id == proj.library_id), None)
            if not lib:
                raise RuntimeError("项目未关联代码库")
            pat = get_pat(lib.id)
            if not pat:
                raise RuntimeError("未找到 PAT")

            targets = list(hit.targets or [])
            if not targets:
                raise RuntimeError("任务未配置发布目标")

            def fmt_time(iso: str | None) -> str:
                if not iso:
                    return ""
                s = str(iso).strip()
                try:
                    if s.endswith("Z"):
                        s2 = s[:-1] + "+00:00"
                    else:
                        s2 = s
                    dt = datetime.fromisoformat(s2)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    local = dt.astimezone()
                    return local.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    return s

            per_target: list[tuple[str, list]] = []
            for tgt in targets:
                if not tgt.release_id:
                    raise RuntimeError(f"发布目标未配置 release_id：{tgt.name}")
                try:
                    rels = list_recent_releases(lib.base_url, proj.collection, proj.project, str(tgt.release_id), pat=pat, top=6, api_version="6.0")
                except Exception:
                    rels = list_recent_releases(lib.base_url, proj.collection, proj.project, str(tgt.release_id), pat=pat, top=6, api_version="7.0")
                per_target.append((tgt.name, rels))

            max_offset = 5
            for _, rels in per_target:
                max_offset = min(max_offset, max(0, len(rels) - 1))
            if max_offset <= 0:
                raise RuntimeError("Release 历史不足（需要至少 2 个 Release 才能回退）")

            label = (hit.tg_desc or "").strip() or ("/" + (hit.tg_command or "").strip())
            lines = [f"请选择回退版本 offset（1~{max_offset}，1=上一个）："]
            for k in range(1, max_offset + 1):
                lines.append(f"\noffset={k}:")
                for tgt_name, rels in per_target:
                    r = rels[k]
                    ts2 = fmt_time(r.created_on)
                    lines.append(f"- {tgt_name}: {r.name or r.id}" + (f" ({ts2})" if ts2 else ""))

            wiz = self._rollback_wizard.get(str(ctx.chat_id)) or {}
            wiz["task_id"] = str(hit.id)
            wiz["task_label"] = label
            wiz["max_offset"] = int(max_offset)
            wiz["step"] = "pick_offset"
            self._rollback_wizard[str(ctx.chat_id)] = wiz

            self._reply(token, ctx.chat_id, "\n".join(lines), reply_markup=offset_buttons(int(max_offset)))
            return
        except Exception as ex:
            self._reply(token, ctx.chat_id, "无法获取回退版本：" + str(ex))
            self._rollback_wizard.pop(str(ctx.chat_id), None)
            return

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
        owner_chat = str(s.telegram_chat_id or "").strip()
        if not owner_chat:
            # 还没绑定 owner：第一个私聊机器人的人自动成为 owner（对齐「只填 Token」的配置方式，
            # 不再手填 Chat ID）。群聊 id 是负数，不让群抢 owner。
            cid = str(chat_id).strip()
            if cid and not cid.startswith("-"):
                s.telegram_chat_id = cid
                save_ui_settings(s)
                return "owner", None
        elif str(chat_id) == owner_chat:
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
        if action == "stop":
            return bool(group.get("can_stop"))
        if action in ("run", "rollback"):
            flag = "can_run" if action == "run" else "can_rollback"
            if not bool(group.get(flag)):
                return False
            if task_id is None:
                return False
            return str(task_id) in [str(x) for x in (group.get("task_ids") or [])]
        return False

    def _bot_token(self) -> str | None:
        try:
            return self._token_fn()
        except Exception:
            return None

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
            "allowed_updates": json.dumps(["message", "callback_query"], ensure_ascii=False),
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

    def _reply(self, token: str, chat_id: str, text: str, *, reply_markup: dict | None = None) -> None:
        send_telegram_message(bot_token=token, chat_id=chat_id, text=text, reply_markup=reply_markup)

    def _reply_photo(self, token: str, chat_id: str, photo: bytes, *, caption: str | None = None) -> None:
        from app_ado.notifier_telegram import send_telegram_photo

        send_telegram_photo(bot_token=token, chat_id=chat_id, photo=photo, caption=caption)

    def _reply_media_group(
        self,
        token: str,
        chat_id: str,
        photos: list[tuple[str, bytes, str]],
    ) -> None:
        """photos = [(filename, bytes, content_type), ...]。

        - 0 张：直接返回。
        - 1 张：退回 sendPhoto。
        - 2-10 张：一次 sendMediaGroup。
        - >10：按 10 张一组拆开发。
        失败静默吞掉（避免一张坏图把整个 view 流程拖死）。
        """
        if not photos:
            return
        if len(photos) == 1:
            try:
                self._reply_photo(token, chat_id, photos[0][1])
            except Exception:
                pass
            return
        url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
        for i in range(0, len(photos), 10):
            group = photos[i:i + 10]
            media: list[dict[str, Any]] = []
            files: dict[str, tuple[str, bytes, str]] = {}
            for j, (name, blob, ct) in enumerate(group):
                key = f"photo{j}"
                media.append({"type": "photo", "media": f"attach://{key}"})
                files[key] = (name, blob, ct or "image/png")
            data = {"chat_id": str(chat_id), "media": json.dumps(media, ensure_ascii=False)}
            try:
                with httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0), follow_redirects=False) as c:
                    c.post(url, data=data, files=files)
            except Exception:
                continue

    # ---------- AI 专属机器人（mode="ai"）：只处理 Claude 会话 ----------

    def _handle_ai_callback(
        self, token: str, cb: dict, chat_id: str, data: str, role: str, group: dict | None
    ) -> None:
        """AI 机器人的 inline 回调：只认 cc:* / cc，其它忽略。"""
        if self._headless_bridge is None:
            return
        if not (data == "cc" or data.startswith("cc:")):
            return
        cc_data = data if data.startswith("cc:") else "cc:menu"
        txt, mk = self._headless_bridge.handle_callback(cc_data, chat_id, role, group)
        # 审批 ✅/❌ 一次性：点完去掉原消息按钮
        if cc_data.startswith("cc:appr:"):
            mid = (cb.get("message") or {}).get("message_id")
            if mid is not None:
                self._strip_inline_keyboard(token, chat_id, mid)
        if txt:
            self._reply(token, chat_id, txt, reply_markup=mk)

    def _handle_ai(self, token: str, ctx: TgCommandContext, *, role: str, group: dict | None) -> None:
        """AI 机器人的消息处理：向导文字 / 投递给聚焦会话 / Claude 会话菜单。

        任务、工单、服务、回退等一律不在这个机器人里出现（避免任务和 AI 对话打架）。
        """
        if self._headless_bridge is None:
            return
        t = (ctx.text or "").strip()

        # 建会话向导的文字输入（手输路径可能以 / 开头，必须在命令解析前拦下）
        if t and self._headless_bridge.wizard_expects_text(ctx.chat_id):
            looks_like_input = (not t.startswith("/")) or t.startswith("~") or ("/" in t[1:])
            if looks_like_input:
                txt, mk = self._headless_bridge.handle_wizard_text(ctx.chat_id, ctx.text or "", role, group)
                if txt:
                    self._reply(token, ctx.chat_id, txt, reply_markup=mk)
                return

        # 非 / 文字 → 投给当前聚焦会话；没有聚焦会话则打开会话菜单
        if t and not t.startswith("/"):
            if self._headless_bridge.should_consume_text(ctx.chat_id, ctx.reply_to_msg_id):
                _ok, msg = self._headless_bridge.handle_text(
                    text=ctx.text or "",
                    chat_id=ctx.chat_id,
                    reply_to_msg_id=ctx.reply_to_msg_id,
                    role=role,
                    group=group,
                )
                if msg:
                    self._reply(token, ctx.chat_id, msg)
            else:
                txt, mk = self._headless_bridge.handle_menu(ctx.chat_id, role, group)
                self._reply(token, ctx.chat_id, txt or "🤖 Claude 会话", reply_markup=mk)
            return

        if not t.startswith("/"):
            return
        cmd = t.split()[0].lower()
        if cmd in ("/start", "/help", "/cc", "/menu"):
            txt, mk = self._headless_bridge.handle_menu(ctx.chat_id, role, group)
            if txt:
                self._reply(token, ctx.chat_id, txt, reply_markup=mk)
        # 其它命令在 AI 机器人里不处理

    def _handle(self, token: str, ctx: TgCommandContext, *, role: str, group: dict | None) -> None:
        t = (ctx.text or "").strip()

        # Claude headless 向导文字输入：手输路径可能以 / 开头（绝对路径），会被 TG 当命令，
        # 必须在命令解析之前拦下。仅当输入「像路径/关键字」时拦截，保留 /help、/cc 等真命令逃生。
        if (self._headless_bridge is not None and t
                and not self._rollback_wizard.get(str(ctx.chat_id))
                and self._headless_bridge.wizard_expects_text(ctx.chat_id)):
            looks_like_input = (not t.startswith("/")) or t.startswith("~") or ("/" in t[1:])
            if looks_like_input:
                txt, mk = self._headless_bridge.handle_wizard_text(
                    ctx.chat_id, ctx.text or "", role, group
                )
                if txt:
                    self._reply(token, ctx.chat_id, txt, reply_markup=mk)
                return

        # Claude headless 会话：非 / 文字消息 → 给当前聚焦会话发提示词
        if self._headless_bridge is not None and t and not t.startswith("/"):
            if not self._rollback_wizard.get(str(ctx.chat_id)):
                if self._headless_bridge.should_consume_text(ctx.chat_id, ctx.reply_to_msg_id):
                    ok, msg = self._headless_bridge.handle_text(
                        text=ctx.text or "",
                        chat_id=ctx.chat_id,
                        reply_to_msg_id=ctx.reply_to_msg_id,
                        role=role,
                        group=group,
                    )
                    if msg:
                        self._reply(token, ctx.chat_id, msg)
                    return

        # rollback wizard (multi-step) can accept non-slash replies
        wiz = self._rollback_wizard.get(str(ctx.chat_id))
        if wiz and not t.startswith("/"):
            step = wiz.get("step")
            ts = load_task_settings()
            tasks = list(getattr(ts, "tasks", []) or [])
            tasks.sort(key=lambda x: (int(getattr(x, "sort_order", 0) or 0), (x.tg_command or "").lower()))

            if step == "pick_task":
                try:
                    idx = int(t.strip())
                except Exception:
                    self._reply(token, ctx.chat_id, "请输入序号（数字）。或发送 /cancelrollback 取消。")
                    return
                options = wiz.get("options") or []
                if idx < 1 or idx > len(options):
                    self._reply(token, ctx.chat_id, "序号超出范围。或发送 /cancelrollback 取消。")
                    return
                task_id = str(options[idx - 1]["task_id"])
                hit = next((x for x in tasks if str(x.id) == task_id), None)
                if not hit:
                    self._reply(token, ctx.chat_id, "任务不存在，请重新发 /rollback")
                    self._rollback_wizard.pop(str(ctx.chat_id), None)
                    return
                if not self._can(role, group, "rollback", task_id=str(hit.id)):
                    self._reply(token, ctx.chat_id, "无权限：rollback")
                    self._rollback_wizard.pop(str(ctx.chat_id), None)
                    return

                # For text-based flow, just ask user to use button or /rollback again.
                self._reply(token, ctx.chat_id, "请使用 /rollback 的按钮选择任务（或重新发送 /rollback）。")
                self._rollback_wizard.pop(str(ctx.chat_id), None)
                return

            if step == "pick_offset":
                try:
                    off = int(t.strip())
                except Exception:
                    self._reply(token, ctx.chat_id, "请输入回退 offset（数字）。或发送 /cancelrollback 取消。")
                    return
                max_off = int(wiz.get("max_offset") or 0)
                if max_off and (off < 1 or off > max_off):
                    self._reply(token, ctx.chat_id, f"offset 超出范围（1~{max_off}）。或发送 /cancelrollback 取消。")
                    return
                wiz["offset"] = off
                wiz["step"] = "confirm"
                self._rollback_wizard[str(ctx.chat_id)] = wiz
                self._reply(token, ctx.chat_id, f"确认回退？\n任务：{wiz.get('task_label') or wiz.get('task_id')}\noffset={off}\n\n回复 y 确认，n 取消")
                return

            if step == "confirm":
                yn = t.strip().lower()
                if yn in ("n", "no", "cancel"):
                    self._rollback_wizard.pop(str(ctx.chat_id), None)
                    self._reply(token, ctx.chat_id, "已取消回退")
                    return
                if yn not in ("y", "yes"):
                    self._reply(token, ctx.chat_id, "请回复 y 或 n。")
                    return
                task_id = str(wiz.get("task_id") or "")
                off = int(wiz.get("offset") or 0)
                self._rollback_wizard.pop(str(ctx.chat_id), None)
                ok, msg = self._on_rollback(task_id, off, ctx.chat_id, ctx.username)
                self._reply(token, ctx.chat_id, msg)
                return

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

            # Prefer inline buttons for a cleaner UX (no need to type commands)
            try:
                from app_ado.tg_help_inline import top_menu

                items: list[tuple[str, str]] = []
                if role == "owner":
                    allowed_tasks = [t for t in tasks if (t.tg_command or "").strip()]
                else:
                    allowed_tasks = [t for t in tasks if (t.tg_command or "").strip() and self._can(role, group, "run", task_id=str(t.id))]

                for t in allowed_tasks:
                    label = (t.tg_desc or "").strip() or ("/" + (t.tg_command or "").strip())
                    items.append((str(t.id), label))

                show_stop = (role == "owner") or self._can(role, group, "stop")
                show_status = (role == "owner") or self._can(role, group, "status")
                show_rollback = (role == "owner") or any(self._can(role, group, "rollback", task_id=str(t.id)) for t in tasks)

                # Telegram does not allow empty text. Use an "invisible" placeholder char.
                show_dev = (role == "owner") and (self._headless_bridge is not None)
                show_wi = (role == "owner") and (self._wi_bridge is not None)
                show_svc = (role == "owner")
                show_mcp = (role == "owner")
                self._reply(
                    token,
                    ctx.chat_id,
                    "代码工具箱",
                    reply_markup=top_menu(show_dev=show_dev, show_wi=show_wi, show_svc=show_svc, show_mcp=show_mcp),
                )
                return
            except Exception as e:
                # log why inline help failed, then fall back
                try:
                    self._log(f"{time.strftime('%Y-%m-%d %H:%M:%S')} help inline failed: {e}")
                    self._write_state(state="运行中", last_poll=time.strftime('%Y-%m-%d %H:%M:%S'), last_error=str(e))
                except Exception:
                    pass
                # fallback to text list
                if role == "owner":
                    msg = "可用命令（点击即可执行）：\n" + ("\n".join(lines) if lines else "（暂无任务）")
                    msg += "\n/status  # 查看当前运行状态\n/stop  # 停止任务（非超级管理员只能停止自己触发的任务）\n/rollback  # 回退发布版本（交互式）\n/help"
                else:
                    if not lines:
                        msg = "当前无可运行任务权限。请联系管理员分配权限。"
                    else:
                        msg = "可用任务命令：\n" + "\n".join(lines)
                    if self._can(role, group, "stop"):
                        msg += "\n/stop  # 停止自己触发的任务"
                    if any(self._can(role, group, "rollback", task_id=str(t.id)) for t in tasks):
                        msg += "\n/rollback  # 回退发布版本（交互式）"

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
            items = self._on_stop_menu(ctx.chat_id, ctx.username)
            if not items:
                self._reply(token, ctx.chat_id, "当前没有可停止的任务")
                return
            from app_ado.tg_stop_inline import stop_task_buttons

            self._reply(token, ctx.chat_id, "请选择要停止的任务：", reply_markup=stop_task_buttons(items))
            return

        if cmd == "/cancelrollback":
            if str(ctx.chat_id) in self._rollback_wizard:
                self._rollback_wizard.pop(str(ctx.chat_id), None)
                self._reply(token, ctx.chat_id, "已取消回退流程")
            else:
                self._reply(token, ctx.chat_id, "当前没有进行中的回退流程")
            return

        if cmd == "/rollback":
            ts = load_task_settings()
            tasks = list(getattr(ts, "tasks", []) or [])
            tasks.sort(key=lambda t: (int(getattr(t, "sort_order", 0) or 0), (t.tg_command or "").lower()))

            items: list[tuple[str, str]] = []
            for tsk in tasks:
                if not (tsk.tg_command or "").strip():
                    continue
                if not self._can(role, group, "rollback", task_id=str(tsk.id)):
                    continue
                label = (tsk.tg_desc or "").strip() or ("/" + (tsk.tg_command or "").strip())
                items.append((str(tsk.id), label))

            if not items:
                self._reply(token, ctx.chat_id, "无可回退任务权限。请联系管理员分配权限。")
                return

            from app_ado.tg_rollback_inline import task_buttons

            self._rollback_wizard[str(ctx.chat_id)] = {"step": "pick_task"}
            self._reply(token, ctx.chat_id, "请选择要回退的任务：", reply_markup=task_buttons(items))
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

        # Claude headless 会话（CC Pocket 式）：/cc 打开会话菜单
        if self._headless_bridge is not None and cmd == "/cc":
            txt, mk = self._headless_bridge.handle_menu(ctx.chat_id, role, group)
            if txt:
                self._reply(token, ctx.chat_id, txt, reply_markup=mk)
            return

        # 工单：/wi [<id>]（owner-only）
        if self._wi_bridge is not None and cmd == "/wi":
            if not self._wi_bridge.can_use(role, group):
                self._reply(token, ctx.chat_id, "无权限：工单")
                return
            if len(parts) >= 2:
                raw = parts[1].strip().lstrip("#")
                try:
                    wid = int(raw)
                except ValueError:
                    text, markup = self._wi_bridge.handle_main(ctx.chat_id)
                    self._reply(token, ctx.chat_id, text, reply_markup=markup)
                    return
                text, markup = self._wi_bridge.handle_open(ctx.chat_id, wid)
                self._reply(token, ctx.chat_id, text, reply_markup=markup)
                return
            text, markup = self._wi_bridge.handle_main(ctx.chat_id)
            self._reply(token, ctx.chat_id, text, reply_markup=markup)
            return

        # VPN：/vpn [on|status|off]（owner-only）——配了 Ente 种子则全自动登录连接
        if cmd == "/vpn":
            if role != "owner":
                self._reply(token, ctx.chat_id, "无权限：vpn")
                return
            sub = parts[1].lower() if len(parts) >= 2 else "status"
            if sub in ("status", "st"):
                self._reply(token, ctx.chat_id, self._vpn_status_text())
            elif sub in ("on", "connect", "login"):
                self._vpn_connect_async(token, ctx.chat_id)
            elif sub in ("off", "disconnect"):
                self._reply(token, ctx.chat_id, self._vpn_off_text())
            else:
                self._reply(token, ctx.chat_id, "用法：/vpn [on|status|off]")
            return

        self._reply(token, ctx.chat_id, f"未知命令：{cmd}，发 /help 查看")

    # ---------------- VPN 远程控制 ----------------

    def _vpn_status_text(self) -> str:
        from app_ado.vpn_control import status
        from app_ado.vpn_totp import has_secret

        st = status()
        if st["connected"]:
            app = "在跑" if st["app_running"] else "没跑（隧道仍由后台 helper 维持）"
            return f"🟢 VPN 已连接\nIP：{st['ip']}\napp：{app}"
        seed = "已配置" if has_secret() else "未配置 ⚠️ 无法自动登录"
        app = "在跑" if st["app_running"] else "没跑"
        return (
            "🔴 VPN 未连接\n"
            f"app：{app}\nEnte 种子：{seed}\n\n发 /vpn on 自动登录并连接"
        )

    def _vpn_connect_async(self, token: str, chat_id: str) -> None:
        """后台线程跑自愈阶梯 + 自动登录（login_flow 要 1-2 分钟，不能阻塞轮询线程）。"""
        from app_ado.vpn_control import status
        from app_ado.vpn_totp import has_secret

        st = status()
        if st["connected"]:
            self._reply(token, chat_id, f"🟢 已经连着了：{st['ip']}")
            return
        if not has_secret():
            self._reply(
                token, chat_id,
                "⚠️ 没配 Ente 种子，无法远程自动登录。\n请先在电脑端 App 服务页导入 Ente 种子。",
            )
            return
        self._reply(token, chat_id, "🔄 正在连接 VPN…（自愈：重启/登录，约 1–2 分钟，完成通知你）")

        def work() -> None:
            from app_ado.vpn_control import ensure_connected
            from app_ado.vpn_control import status as status2

            lines: list[str] = []
            try:
                ok = ensure_connected(token_provider=lambda: None, log=lambda m: lines.append(m))
            except Exception as e:  # noqa: BLE001
                ok = False
                lines.append(f"异常：{e}")
            if ok:
                self._reply(token, chat_id, f"✅ VPN 已连上：{status2().get('ip')}")
            else:
                tail = "\n".join(lines[-6:]) or "（无日志）"
                self._reply(token, chat_id, f"❌ 连接失败\n\n最后日志：\n{tail}")

        threading.Thread(target=work, daemon=True).start()

    def _vpn_off_text(self) -> str:
        # 退 app 不会断隧道（root helper 维持）；远程彻底断开需 app 内 Disconnect 或 root。
        return (
            "⚠️ 远程断开暂不支持：Harmony 隧道由后台 root helper 维持，退 app 也不会断。"
            "如需断开请在电脑上的 Harmony app 里点 Disconnect。"
        )

    # ---------------- 工单：callback 分发 ----------------

    def _handle_svc_callback(self, token: str, chat_id: str, data: str) -> None:
        """服务面板回调（owner-only，调用方已校验权限）。

        data: svc / svc:vpn / svc:cs[:start|stop] / svc:cf[:start|stop]
        """
        from app_ado import services_panel as svc
        from app_ado.tg_help_inline import (
            services_menu,
            service_actions_menu,
            service_back_menu,
            vpn_actions_menu,
        )

        parts = data.split(":")
        if len(parts) == 1:  # "svc"
            self._reply(token, chat_id, "🧰 服务面板", reply_markup=services_menu())
            return

        key = parts[1]
        action = parts[2] if len(parts) > 2 else ""

        if key == "vpn":
            if action == "on":  # 点「连接」→ 后台自动登录连接
                self._vpn_connect_async(token, chat_id)
                return
            self._reply(token, chat_id, self._vpn_status_text(), reply_markup=vpn_actions_menu())
            return

        if key in ("cs", "cf"):
            starter = svc.codeserver_start if key == "cs" else svc.cloudflared_start
            stopper = svc.codeserver_stop if key == "cs" else svc.cloudflared_stop
            status = svc.codeserver_status if key == "cs" else svc.cloudflared_status

            head = ""
            if action == "start":
                _, head = starter()
            elif action == "stop":
                _, head = stopper()

            text = status()
            if head:
                text = f"{head}\n\n{text}"
            self._reply(token, chat_id, text, reply_markup=service_actions_menu(key))
            return

        # 未知子项，回服务面板
        self._reply(token, chat_id, "🧰 服务面板", reply_markup=services_menu())

    def _handle_wi_callback(self, token: str, chat_id: str, data: str) -> None:
        bridge = self._wi_bridge
        if bridge is None:
            return

        if data == "wi_noop":
            return

        if data == "wi_main":
            text, markup = bridge.handle_main(chat_id)
            self._reply(token, chat_id, text, reply_markup=markup)
            return

        if data == "wi_pp":
            text, markup = bridge.handle_pick_project(chat_id)
            self._reply(token, chat_id, text, reply_markup=markup)
            return

        if data.startswith("wi_psp:"):
            pid = data.split(":", 1)[1].strip()
            text, markup = bridge.handle_set_project(chat_id, pid)
            self._reply(token, chat_id, text, reply_markup=markup)
            return

        if data == "wi_pc":
            text, markup = bridge.handle_pick_column(chat_id)
            self._reply(token, chat_id, text, reply_markup=markup)
            return

        if data.startswith("wi_psc:"):
            try:
                idx = int(data.split(":", 1)[1].strip())
            except ValueError:
                return
            text, markup = bridge.handle_set_column(chat_id, idx)
            self._reply(token, chat_id, text, reply_markup=markup)
            return

        if data == "wi_rl":
            text, markup = bridge.handle_refresh(chat_id)
            self._reply(token, chat_id, text, reply_markup=markup)
            return

        if data.startswith("wi_l:"):
            try:
                page = int(data.split(":", 1)[1].strip())
            except ValueError:
                return
            text, markup = bridge.handle_list(chat_id, page)
            self._reply(token, chat_id, text, reply_markup=markup)
            return

        if data.startswith("wi_o:"):
            try:
                wid = int(data.split(":", 1)[1].strip())
            except ValueError:
                return
            text, markup = bridge.handle_open(chat_id, wid)
            self._reply(token, chat_id, text, reply_markup=markup)
            return

        if data.startswith("wi_ma:"):
            # 选 AI（命中 claude 时实际启动会话；其它 AI 暂未对接 TG，会礼貌报错）
            try:
                _, wid_s, repo_idx_s, ai_idx_s = data.split(":", 3)
                wid = int(wid_s)
                repo_idx = int(repo_idx_s)
                ai_idx = int(ai_idx_s)
            except ValueError:
                return
            text, markup = bridge.handle_mcp_pick_ai(chat_id, wid, repo_idx, ai_idx)
            if text is not None:
                self._reply(token, chat_id, text, reply_markup=markup)
            return

        if data.startswith("wi_mr:"):
            # 选仓库
            try:
                _, wid_s, idx_s = data.split(":", 2)
                wid = int(wid_s)
                repo_idx = int(idx_s)
            except ValueError:
                return
            text, markup = bridge.handle_mcp_pick_repo(chat_id, wid, repo_idx)
            self._reply(token, chat_id, text, reply_markup=markup)
            return

        if data.startswith("wi_m:"):
            # 启动 MCP 分析向导（先选仓库）
            try:
                wid = int(data.split(":", 1)[1].strip())
            except ValueError:
                return
            text, markup = bridge.handle_mcp_start(chat_id, wid)
            self._reply(token, chat_id, text, reply_markup=markup)
            return

        if data.startswith("wi_v:"):
            # 查看工单内容（文本 + 图片相册）
            try:
                wid = int(data.split(":", 1)[1].strip())
            except ValueError:
                return
            payload = bridge.handle_view(chat_id, wid)
            if payload.get("error"):
                self._reply(token, chat_id, str(payload["error"]),
                            reply_markup=payload.get("final_kb"))
                return
            chunks = list(payload.get("chunks") or [])
            photos = list(payload.get("photos") or [])
            final_kb = payload.get("final_kb")
            # 没图：kb 挂在最后一条文本上；有图：先发文 + 相册，再补一条带 kb 的尾巴
            if chunks:
                for i, chunk in enumerate(chunks):
                    last_text = (i == len(chunks) - 1)
                    rm = final_kb if (last_text and not photos) else None
                    self._reply(token, chat_id, chunk, reply_markup=rm)
            if photos:
                self._reply_media_group(token, chat_id, photos)
                self._reply(token, chat_id, f"—— 图片 {len(photos)} 张 ——", reply_markup=final_kb)
            return

        if data.startswith("wi_r:"):
            try:
                wid = int(data.split(":", 1)[1].strip())
            except ValueError:
                return
            text, markup = bridge.handle_related(chat_id, wid)
            self._reply(token, chat_id, text, reply_markup=markup)
            return

    # ---------------- MCP 配置：callback 分发 ----------------

    def _build_mcp_menu(self) -> dict:
        from app_ado.mcp_server_manager import is_ado_work_items_mcp_running
        from app_ado.tg_help_inline import mcp_menu
        from app_figma.mcp_server_manager import is_figma_mcp_running
        from app_figma.secrets import is_figma_configured
        from app_lark.mcp_server_manager import is_lark_logged_in, is_lark_mcp_running

        return mcp_menu(
            ado_running=is_ado_work_items_mcp_running(),
            lark_running=is_lark_mcp_running(),
            lark_logged_in=is_lark_logged_in(),
            figma_running=is_figma_mcp_running(),
            figma_configured=is_figma_configured(),
        )

    def _handle_mcp_callback(self, token: str, chat_id: str, data: str) -> None:
        """data 形态:mcp:<key>:<op>。点击 toggle → 切状态 + 重绘菜单。"""
        parts = data.split(":")
        key = parts[1] if len(parts) > 1 else ""

        if key == "ado":
            from app_ado.mcp_server_manager import (
                is_ado_work_items_mcp_running,
                start_ado_work_items_mcp,
                stop_ado_work_items_mcp,
            )
            if is_ado_work_items_mcp_running():
                ok, msg = stop_ado_work_items_mcp()
                text = f"工单 MCP 已关闭（{msg}）" if ok else f"关闭失败：{msg}"
            else:
                ok, msg = start_ado_work_items_mcp()
                text = f"工单 MCP 已开启（{msg}）" if ok else f"开启失败：{msg}"
            self._reply(token, chat_id, text, reply_markup=self._build_mcp_menu())
            return

        if key == "lark":
            from app_lark.mcp_server_manager import (
                is_lark_logged_in,
                is_lark_mcp_running,
                start_lark_mcp,
                stop_lark_mcp,
            )
            if is_lark_mcp_running():
                ok, msg = stop_lark_mcp()
                text = f"Lark MCP 已关闭（{msg}）" if ok else f"关闭失败：{msg}"
            elif not is_lark_logged_in():
                text = "Lark MCP 未登录。请到桌面端 MCP 配置 Tab,点 \"登录\" 完成 OAuth 授权后再开启。"
            else:
                ok, msg = start_lark_mcp()
                text = f"Lark MCP 已开启（{msg}）" if ok else f"开启失败：{msg}"
            self._reply(token, chat_id, text, reply_markup=self._build_mcp_menu())
            return

        if key == "larkinject":
            from app_lark.mcp_server_manager import is_lark_logged_in
            if not is_lark_logged_in():
                text = "未登录,无法注入。请先到桌面端登录 Lark。"
            else:
                from app_lark.lark_token_inject import inject_bearer_to_all_tools
                res = inject_bearer_to_all_tools()
                text = res.get("message") or "注入完成"
            self._reply(token, chat_id, text, reply_markup=self._build_mcp_menu())
            return

        if key == "figma":
            from app_figma.mcp_server_manager import (
                is_figma_mcp_running,
                start_figma_mcp,
                stop_figma_mcp,
            )
            from app_figma.secrets import is_figma_configured
            if is_figma_mcp_running():
                ok, msg = stop_figma_mcp()
                text = f"Figma MCP 已关闭（{msg}）" if ok else f"关闭失败：{msg}"
            elif not is_figma_configured():
                text = "Figma MCP 未配置。请到桌面端 MCP 配置 Tab,在 Figma MCP 卡里填写 Figma API Token 并保存后再开启。"
            else:
                ok, msg = start_figma_mcp()
                text = f"Figma MCP 已开启（{msg}）" if ok else f"开启失败：{msg}"
            self._reply(token, chat_id, text, reply_markup=self._build_mcp_menu())
            return

        self._reply(token, chat_id, "⚙️ MCP 配置", reply_markup=self._build_mcp_menu())

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
                # success -> reset health counters
                self._consecutive_errors = 0
                self._first_error_ts = 0.0
                self._write_state(state="运行中", last_poll=time.strftime('%Y-%m-%d %H:%M:%S'), last_error="-")
                items = data.get("result") or []
                last_id: int | None = None

                for u in items:
                    last_id = u.get("update_id")

                    # callback_query (inline buttons)
                    cb = u.get("callback_query")
                    if cb:
                        cb_id = str(cb.get("id") or "")
                        data2 = str(cb.get("data") or "")
                        msg2 = cb.get("message") or {}
                        chat2 = msg2.get("chat") or {}
                        chat_id2 = str(chat2.get("id") or "")
                        frm2 = cb.get("from") or {}
                        username2 = frm2.get("username")
                        if cb_id:
                            self._answer_callback(token, cb_id)
                        if chat_id2 and data2:
                            role2, group2 = self._resolve_acl(chat_id2, username2)
                            if role2 == "none":
                                continue
                            ctx2 = TgCommandContext(chat_id=chat_id2, username=username2, text=data2)

                            if data2 == "help_noop":
                                continue

                            # AI 专属机器人：只认 Claude 会话（cc:*）回调，其它一概不处理。
                            if self._mode == "ai":
                                self._handle_ai_callback(token, cb, chat_id2, data2, role2, group2)
                                continue

                            # 服务面板：svc / svc:vpn / svc:cs[:start|stop] / svc:cf[:start|stop]，仅 owner
                            if data2 == "svc" or data2.startswith("svc:"):
                                if role2 != "owner":
                                    self._reply(token, chat_id2, "无权限")
                                    continue
                                self._handle_svc_callback(token, chat_id2, data2)
                                continue

                            # Claude headless 会话（CC Pocket 式）：所有 cc:* 回调
                            if self._headless_bridge is not None and (data2 == "cc" or data2.startswith("cc:")):
                                cc_data = data2 if data2.startswith("cc:") else "cc:menu"
                                txt, mk = self._headless_bridge.handle_callback(
                                    cc_data, chat_id2, role2, group2
                                )
                                # 审批 ✅/❌ 是一次性的：点完把原消息的按钮去掉
                                if cc_data.startswith("cc:appr:"):
                                    mid2 = (cb.get("message") or {}).get("message_id")
                                    if mid2 is not None:
                                        self._strip_inline_keyboard(token, chat_id2, mid2)
                                if txt:
                                    self._reply(token, chat_id2, txt, reply_markup=mk)
                                continue

                            # 工单：所有 wi_* callback 走 owner-only 桥
                            if self._wi_bridge is not None and (data2 == "wi_main" or data2.startswith("wi_")):
                                if not self._wi_bridge.can_use(role2, group2):
                                    self._reply(token, chat_id2, "无权限：工单")
                                    continue
                                self._handle_wi_callback(token, chat_id2, data2)
                                continue

                            if data2.startswith("help_menu:"):
                                op = data2.split(":", 1)[1]

                                ts3 = load_task_settings()
                                tasks3 = list(getattr(ts3, "tasks", []) or [])
                                tasks3.sort(key=lambda t: (int(getattr(t, "sort_order", 0) or 0), (t.tg_command or "").lower()))

                                from app_ado.tg_help_inline import top_menu, tasks_menu, sys_menu

                                # allowed task buttons
                                if role2 == "owner":
                                    allowed = [t for t in tasks3 if (t.tg_command or "").strip()]
                                else:
                                    allowed = [t for t in tasks3 if (t.tg_command or "").strip() and self._can(role2, group2, "run", task_id=str(t.id))]

                                items2: list[tuple[str, str]] = []
                                for t in allowed:
                                    label = (t.tg_desc or "").strip() or ("/" + (t.tg_command or "").strip())
                                    items2.append((str(t.id), label))

                                show_stop2 = (role2 == "owner") or self._can(role2, group2, "stop")
                                show_status2 = (role2 == "owner") or self._can(role2, group2, "status")
                                show_rollback2 = (role2 == "owner") or any(self._can(role2, group2, "rollback", task_id=str(t.id)) for t in tasks3)

                                if op == "tasks":
                                    self._reply(token, chat_id2, "代码工具箱", reply_markup=tasks_menu(items2))
                                    continue
                                if op == "sys":
                                    self._reply(token, chat_id2, "代码工具箱", reply_markup=sys_menu(show_rollback=show_rollback2, show_stop=show_stop2, show_status=show_status2))
                                    continue
                                if op == "dev":
                                    if self._headless_bridge is not None:
                                        txt_cc, mk_cc = self._headless_bridge.handle_menu(chat_id2, role2, group2)
                                        if txt_cc:
                                            self._reply(token, chat_id2, txt_cc, reply_markup=mk_cc)
                                    continue
                                if op == "svc":
                                    if role2 != "owner":
                                        self._reply(token, chat_id2, "无权限：服务")
                                        continue
                                    from app_ado.tg_help_inline import services_menu
                                    self._reply(token, chat_id2, "🧰 服务面板", reply_markup=services_menu())
                                    continue
                                if op == "wi":
                                    if self._wi_bridge is not None and self._wi_bridge.can_use(role2, group2):
                                        text_wi, markup_wi = self._wi_bridge.handle_main(chat_id2)
                                        self._reply(token, chat_id2, text_wi, reply_markup=markup_wi)
                                    else:
                                        self._reply(token, chat_id2, "无权限：工单")
                                    continue
                                if op == "mcp":
                                    if role2 != "owner":
                                        self._reply(token, chat_id2, "无权限：MCP 配置")
                                        continue
                                    self._reply(token, chat_id2, "⚙️ MCP 配置", reply_markup=self._build_mcp_menu())
                                    continue
                                # back
                                show_dev2 = (role2 == "owner") and (self._headless_bridge is not None)
                                show_wi2 = (role2 == "owner") and (self._wi_bridge is not None)
                                show_svc2 = (role2 == "owner")
                                show_mcp2 = (role2 == "owner")
                                self._reply(token, chat_id2, "代码工具箱", reply_markup=top_menu(show_dev=show_dev2, show_wi=show_wi2, show_svc=show_svc2, show_mcp=show_mcp2))
                                continue

                            if data2.startswith("mcp:"):
                                if role2 != "owner":
                                    self._reply(token, chat_id2, "无权限：MCP 配置")
                                    continue
                                self._handle_mcp_callback(token, chat_id2, data2)
                                continue

                            if data2.startswith("help_run:"):
                                tid = data2.split(":", 1)[1]
                                if not self._can(role2, group2, "run", task_id=str(tid)):
                                    self._reply(token, chat_id2, "无权限：run")
                                    continue
                                from app_ado.tg_help_run_inline import run_mode_buttons

                                self._reply(token, chat_id2, "请选择执行方式：", reply_markup=run_mode_buttons(str(tid)))
                                continue

                            if data2.startswith("runmode:build:"):
                                tid = data2.split(":", 2)[2]
                                if not self._can(role2, group2, "run", task_id=str(tid)):
                                    self._reply(token, chat_id2, "无权限：run")
                                    continue
                                ok, msg = self._on_run(str(tid), chat_id2, username2)
                                self._reply(token, chat_id2, msg if msg else ("收到，开始执行" if ok else "执行失败"))
                                continue

                            if data2.startswith("runmode:deploy:"):
                                tid = data2.split(":", 2)[2]
                                if not self._can(role2, group2, "run", task_id=str(tid)):
                                    self._reply(token, chat_id2, "无权限：run")
                                    continue
                                # deploy-only uses latest successful build
                                try:
                                    ok, msg = self._on_deploy_only(str(tid), chat_id2, username2)
                                except Exception as ex:
                                    ok, msg = False, str(ex)
                                self._reply(token, chat_id2, msg if msg else ("收到，开始仅发布" if ok else "执行失败"))
                                continue

                            if data2 == "runmode:cancel":
                                self._reply(token, chat_id2, "已取消")
                                continue

                            if data2.startswith("help_sys:"):
                                op = data2.split(":", 1)[1]
                                if op == "status":
                                    if not self._can(role2, group2, "status"):
                                        self._reply(token, chat_id2, "无权限：status")
                                    else:
                                        self._reply(token, chat_id2, self._on_status())
                                    continue
                                if op == "stop":
                                    if not self._can(role2, group2, "stop"):
                                        self._reply(token, chat_id2, "无权限：stop")
                                    else:
                                        items = self._on_stop_menu(chat_id2, username2)
                                        if not items:
                                            self._reply(token, chat_id2, "当前没有可停止的任务")
                                        else:
                                            from app_ado.tg_stop_inline import stop_task_buttons

                                            self._reply(token, chat_id2, "请选择要停止的任务：", reply_markup=stop_task_buttons(items))
                                    continue
                                if op == "rollback":
                                    # reuse /rollback flow
                                    ctx3 = TgCommandContext(chat_id=chat_id2, username=username2, text="/rollback")
                                    self._handle(token, ctx3, role=role2, group=group2)
                                    continue

                            if data2.startswith("rb_task:"):
                                self._rollback_wizard[str(chat_id2)] = {"step": "pick_offset"}
                                self._handle_rollback_pick_task(token, ctx2, role=role2, group=group2, task_id=data2.split(":", 1)[1])
                                continue
                            if data2.startswith("rb_off:"):
                                wiz = self._rollback_wizard.get(str(chat_id2)) or {}
                                try:
                                    off = int(data2.split(":", 1)[1])
                                except Exception:
                                    self._reply(token, chat_id2, "offset 无效")
                                    continue
                                wiz["offset"] = off
                                wiz["step"] = "confirm"
                                self._rollback_wizard[str(chat_id2)] = wiz
                                from app_ado.tg_rollback_inline import confirm_buttons

                                self._reply(token, chat_id2, f"确认回退？\noffset={off}\n\n（回退将对该任务配置的所有发布目标依次执行）", reply_markup=confirm_buttons())
                                continue
                            if data2 == "rb_yes":
                                wiz = self._rollback_wizard.get(str(chat_id2)) or {}
                                task_id2 = str(wiz.get("task_id") or "")
                                off2 = int(wiz.get("offset") or 0)
                                if not task_id2 or off2 <= 0:
                                    self._reply(token, chat_id2, "回退流程状态丢失，请重新发 /rollback")
                                    self._rollback_wizard.pop(str(chat_id2), None)
                                    continue
                                self._rollback_wizard.pop(str(chat_id2), None)
                                ok, msg = self._on_rollback(task_id2, off2, chat_id2, username2)
                                self._reply(token, chat_id2, msg)
                                continue
                            if data2.startswith("stp:"):
                                if not self._can(role2, group2, "stop"):
                                    self._reply(token, chat_id2, "无权限：stop")
                                    continue
                                tid = data2.split(":", 1)[1]
                                ok, msg = self._on_stop_one(str(tid), chat_id2, username2)
                                self._reply(token, chat_id2, msg)
                                continue
                            if data2 == "stp_cancel":
                                self._reply(token, chat_id2, "已取消停止")
                                continue

                            if data2 == "rb_cancel":
                                self._rollback_wizard.pop(str(chat_id2), None)
                                self._reply(token, chat_id2, "已取消回退流程")
                                continue

                        continue

                    # message
                    msg = u.get("message") or {}
                    chat = msg.get("chat") or {}
                    chat_id = str(chat.get("id") or "")
                    if not chat_id:
                        continue
                    frm = msg.get("from") or {}
                    username = frm.get("username")
                    text = msg.get("text") or ""
                    reply_to_msg_id: int | None = None
                    rt = msg.get("reply_to_message") or {}
                    if rt.get("message_id") is not None:
                        try:
                            reply_to_msg_id = int(rt.get("message_id"))
                        except Exception:
                            reply_to_msg_id = None

                    role, group = self._resolve_acl(chat_id, username)
                    if role == "none":
                        continue

                    ctx = TgCommandContext(
                        chat_id=chat_id, username=username, text=text, reply_to_msg_id=reply_to_msg_id
                    )
                    if self._mode == "ai":
                        self._handle_ai(token, ctx, role=role, group=group)
                    else:
                        self._handle(token, ctx, role=role, group=group)

                if last_id is not None:
                    self._update_offset = int(last_id) + 1
                    self._save_offset(self._update_offset)

            except Exception as e:
                msg = str(e)
                now = time.time()

                # Treat intermittent network issues as normal; only surface when repeated.
                is_timeout = ("timed out" in msg.lower()) or ("read operation timed out" in msg.lower())

                # update counters
                if self._last_error_ts and (now - self._last_error_ts) > 90:
                    self._consecutive_errors = 0
                    self._first_error_ts = 0.0
                if not self._first_error_ts:
                    self._first_error_ts = now
                self._last_error_ts = now
                # cap to avoid unbounded growth (long outages)
                self._consecutive_errors = min(int(self._consecutive_errors) + 1, 999999)

                # log
                self._log(f"{time.strftime('%Y-%m-%d %H:%M:%S')} tg_control error: {msg}")

                # keep state running but remember last error
                self._write_state(state="运行中", last_poll=time.strftime('%Y-%m-%d %H:%M:%S'), last_error=msg)

                # alert owner if errors keep happening (rate limited)
                try:
                    # alert if repeated failures (rate limited)
                    # At most once per day to avoid spamming.
                    if self._consecutive_errors >= 3 and (now - self._last_alert_ts) > 86400:
                        s2 = load_ui_settings()
                        owner_chat = str(getattr(s2, "telegram_chat_id", "") or "").strip()
                        tok = self._bot_token() or ""
                        if owner_chat and tok:
                            since = int(now - float(self._first_error_ts or now))
                            cnt = int(self._consecutive_errors)
                            send_telegram_message(
                                bot_token=tok,
                                chat_id=owner_chat,
                                text=(
                                    "⚠️ TG 控制网络异常（轮询失败多次）\n"
                                    + f"错误：{msg}\n"
                                    + f"连续次数：{cnt}（持续约 {since}s）\n"
                                    + "说明：这通常是本机网络/DNS/代理导致无法连接 api.telegram.org。\n"
                                    + "建议：检查网络、VPN、代理、DNS。"
                                ),
                            )
                            self._last_alert_ts = now
                except Exception:
                    pass

                # 409 can happen if webhook is set or another poller is active.
                if "409" in msg or "Conflict" in msg:
                    self._delete_webhook(token)
                    time.sleep(5.0)
                else:
                    # For timeouts, shorter sleep is fine.
                    time.sleep(1.0 if is_timeout else 2.0)
