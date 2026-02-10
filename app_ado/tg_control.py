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
    ) -> None:
        self._on_run = on_run
        self._on_deploy_only = on_deploy_only
        self._on_rollback = on_rollback
        self._on_stop_menu = on_stop_menu
        self._on_stop_one = on_stop_one
        self._on_status = on_status

        self._rollback_wizard: dict[str, dict] = {}  # chat_id -> state

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._offset_path = config_dir() / "tg_offset.json"
        self._log_path = config_dir() / "tg_control.log"
        self._state_path = config_dir() / "tg_control_state.json"
        self._update_offset = self._load_offset()

        # health tracking
        self._consecutive_errors: int = 0
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

    def _handle(self, token: str, ctx: TgCommandContext, *, role: str, group: dict | None) -> None:
        t = (ctx.text or "").strip()

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
                self._reply(
                    token,
                    ctx.chat_id,
                    "代码工具箱",
                    reply_markup=top_menu(),
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
                                # back
                                self._reply(token, chat_id2, "代码工具箱", reply_markup=top_menu())
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
                now = time.time()

                # Treat intermittent network issues as normal; only surface when repeated.
                is_timeout = ("timed out" in msg.lower()) or ("read operation timed out" in msg.lower())

                # update counters
                if self._last_error_ts and (now - self._last_error_ts) > 90:
                    self._consecutive_errors = 0
                self._last_error_ts = now
                self._consecutive_errors += 1

                # log
                self._log(f"{time.strftime('%Y-%m-%d %H:%M:%S')} tg_control error: {msg}")

                # keep state running but remember last error
                self._write_state(state="运行中", last_poll=time.strftime('%Y-%m-%d %H:%M:%S'), last_error=msg)

                # alert owner if errors keep happening (rate limited)
                try:
                    if self._consecutive_errors >= 3 and (now - self._last_alert_ts) > 300:
                        s2 = load_ui_settings()
                        owner_chat = str(getattr(s2, "telegram_chat_id", "") or "").strip()
                        tok = self._bot_token() or ""
                        if owner_chat and tok:
                            send_telegram_message(
                                bot_token=tok,
                                chat_id=owner_chat,
                                text=(
                                    "⚠️ TG 控制网络不稳定（轮询失败多次）\n"
                                    + f"错误：{msg}\n"
                                    + f"连续次数：{self._consecutive_errors}"
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
