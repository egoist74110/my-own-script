from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QWidget, QFormLayout
from qfluentwidgets import CardWidget, ComboBox, PushButton, LineEdit
from shiboken6 import isValid

from app_ado.ui.task_card import TaskCard

from app_ado.store import load_task_settings, save_task_settings
from app_ado.ui.confirm import show_confirm_dialog
from app_ado.ui.dialogs import show_error_dialog
from app_ado.ui.run_log_dialog import RunLogDialog
from app_ado.ui.task_flow_dialog import FlowTaskConfigDialog
from qfluentwidgets import ScrollArea


class TasksTab(QtWidgets.QWidget):
    """Tasks tab.

    Now supports dynamic tasks (CRUD) stored in tasks.yaml.
    """

    icon = None
    name = "任务"

    def __init__(self):
        super().__init__()
        # Required by qfluentwidgets FluentWindow.addSubInterface
        if not self.objectName():
            self.setObjectName("TasksTab")

        # Root layout: fixed header + scrollable task list
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)
        # Per-task running contexts: task_id -> ctx
        # ctx keys: stop_event, by_chat_id, by_username, kind ('run'|'rollback'), label
        self._running_tasks: dict[str, dict] = {}
        self._stop_requester_chat_id: str = ""
        self._stop_requester_username: str | None = None
        self._stop_source: str = ""  # 'tg'|'ui'

        self._task_cards: dict[str, TaskCard] = {}

        # Header (fixed)
        header = QtWidgets.QWidget(self)
        header_row = QtWidgets.QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        self.search = LineEdit(); self.search.setPlaceholderText("搜索任务（命令/说明）")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)

        self.btn_new_task = PushButton("新增任务")
        self.btn_new_task.setFixedWidth(96)
        self.btn_sort_tasks = PushButton("排序")
        self.btn_sort_tasks.setFixedWidth(72)
        self.btn_refresh_tasks = PushButton("刷新")
        self.btn_refresh_tasks.setFixedWidth(72)

        header_row.addWidget(self.search)
        header_row.addWidget(self.btn_new_task)
        header_row.addWidget(self.btn_sort_tasks)
        header_row.addWidget(self.btn_refresh_tasks)
        header_row.addStretch(1)

        self.btn_new_task.clicked.connect(self._new_task)
        self.btn_sort_tasks.clicked.connect(self._sort_tasks)
        self.btn_refresh_tasks.clicked.connect(self._render_tasks)
        self.search.textChanged.connect(lambda: self._render_tasks())

        root.addWidget(header, 0)

        # Scrollable list area
        self.list_area = ScrollArea(self)
        self.list_area.setWidgetResizable(True)
        self.list_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        # Remove scroll area border/frame for a cleaner list look
        self.list_area.setStyleSheet(
            "QScrollArea{border:0px;background:transparent;}"
            "QScrollArea>QWidget>QWidget{background:transparent;}"
        )

        self.list_view = QtWidgets.QWidget(self.list_area)
        self.list_layout = QtWidgets.QVBoxLayout(self.list_view)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.setAlignment(QtCore.Qt.AlignTop)

        self.list_area.setWidget(self.list_view)
        root.addWidget(self.list_area, 1)

        self._render_tasks()

    def _check_running_lock(self) -> bool:
        if self._running_tasks:
            from app_ado.ui.dialogs import show_error_dialog
            show_error_dialog(self.window(), "操作受限", "当前有任务正在运行中，为保护运行日志和状态，请等待任务完成后再修改配置！")
            return False
        return True

    def _update_run_states(self) -> None:
        has_running = len(self._running_tasks) > 0
        self.btn_new_task.setEnabled(not has_running)
        self.btn_sort_tasks.setEnabled(not has_running)
        self.btn_refresh_tasks.setEnabled(not has_running)
        self.search.setEnabled(not has_running)

        for tid, card in self._task_cards.items():
            if str(tid) == "__hint__":
                continue
            try:
                card.btn_config.setEnabled(not has_running)
                card.btn_delete.setEnabled(not has_running)
            except Exception:
                pass

    def _clear_run_log(self, card: TaskCard) -> None:
        card.clear_log()

    def _append_run_log(self, card: TaskCard, text: str) -> None:
        card.append_log(text)

    def _sort_tasks(self) -> None:
        if not self._check_running_lock():
            return
        ts = load_task_settings()
        tasks = list(getattr(ts, "tasks", []) or [])
        if not tasks:
            show_error_dialog(self.window(), "提示", "暂无任务可排序")
            return

        from app_ado.ui.task_sort_dialog import TaskSortDialog

        dlg = TaskSortDialog(self.window(), tasks)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        order = dlg.result_order()
        for t in tasks:
            if str(t.id) in order:
                t.sort_order = int(order[str(t.id)])

        # persist and rerender
        ts.tasks = tasks
        save_task_settings(ts)
        self._render_tasks()

    def _render_tasks(self) -> None:
        """Render task cards from dynamic tasks config."""
        if self._running_tasks:
            return  # do not wipe out cards while tasks are running

        # remove old cards
        for card in list(self._task_cards.values()):
            try:
                self.list_layout.removeWidget(card)
                card.setParent(None)
                card.deleteLater()
            except Exception:
                pass
        self._task_cards.clear()

        ts = load_task_settings()
        tasks = list(getattr(ts, "tasks", []) or [])
        tasks.sort(key=lambda t: (int(getattr(t, "sort_order", 0) or 0), (t.tg_command or "").lower()))

        q = (self.search.text() or "").strip().lower() if hasattr(self, "search") else ""
        if q:
            def match(t):
                cmd = (t.tg_command or "").strip().lower()
                desc = (t.tg_desc or "").strip().lower()
                return q in cmd or q in desc
            tasks = [t for t in tasks if match(t)]

        if not tasks:
            hint = QtWidgets.QLabel("暂无任务。点击【新增任务】创建。")
            hint.setStyleSheet("color: #666;")
            self.list_layout.addWidget(hint)
            self._task_cards["__hint__"] = hint  # type: ignore
            return

        for t in tasks:
            title = (t.tg_desc or "").strip() or ("/" + (t.tg_command or ""))
            subtitle = ("TG命令：/" + (t.tg_command or ""))
            card = TaskCard(title=title, subtitle=subtitle, show_delete=True, show_history=True)

            card.config_clicked.connect(lambda _=None, tid=t.id: self._edit_task(tid))
            card.run_clicked.connect(lambda _=None, tid=t.id, c=card: self._run(tid, c))
            card.rollback_clicked.connect(lambda _=None, tid=t.id, c=card: self._rollback(tid, c))
            card.stop_clicked.connect(lambda _=None, tid=t.id: self._stop_task_ui(tid))
            card.history_clicked.connect(lambda _=None, tid=t.id: self._show_history(tid))
            card.delete_clicked.connect(lambda _=None, tid=t.id: self._delete_task(tid))

            self.list_layout.addWidget(card)
            self._task_cards[t.id] = card
        
        self._update_run_states()

    def _new_task(self) -> None:
        if not self._check_running_lock():
            return
        from app_ado.models import DynamicTaskConfig
        from app_ado.store import load_ui_settings
        from app_ado.ui.dynamic_task_dialog import DynamicTaskConfigDialog

        ts = load_task_settings()
        settings = load_ui_settings()
        t = DynamicTaskConfig(id="")
        dlg = DynamicTaskConfigDialog(self.window(), settings=settings, task=t)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        rt = dlg.result_task()
        if not rt:
            return
        if int(getattr(rt, "sort_order", 0) or 0) == 0:
            cur = [int(getattr(x, "sort_order", 0) or 0) for x in (ts.tasks or [])]
            rt.sort_order = (max(cur) + 10) if cur else 10
        ts.tasks.append(rt)
        save_task_settings(ts)
        self._render_tasks()

    def _show_history(self, task_id: str) -> None:
        from app_ado.task_history import read_recent, fmt_ts

        ts = load_task_settings()
        t = next((x for x in (ts.tasks or []) if x.id == task_id), None)
        label = (t.tg_desc or "").strip() if t else task_id

        items = read_recent(task_id=task_id, limit=50)
        if not items:
            show_error_dialog(self.window(), "任务历史", f"暂无历史记录：{label}")
            return

        dlg = RunLogDialog(self.window(), title=f"历史：{label}")
        for j in items:
            dlg.log(
                f"[{fmt_ts(int(j.get('ts') or 0))}] {j.get('result') or ''}"
                f"\n触发者: {j.get('requester_username') or ''} ({j.get('requester_chat_id') or ''})"
                f"\n来源: {j.get('triggered_by') or ''}"
                f"\n概要: {j.get('summary') or ''}"
                f"\n"
            )
        dlg.exec()

    def _delete_task(self, task_id: str) -> None:
        if not self._check_running_lock():
            return
        ts = load_task_settings()
        t = next((x for x in (ts.tasks or []) if x.id == task_id), None)
        if not t:
            return
        label = (t.tg_desc or "").strip() or ("/" + (t.tg_command or ""))
        from app_ado.ui.confirm import show_confirm_dialog

        ok = show_confirm_dialog(self.window(), "确认删除", f"删除任务：{label}？")
        if not ok:
            return
        ts.tasks = [x for x in (ts.tasks or []) if x.id != task_id]
        save_task_settings(ts)

        # Also remove references from Telegram ACL groups
        try:
            from app_ado.store import load_ui_settings, save_ui_settings

            s = load_ui_settings()
            changed = False
            new_groups: list[dict] = []
            for g in (s.telegram_acl_groups or []):
                tids = list(g.get("task_ids") or [])
                tids2 = [x for x in tids if str(x) != str(task_id)]
                if tids2 != tids:
                    changed = True
                gg = dict(g)
                gg["task_ids"] = tids2
                new_groups.append(gg)
            if changed:
                s.telegram_acl_groups = new_groups
                save_ui_settings(s)
        except Exception:
            pass

        self._render_tasks()

    def _edit_task(self, task_id: str) -> None:
        if not self._check_running_lock():
            return
        from app_ado.store import load_ui_settings
        from app_ado.ui.dynamic_task_dialog import DynamicTaskConfigDialog

        ts = load_task_settings()
        t = next((x for x in (ts.tasks or []) if x.id == task_id), None)
        if not t:
            show_error_dialog(self.window(), "错误", "任务不存在")
            return

        settings = load_ui_settings()
        dlg = DynamicTaskConfigDialog(self.window(), settings=settings, task=t)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        rt = dlg.result_task()
        if not rt:
            return

        # enforce command uniqueness
        cmd = (rt.tg_command or "").strip().lower()
        for x in ts.tasks:
            if x.id != rt.id and (x.tg_command or "").strip().lower() == cmd:
                show_error_dialog(self.window(), "错误", f"TG 命令已被占用：/{cmd}")
                return

        ts.tasks = [rt if x.id == rt.id else x for x in ts.tasks]
        save_task_settings(ts)
        self._render_tasks()

    def _is_task_running(self, task_id: str) -> bool:
        return str(task_id) in self._running_tasks

    def run_task(self, key: str, requester_chat_id: str, requester_username: str | None) -> tuple[bool, str]:
        """TG-triggered run.

        key can be task_id or tg_command.
        Returns (ok, message) for Telegram reply.
        """
        ts = load_task_settings()
        tasks = list(getattr(ts, "tasks", []) or [])
        k = (key or "").strip().lstrip("/")
        t = next((x for x in tasks if x.id == k), None) or next(
            (x for x in tasks if (x.tg_command or "").strip().lower() == k.lower()),
            None,
        )
        if not t:
            return False, "⚠️ 未找到任务，请发 /help 查看可用任务"

        if self._is_task_running(str(t.id)):
            label = (t.tg_desc or "").strip() or ("/" + (t.tg_command or "").strip()) or str(t.id)
            return False, f"⛔ 无法执行\n该任务正在运行中：{label}。请等待完成或先 /stop"

        # basic precheck
        missing: list[str] = []
        # local repo path is optional
        if not t.targets:
            missing.append("- 发布目标（至少新增一个：构建+发布+阶段）")
        build_branch = (getattr(t.git_flow, "build_branch", "") or "").strip()
        if not build_branch:
            missing.append("- Git流程：构建分支")
        if t.git_flow.merges:
            r = t.git_flow.merges[0]
            if not r.source or not r.target:
                missing.append("- Git流程：合并规则不完整")

        if missing:
            label = (t.tg_desc or "").strip() or ("/" + (t.tg_command or ""))
            msg = "⚠️ 配置不完整\n" + f"请先在【代码配置】中补齐（{label}）：\n" + "\n".join(missing)
            return False, msg

        card = self._task_cards.get(t.id)
        if not card:
            return False, "⚠️ 任务卡片未加载，请打开应用后再试"

        QtCore.QTimer.singleShot(0, self, lambda: self._run(t.id, card, skip_confirm=True, tg_reply_chat_id=requester_chat_id, tg_reply_username=requester_username))
        return True, f"收到，开始执行：{t.name}"

    def deploy_only_task(self, task_id: str, requester_chat_id: str, requester_username: str | None) -> tuple[bool, str]:
        """TG-triggered deploy-only (use latest successful build, skip git/build).

        Returns (ok, message) for Telegram reply.
        """
        ts = load_task_settings()
        task = next((t for t in (ts.tasks or []) if str(t.id) == str(task_id)), None)
        if not task:
            return False, "⚠️ 未找到任务，请发 /help 查看可用任务"

        if self._is_task_running(str(task.id)):
            label = (task.tg_desc or "").strip() or ("/" + (task.tg_command or "").strip()) or str(task.id)
            return False, f"⛔ 无法执行\n该任务正在运行中：{label}。请等待完成或先 /stop"

        card = self._task_cards.get(str(task.id))
        if not card:
            return False, "⚠️ 任务卡片未加载，请打开应用后再试"

        QtCore.QTimer.singleShot(0, self, lambda: self._deploy_only(str(task.id), card, tg_reply_chat_id=requester_chat_id, tg_reply_username=requester_username))
        return True, f"收到，开始仅发布：{(task.tg_desc or task.tg_command or task.id)}"

    def rollback_task(self, task_id: str, offset: int, requester_chat_id: str, requester_username: str | None) -> tuple[bool, str]:
        """TG-triggered rollback.

        Returns (ok, message) for Telegram reply.
        """
        ts = load_task_settings()
        task = next((t for t in (ts.tasks or []) if str(t.id) == str(task_id)), None)
        if not task:
            return False, "⚠️ 未找到任务，请发 /help 查看可用任务"

        if self._is_task_running(str(task.id)):
            label = (task.tg_desc or "").strip() or ("/" + (task.tg_command or "").strip()) or str(task.id)
            return False, f"⛔ 无法执行\n该任务正在运行中：{label}。请等待完成或先 /stop"

        if offset < 1:
            return False, "⚠️ offset 必须 >= 1（请先发 /rollback 开始交互式选择）"

        card = self._task_cards.get(str(task.id))
        if not card:
            return False, "⚠️ 任务卡片未加载，请打开应用后再试"

        # schedule on Qt main thread
        QtCore.QTimer.singleShot(0, self, lambda: self._rollback_tg(str(task.id), card, offset, tg_reply_chat_id=requester_chat_id, tg_reply_username=requester_username))
        return True, f"收到，开始回退：{(task.tg_desc or task.tg_command or task.id)}（offset={offset}）"

    def list_stoppable_tasks(self, requester_chat_id: str, requester_username: str | None) -> list[tuple[str, str]]:
        """Return [(task_id, label)] tasks that requester can stop."""
        try:
            from app_ado.store import load_ui_settings

            s = load_ui_settings()
            owner = str(s.telegram_chat_id or "")
        except Exception:
            owner = ""

        req = str(requester_chat_id or "")
        is_owner = bool(owner and req and req == owner)

        out: list[tuple[str, str]] = []
        for tid, ctx in list(self._running_tasks.items()):
            by_chat = str(ctx.get("by_chat_id") or "")
            if is_owner or (req and req == by_chat):
                label = str(ctx.get("label") or tid)
                kind = str(ctx.get("kind") or "run")
                out.append((str(tid), f"{label} ({kind})"))
        return out

    def stop_one_task(self, task_id: str, requester_chat_id: str, requester_username: str | None) -> tuple[bool, str]:
        """Stop a specific running task (TG)."""
        ctx = self._running_tasks.get(str(task_id))
        if not ctx:
            return False, "该任务当前不在运行中"

        # permission: owner or same requester
        try:
            from app_ado.store import load_ui_settings

            s = load_ui_settings()
            owner = str(s.telegram_chat_id or "")
        except Exception:
            owner = ""

        req = str(requester_chat_id or "")
        is_owner = bool(owner and req and req == owner)
        by_chat = str(ctx.get("by_chat_id") or "")
        if not is_owner and (not req or req != by_chat):
            return False, "停止请求被拒绝：只能停止自己触发的任务"

        ctx["stop_source"] = "tg"
        ctx["stop_requester_chat_id"] = req
        ctx["stop_requester_username"] = str(requester_username or "")
        try:
            ev = ctx.get("stop_event")
            if ev:
                ev.set()
        except Exception:
            pass
        return True, "已发送停止请求"

    def stop_task(self, requester_chat_id: str, requester_username: str | None) -> None:
        # Deprecated: keep for backward compatibility.
        self._stop_requester_chat_id = requester_chat_id
        self._stop_requester_username = requester_username
        QtCore.QTimer.singleShot(0, self, self._stop_tasks_from_tg)

    def status_text(self) -> str:
        if not self._running_tasks:
            return "空闲"
        parts = []
        for tid, ctx in list(self._running_tasks.items()):
            label = ctx.get("label") or tid
            kind = ctx.get("kind") or "run"
            parts.append(f"- {label} ({kind})")
        return "运行中：\n" + "\n".join(parts)

    def _rollback_tg(self, task_id: str, card: TaskCard, offset: int, *, tg_reply_chat_id: str, tg_reply_username: str | None = None) -> None:
        """TG rollback execution (no dialogs)."""
        # Reuse the same underlying implementation as UI, but skip dialogs.
        return self._rollback_impl(task_id, card, offset=offset, skip_confirm=True, tg_reply_chat_id=tg_reply_chat_id, tg_reply_username=tg_reply_username)

    def _rollback(self, task_id: str, card: TaskCard) -> None:
        """Rollback: redeploy previous classic releases for each target."""
        if self._is_task_running(str(task_id)):
            show_error_dialog(self.window(), "无法执行", "该任务正在运行中，请等待完成或先停止")
            return

        ts = load_task_settings()
        task = next((t for t in (ts.tasks or []) if t.id == task_id), None)
        if not task:
            show_error_dialog(self.window(), "错误", "任务不存在")
            return

        task_label = (task.tg_desc or "").strip() or ("/" + (task.tg_command or "").strip()) or "任务"

        # basic validation
        missing: list[str] = []
        targets = list(task.targets or [])
        if not targets:
            missing.append("- 发布目标")
        for i, tgt in enumerate(targets, start=1):
            if not (tgt.release_id and (tgt.release_stage_ids or tgt.release_stage_names)):
                missing.append(f"- Target[{i}] {tgt.name}: release 定义/阶段未配置")
        if missing:
            show_error_dialog(self.window(), "配置不完整", "回退需要配置 Release 定义 + 阶段：\n" + "\n".join(missing))
            return

        # load settings/pat
        from app_ado.store import load_ui_settings
        from app_ado.secrets import get_pat

        settings = load_ui_settings()
        proj = next((p for p in settings.projects if p.id == task.project_id), None)
        if not proj:
            show_error_dialog(self.window(), "错误", "找不到项目配置（project_id）")
            return
        lib = next((l for l in settings.libraries if l.id == proj.library_id), None)
        if not lib:
            show_error_dialog(self.window(), "错误", "项目未关联代码库")
            return
        pat = get_pat(lib.id)
        if not pat:
            show_error_dialog(self.window(), "错误", "该代码库未保存 PAT")
            return

        # UI chooses offset in dialog, then delegates to implementation
        from app_ado.ado_release_http import list_recent_releases

        per_target: list[tuple[str, list]] = []
        for tgt in targets:
            try:
                rels = list_recent_releases(lib.base_url, proj.collection, proj.project, str(tgt.release_id), pat=pat, top=6, api_version="6.0")
            except Exception:
                rels = list_recent_releases(lib.base_url, proj.collection, proj.project, str(tgt.release_id), pat=pat, top=6, api_version="7.0")
            per_target.append((tgt.name, rels))

        max_offset = 5
        for _, rels in per_target:
            max_offset = min(max_offset, max(0, len(rels) - 1))
        if max_offset <= 0:
            show_error_dialog(self.window(), "无法回退", "Release 历史不足（需要至少 2 个 Release 才能回退）。")
            return

        from datetime import datetime, timezone

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

        preview: dict[int, list[str]] = {}
        for k in range(1, max_offset + 1):
            lines = [f"回退 offset={k}："]
            for tgt, rels in per_target:
                r = rels[k]
                ts2 = fmt_time(r.created_on)
                lines.append(f"- {tgt}: {r.name or r.id}" + (f" ({ts2})" if ts2 else ""))
            preview[k] = lines

        from app_ado.ui.rollback_dialog import RollbackDialog

        dlg = RollbackDialog(self.window(), task_label=task_label, max_offset=max_offset, preview_lines=preview)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        choice = dlg.result_choice()
        if not choice:
            return
        offset = int(choice.offset)

        ok = show_confirm_dialog(self.window(), "确认回退？", "将按以下版本回退（依次执行）：\n\n" + "\n".join(preview[offset]))
        if not ok:
            return

        self._rollback_impl(task_id, card, offset=offset, skip_confirm=False, tg_reply_chat_id=None)
        return

    def _rollback_impl(self, task_id: str, card: TaskCard, *, offset: int, skip_confirm: bool, tg_reply_chat_id: str | None, tg_reply_username: str | None = None) -> None:
        """Shared rollback implementation for UI and TG."""
        import queue
        import threading
        import time

        # re-load task/settings inside impl (avoid capturing stale objects)
        ts = load_task_settings()
        task = next((t for t in (ts.tasks or []) if str(t.id) == str(task_id)), None)
        if not task:
            show_error_dialog(self.window(), "错误", "任务不存在")
            return

        task_label = (task.tg_desc or "").strip() or ("/" + (task.tg_command or "").strip()) or "任务"

        from app_ado.store import load_ui_settings
        from app_ado.secrets import get_pat

        ui = load_ui_settings()
        proj = next((p for p in ui.projects if p.id == task.project_id), None)
        if not proj:
            show_error_dialog(self.window(), "错误", "找不到项目配置（project_id）")
            return
        lib = next((l for l in ui.libraries if l.id == proj.library_id), None)
        if not lib:
            show_error_dialog(self.window(), "错误", "项目未关联代码库")
            return
        pat = get_pat(lib.id)
        if not pat:
            show_error_dialog(self.window(), "错误", "该代码库未保存 PAT")
            return

        targets = list(task.targets or [])
        if not targets:
            show_error_dialog(self.window(), "配置不完整", "回退需要配置发布目标")
            return

        from app_ado.ado_release_http import list_recent_releases

        per_target: list[tuple[str, list]] = []
        for tgt in targets:
            try:
                rels = list_recent_releases(lib.base_url, proj.collection, proj.project, str(tgt.release_id), pat=pat, top=6, api_version="6.0")
            except Exception:
                rels = list_recent_releases(lib.base_url, proj.collection, proj.project, str(tgt.release_id), pat=pat, top=6, api_version="7.0")
            per_target.append((tgt.name, rels))

        max_offset = 5
        for _, rels in per_target:
            max_offset = min(max_offset, max(0, len(rels) - 1))
        if max_offset <= 0:
            show_error_dialog(self.window(), "无法回退", "Release 历史不足（需要至少 2 个 Release 才能回退）。")
            return
        if offset < 1 or offset > max_offset:
            show_error_dialog(self.window(), "无法回退", f"offset 超出范围：1~{max_offset}")
            return

        # stop support (per task)
        stop_event = threading.Event()
        # determine notification recipient and requester identity (avoid global last_requester races)
        try:
            from app_ado.store import load_ui_settings

            s_owner = load_ui_settings()
            owner_chat = str(getattr(s_owner, "telegram_chat_id", "") or "").strip()
        except Exception:
            owner_chat = ""

        requester_chat = str(tg_reply_chat_id or "").strip()
        notify_chat_id = requester_chat or owner_chat

        self._running_tasks[str(task_id)] = {
            "stop_event": stop_event,
            "by_chat_id": requester_chat,
            "by_username": str(tg_reply_username or ""),
            "kind": "rollback",
            "label": task_label,
            "card": card,
        }
        self._update_run_states()

        q: queue.Queue[tuple[str, str]] = queue.Queue()

        def emit_log(text: str) -> None:
            q.put(("log", text))

        def should_stop() -> bool:
            return bool(stop_event.is_set())

        def notify_telegram(summary: str, details: str = "") -> None:
            try:
                from app_ado.store import load_ui_settings
                from app_ado.secrets import get_telegram_token
                from app_ado.notifier_telegram import send_telegram_message

                token = get_telegram_token()
                if not token:
                    return
                s = load_ui_settings()
                include = bool(getattr(s, "telegram_notify_include_details", False))

                chat_id = notify_chat_id
                if not chat_id:
                    chat_id = str(getattr(s, "telegram_chat_id", "") or "").strip()
                if not chat_id:
                    return

                text = summary
                if include and details:
                    text = summary + "\n" + details
                send_telegram_message(bot_token=token, chat_id=chat_id, text=text)
            except Exception:
                return

        def _brief_reason(title: str, details: str) -> str:
            t = (title or "").strip()
            d = (details or "").strip()
            for line in d.splitlines():
                line = line.strip()
                if not line or line == t:
                    continue
                return line[:120]
            return ""

        def emit_error(title: str, details: str) -> None:
            brief = _brief_reason(title, details)
            notify_telegram(
                f"❌ 回退失败：{title}" + (f"（{brief}）" if brief else ""),
                f"{task_label}\noffset={offset}\n{title}\n{details}",
            )
            try:
                from app_ado.task_history import TaskRunRecord, append_record
                import time as _time

                append_record(
                    TaskRunRecord(
                        ts=int(_time.time()),
                        task_id=str(task.id),
                        task_label=task_label,
                        triggered_by=("tg" if tg_reply_chat_id else "ui"),
                        requester_chat_id=str(tg_reply_chat_id or ""),
                        requester_username=str(tg_reply_username or ""),
                        result="fail",
                        summary=f"{title}",
                        details=(f"{title}\n{details}"[:1800]),
                    )
                )
            except Exception:
                pass
            q.put(("error", title + "\n" + details))

        def worker() -> None:
            try:
                emit_log(f"回退：{task_label} (offset={offset})")
                notify_telegram("🚧 开始回退", f"{task_label}\noffset={offset}\ntargets={len(targets)}")

                from app_ado.ado_release_http import get_release, extract_envs, start_release_environment

                def fetch_envs(release_id: str):
                    try:
                        data = get_release(lib.base_url, proj.collection, proj.project, release_id, pat=pat, api_version="6.0")
                    except Exception:
                        data = get_release(lib.base_url, proj.collection, proj.project, release_id, pat=pat, api_version="7.0")
                    return extract_envs(data)

                def is_done(status: str) -> bool:
                    s = (status or "").lower()
                    return s in {"succeeded", "rejected", "canceled", "cancelled", "failed"}

                for idx, tgt in enumerate(targets, start=1):
                    if should_stop():
                        emit_error("已取消", "由用户停止")
                        return

                    rels = next((x for n, x in per_target if n == tgt.name), [])
                    sel = rels[offset]
                    emit_log(f"\n=== Target[{idx}] {tgt.name} ===")
                    emit_log(f"选择 Release：{sel.name or sel.id} ({sel.id})")

                    envs = fetch_envs(sel.id)

                    want_ids = set(list(getattr(tgt, "release_stage_ids", []) or []))
                    want_names = set(list(getattr(tgt, "release_stage_names", []) or []))

                    selected = [e for e in envs if (e.definition_environment_id or "") in want_ids] if want_ids else []
                    if not selected and want_names:
                        selected = [e for e in envs if e.name in want_names]

                    if not selected:
                        emit_error("无法回退", f"未在 Release 中找到匹配的阶段：{tgt.name}")
                        return

                    for e in selected:
                        if should_stop():
                            emit_error("已取消", "由用户停止")
                            return
                        emit_log(f"触发回退部署：{e.name} (envId={e.id}, defEnvId={e.definition_environment_id})")
                        start_release_environment(lib.base_url, proj.collection, proj.project, sel.id, e.id, pat=pat)
                        time.sleep(0.8)

                    timeout_sec = 60 * 60
                    start_wait = time.time()
                    deadline = start_wait + timeout_sec
                    last_line = ""
                    while time.time() < deadline:
                        if should_stop():
                            emit_error("已取消", "由用户停止")
                            return

                        envs2 = fetch_envs(sel.id)
                        by_id = {e.id: e for e in envs2}
                        cur_sel = [by_id.get(e.id) for e in selected]
                        cur_sel = [e for e in cur_sel if e is not None]

                        parts = [f"{e.name}(envId={e.id})={e.status}" for e in cur_sel]
                        line = "监控回退：" + " | ".join(parts) if parts else "监控回退：等待阶段状态更新"
                        if line != last_line:
                            emit_log(line)
                            last_line = line

                        if cur_sel and all(is_done(e.status) for e in cur_sel):
                            failed = [e for e in cur_sel if (e.status or "").lower() not in ("succeeded",)]
                            if failed:
                                any_canceled = any((e.status or "").lower() in {"canceled", "cancelled"} for e in failed)
                                msg = "回退部署完成但存在异常阶段：\n" + "\n".join([f"- {e.name} ({e.id}) status={e.status}" for e in failed])
                                if any_canceled:
                                    emit_error("ADO 平台已取消：Release", msg + (f"\n\n{sel.url or ''}"))
                                else:
                                    emit_error("ADO 平台报错：Release", msg + (f"\n\n{sel.url or ''}"))
                                return
                            emit_log(f"✅ Target[{idx}] {tgt.name} 回退成功")
                            break

                        # Responsive sleep
                        for _ in range(8):
                            if should_stop(): break
                            time.sleep(0.5)

                    else:
                        waited = int(time.time() - start_wait)
                        emit_error(
                            "发布超时",
                            "ADO 平台超时：等待回退 Release 阶段完成超时\n"
                            + f"target={tgt.name}\n"
                            + f"release_def_id={tgt.release_id} release_id={sel.id}\n"
                            + f"已等待={waited}s（超时={timeout_sec}s）\n"
                            + f"url={sel.url or ''}",
                        )
                        return

                notify_telegram("✅ 回退成功", f"{task_label}\noffset={offset}\ntargets={len(targets)}")
            except Exception as ex:
                emit_error("回退失败", str(ex))
            finally:
                # 保证任何退出路径（成功/异常/停止/阶段失败/超时 return）都发一次 done，
                # 否则 flush() 不会 pop _running_tasks，运行状态会永久泄漏。
                q.put(("done", ""))

        def flush() -> None:
            finished = False
            try:
                while True:
                    kind, payload = q.get_nowait()
                    if kind == "log":
                        if isValid(card):
                            self._append_run_log(card, payload)
                    elif kind == "error":
                        parts = payload.split("\n", 1)
                        title = parts[0]
                        details = parts[1] if len(parts) > 1 else ""
                        if isValid(self.window()):
                            show_error_dialog(self.window(), title, details)
                    elif kind == "done":
                        finished = True
            except Exception:
                pass

            if finished:
                if isValid(card):
                    card.set_actions_enabled(True)
                self._running_tasks.pop(str(task_id), None)
                self._update_run_states()
                return
            QtCore.QTimer.singleShot(120, flush)

        try:
            card.set_actions_enabled(False)
            self._clear_run_log(card)

            th = threading.Thread(target=worker, daemon=True)
            th.start()
            QtCore.QTimer.singleShot(120, flush)
        except Exception as ex:
            self._running_tasks.pop(str(task_id), None)
            self._update_run_states()
            try:
                card.set_actions_enabled(True)
            except Exception:
                pass
            show_error_dialog(self.window(), "无法启动任务", str(ex))

    def _deploy_only(self, task_id: str, card: TaskCard, *, tg_reply_chat_id: str | None = None, tg_reply_username: str | None = None) -> None:
        """Deploy only: skip git/build, use latest successful build then create release + monitor stages."""

        if self._is_task_running(str(task_id)):
            show_error_dialog(self.window(), "无法执行", "该任务正在运行中，请等待完成或先停止")
            return

        ts = load_task_settings()
        task = next((t for t in (ts.tasks or []) if str(t.id) == str(task_id)), None)
        if not task:
            show_error_dialog(self.window(), "错误", "任务不存在")
            return

        task_label = (task.tg_desc or "").strip() or ("/" + (task.tg_command or "").strip()) or "任务"

        # basic validation
        build_branch = (getattr(task.git_flow, "build_branch", "") or "").strip()
        if not build_branch:
            show_error_dialog(self.window(), "配置不完整", "仅发布需要配置【构建分支】")
            return
        targets = list(task.targets or [])
        if not targets:
            show_error_dialog(self.window(), "配置不完整", "仅发布需要至少一个发布目标")
            return

        from app_ado.store import load_ui_settings
        from app_ado.secrets import get_pat

        settings = load_ui_settings()
        proj = next((p for p in settings.projects if p.id == task.project_id), None)
        if not proj:
            show_error_dialog(self.window(), "错误", "找不到项目配置（project_id）")
            return
        lib = next((l for l in settings.libraries if l.id == proj.library_id), None)
        if not lib:
            show_error_dialog(self.window(), "错误", "项目未关联代码库")
            return
        pat = get_pat(lib.id)
        if not pat:
            show_error_dialog(self.window(), "错误", "该代码库未保存 PAT")
            return

        import queue
        import threading
        import time

        # determine notification recipient and requester identity (avoid global last_requester races)
        try:
            from app_ado.store import load_ui_settings

            s_owner = load_ui_settings()
            owner_chat = str(getattr(s_owner, "telegram_chat_id", "") or "").strip()
        except Exception:
            owner_chat = ""

        requester_chat = str(tg_reply_chat_id or "").strip()
        notify_chat_id = requester_chat or owner_chat

        stop_event = threading.Event()
        self._running_tasks[str(task_id)] = {
            "stop_event": stop_event,
            "by_chat_id": requester_chat,
            "by_username": str(tg_reply_username or ""),
            "kind": "deploy",
            "label": task_label,
            "card": card,
        }
        self._update_run_states()

        q: queue.Queue[tuple[str, str]] = queue.Queue()

        def emit_log(text: str) -> None:
            q.put(("log", text))

        def should_stop() -> bool:
            return bool(stop_event.is_set())

        def notify_telegram(summary: str, details: str = "") -> None:
            try:
                from app_ado.store import load_ui_settings
                from app_ado.secrets import get_telegram_token
                from app_ado.notifier_telegram import send_telegram_message

                token = get_telegram_token()
                if not token:
                    return

                s = load_ui_settings()
                include = bool(getattr(s, "telegram_notify_include_details", False))

                chat_id = notify_chat_id
                if not chat_id:
                    chat_id = str(getattr(s, "telegram_chat_id", "") or "").strip()
                if not chat_id:
                    return

                text = summary
                if include and details:
                    text = summary + "\n" + details
                send_telegram_message(bot_token=token, chat_id=chat_id, text=text)
            except Exception:
                return

        def _brief_reason(title: str, details: str) -> str:
            t = (title or "").strip()
            d = (details or "").strip()
            for line in d.splitlines():
                line = line.strip()
                if not line or line == t:
                    continue
                return line[:120]
            return ""

        def emit_error(title: str, details: str) -> None:
            brief = _brief_reason(title, details)
            notify_telegram(
                f"❌ 仅发布失败：{title}" + (f"（{brief}）" if brief else ""),
                f"{task_label}\n{title}\n{details}",
            )
            try:
                from app_ado.task_history import TaskRunRecord, append_record
                import time as _time

                append_record(
                    TaskRunRecord(
                        ts=int(_time.time()),
                        task_id=str(task.id),
                        task_label=task_label,
                        triggered_by=("tg" if tg_reply_chat_id else "ui"),
                        requester_chat_id=str(tg_reply_chat_id or ""),
                        requester_username=str(tg_reply_username or ""),
                        result="fail",
                        summary=f"{title}",
                        details=(f"{title}\n{details}"[:1800]),
                    )
                )
            except Exception:
                pass
            q.put(("error", title + "\n" + details))

        def worker() -> None:
            try:
                emit_log(f"仅发布：{task_label}")
                emit_log(f"branch={build_branch}")
                notify_telegram("🚀 开始仅发布", f"{task_label}\nbranch={build_branch}\ntargets={len(targets)}")

                from app_ado.ado_build_query import get_latest_successful_build
                from app_ado.ado_release_http import create_release_from_build, extract_envs, get_release, start_release_environment

                for ti, tgt in enumerate(targets, start=1):
                    if not getattr(tgt, "enabled", True):
                        emit_log(f"\n--- Target[{ti}] {tgt.name}: skipped (disabled) ---")
                        continue
                    if should_stop():
                        emit_error("已取消", "由用户停止")
                        return

                    emit_log(f"\n=== Target[{ti}] {tgt.name} ===")
                    emit_log(f"--- 查找最新成功构建: def={tgt.build_id} branch={build_branch} ---")

                    bb = get_latest_successful_build(lib.base_url, proj.collection, proj.project, str(tgt.build_id), branch=build_branch, pat=pat)
                    build_id = bb.id
                    emit_log(f"找到构建: build_id={build_id} url={bb.url or ''}")

                    emit_log("开始触发 Release ...")
                    try:
                        rel = create_release_from_build(lib.base_url, proj.collection, proj.project, str(tgt.release_id), build_id=build_id, pat=pat, api_version="6.0")
                    except Exception:
                        rel = create_release_from_build(lib.base_url, proj.collection, proj.project, str(tgt.release_id), build_id=build_id, pat=pat, api_version="7.0")

                    emit_log(f"已创建 Release：id={rel.id} name={rel.name or ''} url={rel.url or ''}")

                    stage_ids = list(getattr(tgt, "release_stage_ids", []) or [])
                    want_ids = set(stage_ids)
                    want_names = set(getattr(tgt, "release_stage_names", []) or [])

                    def fetch_envs() -> list:
                        try:
                            data = get_release(lib.base_url, proj.collection, proj.project, rel.id, pat=pat, api_version="6.0")
                        except Exception:
                            data = get_release(lib.base_url, proj.collection, proj.project, rel.id, pat=pat, api_version="7.0")
                        return extract_envs(data)

                    def is_done(status: str) -> bool:
                        s = (status or "").lower()
                        return s in {"succeeded", "rejected", "canceled", "cancelled", "failed"}

                    def select_envs(envs):
                        by_def_id = [e for e in envs if (e.definition_environment_id or "") in want_ids]
                        if by_def_id:
                            return by_def_id
                        by_name = [e for e in envs if e.name in want_names]
                        if by_name:
                            return by_name
                        return []

                    timeout_sec = 60 * 60
                    start_wait = time.time()
                    deadline = start_wait + timeout_sec
                    last_line = ""
                    triggered: set[str] = set()  # 已触发部署的 envId，避免每轮重复触发

                    while time.time() < deadline:
                        if should_stop():
                            emit_error("已取消", "由用户停止")
                            return

                        envs = fetch_envs()
                        selected = select_envs(envs)
                        parts = [f"{e.name}(envId={e.id})={e.status}" for e in selected]
                        line = f"监控[{tgt.name}]：" + " | ".join(parts) if parts else f"监控[{tgt.name}]：等待阶段进入 release"
                        if line != last_line:
                            emit_log(line)
                            last_line = line

                        for e in selected:
                            if (e.status or "").lower() == "notstarted" and str(e.id) not in triggered:
                                emit_log(f"触发部署：{e.name} (envId={e.id}, defEnvId={e.definition_environment_id})")
                                start_release_environment(lib.base_url, proj.collection, proj.project, rel.id, e.id, pat=pat)
                                triggered.add(str(e.id))

                        if selected and all(is_done(e.status) for e in selected):
                            failed = [e for e in selected if (e.status or "").lower() not in ("succeeded",)]
                            if failed:
                                any_canceled = any((e.status or "").lower() in {"canceled", "cancelled"} for e in failed)
                                msg = "Release 完成但存在异常阶段：\n" + "\n".join([f"- {e.name} ({e.id}) status={e.status}" for e in failed])
                                if any_canceled:
                                    emit_error("ADO 平台已取消：Release", msg + (f"\n\n{rel.url or ''}"))
                                else:
                                    emit_error("ADO 平台报错：Release", msg + (f"\n\n{rel.url or ''}"))
                                return

                            emit_log(f"✅ Target {tgt.name} Release 成功")
                            break

                        # Responsive sleep
                        for _ in range(8):
                            if should_stop(): break
                            time.sleep(0.5)

                    else:
                        waited = int(time.time() - start_wait)
                        emit_error(
                            "发布超时",
                            "ADO 平台超时：等待 Release 阶段完成超时\n"
                            + f"target={tgt.name}\n"
                            + f"release_def_id={tgt.release_id} release_id={rel.id}\n"
                            + f"已等待={waited}s（超时={timeout_sec}s）\n"
                            + f"url={rel.url or ''}",
                        )
                        return

                notify_telegram("✅ 仅发布成功", f"{task_label}\nbranch={build_branch}\ntargets={len(targets)}")
            except Exception as ex:
                emit_error("运行异常", str(ex))
            finally:
                # 保证任何退出路径（成功/异常/停止/阶段失败/超时 return）都发一次 done，
                # 否则 flush() 不会 pop _running_tasks，运行状态会永久泄漏。
                q.put(("done", ""))

        def flush() -> None:
            finished = False
            try:
                while True:
                    kind, payload = q.get_nowait()
                    if kind == "log":
                        if isValid(card):
                            self._append_run_log(card, payload)
                    elif kind == "error":
                        parts = payload.split("\n", 1)
                        title = parts[0]
                        details = parts[1] if len(parts) > 1 else ""
                        if isValid(self.window()):
                            show_error_dialog(self.window(), title, details)
                    elif kind == "done":
                        finished = True
            except Exception:
                pass

            if finished:
                if isValid(card):
                    card.set_actions_enabled(True)
                self._running_tasks.pop(str(task_id), None)
                self._update_run_states()
                return
            QtCore.QTimer.singleShot(120, flush)

        try:
            card.set_actions_enabled(False)
            self._clear_run_log(card)
            th = threading.Thread(target=worker, daemon=True)
            th.start()
            QtCore.QTimer.singleShot(120, flush)
        except Exception as ex:
            # If thread fails to start, avoid leaving a stuck running state.
            self._running_tasks.pop(str(task_id), None)
            self._update_run_states()
            try:
                card.set_actions_enabled(True)
            except Exception:
                pass
            show_error_dialog(self.window(), "无法启动任务", str(ex))

    def _run(self, flow_id: str, card: TaskCard, *, skip_confirm: bool = False, tg_reply_chat_id: str | None = None, tg_reply_username: str | None = None) -> None:
        """Run in a background Python thread to keep UI responsive.

        Note: single-flight. Only one task can run at a time.
        """

        if self._is_task_running(str(flow_id)):
            msg = "该任务正在运行中，请等待完成或先停止"
            if tg_reply_chat_id:
                try:
                    from app_ado.secrets import get_telegram_token
                    from app_ado.notifier_telegram import send_telegram_message

                    token = get_telegram_token()
                    if token:
                        send_telegram_message(bot_token=token, chat_id=tg_reply_chat_id, text="⛔ 无法执行\n" + msg)
                except Exception:
                    pass
            show_error_dialog(self.window(), "无法执行", msg)
            return
        ts = load_task_settings()
        task = next((t for t in (ts.tasks or []) if t.id == flow_id), None)
        if not task:
            show_error_dialog(self.window(), "错误", "任务不存在")
            return

        task_label = (task.tg_desc or "").strip() or ("/" + (task.tg_command or "").strip()) or "任务"

        # basic config validation (UI thread)
        missing: list[str] = []
        local_path = (task.local_repo_path or "").strip()
        # local repo path is optional

        build_branch = (getattr(task.git_flow, "build_branch", "") or "").strip()
        update_branches = [x.strip() for x in (task.git_flow.update_branches or []) if str(x).strip()]
        merges = list(task.git_flow.merges or [])
        push_branches = [x.strip() for x in (task.git_flow.push_branches or []) if str(x).strip()]

        if not build_branch:
            missing.append("- Git流程：构建分支")

        for i, mr in enumerate(merges):
            if not (mr.source and mr.target):
                missing.append(f"- Git流程：第 {i+1} 条合并规则不完整")
                break

        targets = list(task.targets or [])
        if not targets:
            missing.append("- 发布目标（至少新增一个：构建+发布+阶段）")

        if missing:
            msg = f"请先在【代码配置】中补齐（{task_label}）：\n" + "\n".join(missing)
            if tg_reply_chat_id:
                try:
                    from app_ado.secrets import get_telegram_token
                    from app_ado.notifier_telegram import send_telegram_message

                    token = get_telegram_token()
                    if token:
                        send_telegram_message(bot_token=token, chat_id=tg_reply_chat_id, text="⚠️ 配置不完整\n" + msg)
                except Exception:
                    pass
            show_error_dialog(self.window(), "配置不完整", msg)
            return

        # Determine the branch used for build/release association.
        deploy_branch = build_branch or (merges[-1].target if merges else (update_branches[-1] if update_branches else ""))

        if not skip_confirm:
            steps: list[str] = []
            steps.append("Git 流程：")
            steps.append("1) fetch origin（涉及分支）")
            for i, br in enumerate(update_branches, start=2):
                steps.append(f"{i}) 更新分支（ff-only）：{br}")
            base_idx = 2 + len(update_branches)
            for j, mr in enumerate(merges, start=0):
                steps.append(f"{base_idx + j}) 合并：{mr.source} -> {mr.target}")
            base_idx = base_idx + len(merges)
            for k, br in enumerate(push_branches, start=0):
                steps.append(f"{base_idx + k}) 推送：{br}")

            steps.append("")
            steps.append(f"触发构建（分支：{deploy_branch}）并等待完成")
            steps.append("触发发布并监控所选阶段")

            ok = show_confirm_dialog(
                self.window(),
                "确认执行任务？",
                "\n".join(steps) + f"\n\nrepo_path={local_path}",
            )
            if not ok:
                return
        else:
            # TG-triggered: skip modal confirm.
            self._append_run_log(card, "[TG] 已跳过确认弹窗，开始执行…")

        import queue
        import threading
        import subprocess
        import shlex
        import os

        # determine notification recipient and requester identity (avoid global last_requester races)
        try:
            from app_ado.store import load_ui_settings

            s_owner = load_ui_settings()
            owner_chat = str(getattr(s_owner, "telegram_chat_id", "") or "").strip()
        except Exception:
            owner_chat = ""

        requester_chat = str(tg_reply_chat_id or "").strip()
        notify_chat_id = requester_chat or owner_chat

        # stop support (per task)
        stop_event = threading.Event()
        self._running_tasks[str(flow_id)] = {
            "stop_event": stop_event,
            "by_chat_id": requester_chat,
            "by_username": str(tg_reply_username or ""),
            "kind": "run",
            "label": task_label,
            "card": card,
        }
        self._update_run_states()

        q: queue.Queue[tuple[str, str]] = queue.Queue()
        # ('log'|'error'|'done', payload)

        def ui_call(fn):
            QtCore.QTimer.singleShot(0, fn)

        def emit_log(text: str) -> None:
            q.put(("log", text))

        def should_stop() -> bool:
            return bool(stop_event.is_set())

        # Notify policy:
        # - TG triggered: notify ONLY the requester chat.
        # - UI triggered: notify owner chat_id (ui_settings.telegram_chat_id) if configured.
        # notify_chat_id computed above

        def notify_telegram(kind: str, *, details: str = "", summary: str = "") -> None:
            """Send TG notification.

            kind: 'start'|'success'|'fail'
            If ui_settings.telegram_notify_include_details is False, only send summary.
            """
            try:
                from app_ado.store import load_ui_settings
                from app_ado.secrets import get_telegram_token
                from app_ado.notifier_telegram import send_telegram_message

                token = get_telegram_token()
                if not token:
                    return

                chat_id = notify_chat_id
                s = load_ui_settings()
                include = bool(getattr(s, "telegram_notify_include_details", False))

                if not chat_id:
                    chat_id = str(getattr(s, "telegram_chat_id", "") or "").strip()

                if not chat_id:
                    return

                text = summary
                if include and details:
                    text = summary + "\n" + details

                send_telegram_message(bot_token=token, chat_id=chat_id, text=text)
            except Exception:
                return

        def _brief_reason(title: str, details: str) -> str:
            """Return a short, user-friendly reason for TG summary.

            Keep it short to reduce leakage when details are masked.
            """
            t = (title or "").strip()
            d = (details or "").strip()

            # Prefer first meaningful stderr line for git fetch failures
            if t == "错误" and "fetch 失败" in d and "stderr:" in d:
                try:
                    seg = d.split("stderr:", 1)[1]
                    for line in seg.splitlines():
                        line = line.strip()
                        if not line or line in ("(empty)",):
                            continue
                        return line[:120]
                except Exception:
                    pass

            # Generic: first non-empty line that isn't the title
            for line in d.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line == t:
                    continue
                # common noisy prefixes
                if line.lower().startswith("stdout:") or line.lower().startswith("stderr:"):
                    continue
                return line[:120]

            return ""

        def emit_error(title: str, details: str) -> None:
            brief = _brief_reason(title, details)
            summary = f"❌ 任务失败：{title}" + (f"（{brief}）" if brief else "")
            notify_telegram(
                "fail",
                summary=summary,
                details=f"{task_label}\n{title}\n{details}",
            )
            try:
                from app_ado.task_history import TaskRunRecord, append_record
                import time as _time

                append_record(
                    TaskRunRecord(
                        ts=int(_time.time()),
                        task_id=str(task.id),
                        task_label=task_label,
                        triggered_by=("tg" if tg_reply_chat_id else "ui"),
                        requester_chat_id=str(tg_reply_chat_id or ""),
                        requester_username=str(tg_reply_username or ""),
                        result="fail",
                        summary=f"{title}",
                        details=(f"{title}\n{details}"[:1800]),
                    )
                )
            except Exception:
                pass
            q.put(("error", title + "\n" + details))

        def worker() -> None:
            try:
                # 取消来源/触发者读本任务自己的 ctx（由 stop_one_task / _stop_task_ui /
                # _stop_tasks_from_tg 在停止时写入），不要读全局 self._stop_*（按任务停止后这些全局值
                # 不再更新，会拿到陈旧/空值）。在停止发生时实时读取，而非 worker 启动时快照。
                def stop_detail(where: str) -> str:
                    ctx = self._running_tasks.get(str(flow_id)) or {}
                    src = str(ctx.get("stop_source") or "")
                    if src == "tg":
                        u = str(ctx.get("stop_requester_username") or "")
                        cid = str(ctx.get("stop_requester_chat_id") or "")
                        return f"由 TG 取消 {('@'+u) if u else ''} ({cid})\n阶段：{where}".strip()
                    if src == "ui":
                        return f"由程序界面取消\n阶段：{where}"
                    return f"已取消\n阶段：{where}"

                def emit_stopped(where: str) -> None:
                    notify_telegram(
                        "stopped",
                        summary="⏹ 任务已取消",
                        details=f"{task_label}\n" + stop_detail(where),
                    )
                    try:
                        from app_ado.task_history import TaskRunRecord, append_record
                        import time as _time

                        append_record(
                            TaskRunRecord(
                                ts=int(_time.time()),
                                task_id=str(task.id),
                                task_label=task_label,
                                triggered_by=("tg" if tg_reply_chat_id else "ui"),
                                requester_chat_id=str(tg_reply_chat_id or ""),
                                requester_username=str(tg_reply_username or ""),
                                result="stopped",
                                summary=stop_detail(where),
                                details=stop_detail(where)[:1800],
                            )
                        )
                    except Exception:
                        pass
                    q.put(("error", "已取消\n" + stop_detail(where)))
                emit_log(f"运行：{task_label}")
                emit_log(f"repo_path={local_path}")
                emit_log(f"deploy_branch={deploy_branch}")

                notify_telegram(
                    "start",
                    summary="🚀 开始执行任务",
                    details=f"{task_label}\nbranch={deploy_branch}\ntargets={len(targets)}",
                )

                def run_cmd(cmd: list[str], *, timeout: float = 300.0) -> subprocess.CompletedProcess:
                    line = "$ " + " ".join(shlex.quote(x) for x in cmd)
                    emit_log(line)
                    # local_path may be empty (remote-only mode). In that case, do not set cwd.
                    # 切断 stdin + 禁用 git 交互式认证，避免凭据弹窗等待输入而无限挂起；
                    # timeout 兜底：git 卡死时抛 TimeoutExpired，由 worker 外层 except 捕获并清理运行状态。
                    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
                    try:
                        cp = subprocess.run(
                            cmd,
                            cwd=(local_path or None),
                            capture_output=True,
                            text=True,
                            stdin=subprocess.DEVNULL,
                            env=env,
                            timeout=timeout,
                        )
                    except subprocess.TimeoutExpired:
                        emit_log(f"⏱ 命令超时（>{int(timeout)}s）：{line}")
                        raise RuntimeError(f"命令超时（>{int(timeout)}s）：{' '.join(cmd)}")
                    if cp.stdout:
                        emit_log(cp.stdout.strip())
                    if cp.stderr:
                        emit_log(cp.stderr.strip())
                    return cp

                if should_stop():
                    emit_log("已停止：用户取消")
                    emit_stopped("开始前")
                    return

                if local_path:
                    # verify git repo
                    cp = run_cmd(["git", "rev-parse", "--is-inside-work-tree"])
                    if cp.returncode != 0 or "true" not in (cp.stdout or "").lower():
                        emit_error("错误", f"不是有效的 git 仓库：{local_path}")
                        return

                    # workspace must be clean
                    cp = run_cmd(["git", "status", "--porcelain"])
                    if cp.returncode != 0:
                        emit_error("错误", "git status 失败")
                        return
                    dirty = (cp.stdout or "").strip()
                    if dirty:
                        emit_error("工作区未清理", "检测到未提交改动，请先处理后再运行：\n\n" + dirty)
                        return
                else:
                    emit_log("未配置本地仓库路径：跳过本地 git 仓库检查")

                # --- git flow ---
                if local_path:
                    branches: list[str] = []
                    seen = set()
                    for br in update_branches + push_branches:
                        if br and br not in seen:
                            branches.append(br); seen.add(br)
                    for mr in merges:
                        for br in [mr.source, mr.target]:
                            if br and br not in seen:
                                branches.append(br); seen.add(br)
                    if deploy_branch and deploy_branch not in seen:
                        branches.append(deploy_branch); seen.add(deploy_branch)

                    fetch_cmd = ["git", "fetch", "--prune", "origin"] + branches
                    cp = run_cmd(fetch_cmd)
                    if cp.returncode != 0:
                        out = (cp.stdout or "").strip()
                        err = (cp.stderr or "").strip()
                        msg = "fetch 失败"
                        if out or err:
                            msg += "\n\nstdout:\n" + (out or "(empty)") + "\n\nstderr:\n" + (err or "(empty)")
                        emit_error("错误", msg[:1800])
                        return

                    for br in update_branches:
                        if should_stop():
                            emit_log("已停止：用户取消")
                            emit_stopped(f"更新分支：{br}")
                            return
                        cp = run_cmd(["git", "checkout", br])
                        if cp.returncode != 0:
                            emit_error("错误", f"checkout 失败: {br}")
                            return
                        cp = run_cmd(["git", "pull", "--ff-only"])
                        if cp.returncode != 0:
                            emit_error("错误", f"pull 失败: {br}")
                            return

                    for mr in merges:
                        if should_stop():
                            emit_log("已停止：用户取消")
                            emit_stopped(f"合并：{mr.source}->{mr.target}")
                            return
                        cp = run_cmd(["git", "checkout", mr.target])
                        if cp.returncode != 0:
                            emit_error("错误", f"checkout 失败: {mr.target}")
                            return
                        cp = run_cmd(["git", "merge", f"origin/{mr.source}"])
                        if cp.returncode != 0:
                            # Collect conflict list first
                            cp2 = run_cmd(["git", "diff", "--name-only", "--diff-filter=U"])
                            conflicts = (cp2.stdout or "").strip()

                            # IMPORTANT: avoid leaving repo in a conflicted state.
                            # Abort merge and discard local changes so user can retry later.
                            emit_log("检测到合并失败：将自动放弃本地更改并取消合并（git merge --abort + reset --hard）")
                            try:
                                run_cmd(["git", "merge", "--abort"])
                            except Exception:
                                pass
                            try:
                                run_cmd(["git", "reset", "--hard", "HEAD"])
                            except Exception:
                                pass

                            emit_error(
                                "合并失败（可能存在冲突）",
                                f"merge 失败：{mr.source} -> {mr.target}\n\n已自动执行：git merge --abort + git reset --hard HEAD\n\n冲突文件：\n"
                                + (conflicts or "(未检测到冲突文件列表)"),
                            )
                            return

                    for br in push_branches:
                        if should_stop():
                            emit_log("已停止：用户取消")
                            emit_stopped(f"推送：{br}")
                            return
                        cp = run_cmd(["git", "push", "origin", br])
                        if cp.returncode != 0:
                            emit_error("推送失败", f"push 失败，请检查权限/分支保护。\n\nbranch={br}")
                            return

                    cp = run_cmd(["git", "rev-parse", "HEAD"])
                    head = (cp.stdout or "").strip() if cp.returncode == 0 else ""
                    emit_log("✅ Git 流程完成" + (f"\nHEAD={head}" if head else ""))
                else:
                    # No local repo. Try remote merge via ADO API if git rules exist.
                    if push_branches:
                        emit_error("无法执行", "未配置本地仓库路径时，暂不支持远程 push_branches。请清空 push_branches 或配置本地仓库路径。")
                        return
                    if merges:
                        try:
                            from app_ado.store import load_ui_settings
                            from app_ado.secrets import get_pat
                            from app_ado.ado_git_ops import merge_via_pr

                            settings2 = load_ui_settings()
                            proj2 = next((p for p in settings2.projects if p.id == task.project_id), None)
                            if not proj2:
                                emit_error("无法执行", "找不到项目配置（project_id）")
                                return
                            lib2 = next((l for l in settings2.libraries if l.id == proj2.library_id), None)
                            if not lib2:
                                emit_error("无法执行", "项目未关联代码库")
                                return
                            pat2 = get_pat(lib2.id)
                            if not pat2:
                                emit_error("无法执行", "未找到 PAT（无法使用远程合并）")
                                return
                            if not task.repo_id:
                                emit_error("无法执行", "未选择 Repo（repo_id），无法使用远程合并")
                                return

                            for mr in merges:
                                if should_stop():
                                    emit_log("已停止：用户取消")
                                    return
                                emit_log(f"远程合并(PR)：{mr.source} -> {mr.target}")
                                pr = merge_via_pr(
                                    lib2.base_url,
                                    proj2.collection,
                                    proj2.project,
                                    task.repo_id,
                                    source_branch=mr.source,
                                    target_branch=mr.target,
                                    pat=pat2,
                                )
                                emit_log(f"✅ 已完成远程合并 PR#{pr.id}")
                        except Exception as ex:
                            emit_error("远程合并失败", str(ex))
                            return
                    else:
                        emit_log("跳过 Git 流程：未配置本地仓库路径，且没有 merge/push 规则")

                # notification policy: only start + final result

                if should_stop():
                    emit_log("已停止：用户取消")
                    return

                # ---- Build+Release for each target (serial) ----
                from app_ado.store import load_ui_settings
                from app_ado.secrets import get_pat
                from app_ado.ado_build_http import (
                    get_build,
                    get_pipeline_run,
                    trigger_build_definition,
                    trigger_pipeline_run,
                    wait_build,
                    wait_pipeline,
                    find_matching_run,
                    is_pipeline_running,
                    is_build_running,
                )

                settings = load_ui_settings()
                proj = next((p for p in settings.projects if p.id == task.project_id), None)
                if not proj:
                    emit_error("错误", "找不到项目配置（project_id）")
                    return
                lib = next((l for l in settings.libraries if l.id == proj.library_id), None)
                if not lib:
                    emit_error("错误", "找不到代码库配置（library_id）")
                    return
                pat = get_pat(lib.id)
                if not pat:
                    emit_error("错误", "该代码库未保存 PAT")
                    return

                # ---- Build+Release for each target (serial) ----
                from app_ado.ado_release_http import create_release_from_build
                from app_ado.ado_release_http import extract_envs, get_release, start_release_environment
                import time

                branch = deploy_branch

                for ti, tgt in enumerate(targets, start=1):
                    release_started = False
                    build_started = False
                    build_kind = ""
                    build_ident = ""  # run_id or build_id

                    if not getattr(tgt, "enabled", True):
                        emit_log(f"\n--- Target[{ti}] {tgt.name}: skipped (disabled) ---")
                        continue

                    if should_stop():
                        emit_log("已停止：用户取消")
                        emit_stopped("远程合并")
                        return

                    emit_log(f"\n=== Target[{ti}] {tgt.name} ===")
                    emit_log(f"--- Build: kind={tgt.build_kind} id={tgt.build_id} branch={branch} ---")

                    build_run_id: str | None = None

                    # Agent-pool override only works through the Build API (queue:{id});
                    # the pipelines/runs API has no pool field. So when a pool is set,
                    # trigger via the classic Build path (these defs run via both APIs).
                    queue_override = getattr(task, "agent_queue_id", None) or None
                    if queue_override:
                        emit_log(f"--- 代理程式集区覆盖：queue_id={queue_override} → 走 Build API 触发 ---")

                    if tgt.build_kind == "pipeline" and not queue_override:
                        existing = find_matching_run(lib.base_url, proj.collection, proj.project, "pipeline", tgt.build_id, branch=branch, pat=pat)
                        if existing and is_pipeline_running(existing.state):
                            pr = existing
                            build_run_id = pr.run_id
                            build_started = True
                            build_kind = "pipeline"
                            build_ident = pr.run_id
                            emit_log(f"检测到正在运行的 Pipeline (自动触发或手动冲突)：run_id={pr.run_id} state={pr.state} url={pr.url or ''}")
                        else:
                            pr = trigger_pipeline_run(lib.base_url, proj.collection, proj.project, tgt.build_id, branch=branch, pat=pat)
                            build_run_id = pr.run_id
                            build_started = True
                            build_kind = "pipeline"
                            build_ident = pr.run_id
                            emit_log(f"已触发 Pipeline：run_id={pr.run_id} state={pr.state} url={pr.url or ''}")
                        timeout_sec = 30 * 60
                        start_wait = time.time()
                        deadline = start_wait + timeout_sec
                        pr2 = None
                        while time.time() < deadline:
                            if should_stop():
                                emit_log("已停止：用户取消（构建已触发：将尝试取消 ADO 构建）")
                                # try cancel build on ADO if release not started
                                if build_started and not release_started:
                                    try:
                                        from app_ado.ado_build_http import cancel_pipeline_run

                                        cancel_pipeline_run(lib.base_url, proj.collection, proj.project, tgt.build_id, pr.run_id, pat=pat)
                                        emit_log("✅ 已向 ADO 请求取消 Pipeline")
                                    except Exception as ex:
                                        # 403: usually permission; 404: usually server endpoint not supported (we also fallback inside cancel_pipeline_run)
                                        emit_log(f"⚠️ ADO 取消 Pipeline 失败（可能是权限不足或服务器不支持该取消接口）：{ex}")
                                emit_stopped("等待构建")
                                return
                            pr_cur = get_pipeline_run(lib.base_url, proj.collection, proj.project, tgt.build_id, pr.run_id, pat=pat)
                            if (pr_cur.state or "").lower() == "completed":
                                pr2 = pr_cur
                                break
                            # Responsive sleep
                            for _ in range(8):
                                if should_stop():
                                    break
                                time.sleep(0.5)
                        if pr2 is None:
                            waited = int(time.time() - start_wait)
                            emit_error(
                                "构建超时",
                                "ADO 平台超时：等待 Pipeline 完成超时\n"
                                + f"target={tgt.name}\n"
                                + f"pipeline_id={tgt.build_id} run_id={pr.run_id}\n"
                                + f"branch={branch}\n"
                                + f"已等待={waited}s（超时={timeout_sec}s）\n"
                                + f"url={pr.url or ''}",
                            )
                            return
                        emit_log(f"Pipeline 完成：state={pr2.state} result={pr2.result} url={pr2.url or ''}")
                        res_raw = (pr2.result or "")
                        res = res_raw.lower()
                        if res in ("canceled", "cancelled"):
                            emit_error(
                                "ADO 平台已取消：Pipeline",
                                f"Azure DevOps Pipeline result={res_raw}\n{pr2.url or ''}",
                            )
                            return
                        if res not in ("succeeded", "success"):
                            emit_error(
                                "ADO 平台报错：Pipeline",
                                f"Azure DevOps Pipeline result={res_raw}\n{pr2.url or ''}",
                            )
                            return
                    else:
                        existing_b = find_matching_run(lib.base_url, proj.collection, proj.project, "build_definition", tgt.build_id, branch=branch, pat=pat)
                        if existing_b and is_build_running(existing_b.status):
                            brn = existing_b
                            build_run_id = brn.build_id
                            build_started = True
                            build_kind = "build_definition"
                            build_ident = brn.build_id
                            emit_log(f"检测到正在运行的 Build (自动触发或手动冲突)：build_id={brn.build_id} status={brn.status} url={brn.url or ''}")
                        else:
                            brn = trigger_build_definition(lib.base_url, proj.collection, proj.project, tgt.build_id, branch=branch, pat=pat, queue_id=getattr(task, "agent_queue_id", None))
                            build_run_id = brn.build_id
                            build_started = True
                            build_kind = "build_definition"
                            build_ident = brn.build_id
                            emit_log(f"已触发 Build：build_id={brn.build_id} status={brn.status} url={brn.url or ''}")

                        # wait build with cancel support
                        timeout_sec = 30 * 60
                        start_wait = time.time()
                        deadline = start_wait + timeout_sec
                        br2 = None
                        while time.time() < deadline:
                            if should_stop():
                                emit_log("已停止：用户取消（构建已触发，停止后不会回滚）")
                                if build_started and not release_started:
                                    try:
                                        from app_ado.ado_build_http import cancel_build

                                        cancel_build(lib.base_url, proj.collection, proj.project, brn.build_id, pat=pat)
                                        emit_log("✅ 已向 ADO 请求取消 Build")
                                    except Exception as ex:
                                        emit_log(f"⚠️ ADO 取消 Build 失败：{ex}")
                                emit_stopped("等待构建")
                                return
                            cur = get_build(lib.base_url, proj.collection, proj.project, brn.build_id, pat=pat)
                            if (cur.status or "").lower() == "completed":
                                br2 = cur
                                break
                            # Responsive sleep
                            for _ in range(8):
                                if should_stop():
                                    break
                                time.sleep(0.5)

                        if br2 is None:
                            waited = int(time.time() - start_wait)
                            emit_error(
                                "构建超时",
                                "ADO 平台超时：等待 Build 完成超时\n"
                                + f"target={tgt.name}\n"
                                + f"build_def_id={tgt.build_id} build_id={brn.build_id}\n"
                                + f"branch={branch}\n"
                                + f"已等待={waited}s（超时={timeout_sec}s）\n"
                                + f"url={brn.url or ''}",
                            )
                            return

                        emit_log(f"Build 完成：status={br2.status} result={br2.result} url={br2.url or ''}")
                        res_raw = (br2.result or "")
                        res = res_raw.lower()
                        if res in ("canceled", "cancelled"):
                            emit_error(
                                "ADO 平台已取消：Build",
                                f"Azure DevOps Build result={res_raw}\n{br2.url or ''}",
                            )
                            return
                        if res not in ("succeeded", "success", "partiallysucceeded"):
                            emit_error(
                                "ADO 平台报错：Build",
                                f"Azure DevOps Build result={res_raw}\n{br2.url or ''}",
                            )
                            return

                    emit_log("✅ 构建成功，开始触发 Release ...")
                    release_started = True

                    if not build_run_id:
                        emit_error("错误", "未获得 build_id/run_id，无法创建 Release")
                        return

                    stage_ids = list(getattr(tgt, "release_stage_ids", []) or [])
                    emit_log(f"--- Release: def_id={tgt.release_id} build_id={build_run_id} stages={','.join(stage_ids)} ---")

                    try:
                        rel = create_release_from_build(
                            lib.base_url,
                            proj.collection,
                            proj.project,
                            tgt.release_id,
                            build_id=build_run_id,
                            pat=pat,
                            api_version="6.0",
                        )
                    except Exception:
                        rel = create_release_from_build(
                            lib.base_url,
                            proj.collection,
                            proj.project,
                            tgt.release_id,
                            build_id=build_run_id,
                            pat=pat,
                            api_version="7.0",
                        )

                    emit_log(f"已创建 Release：id={rel.id} name={rel.name or ''} url={rel.url or ''}")

                    def fetch_envs() -> list:
                        try:
                            data = get_release(lib.base_url, proj.collection, proj.project, rel.id, pat=pat, api_version="6.0")
                        except Exception:
                            data = get_release(lib.base_url, proj.collection, proj.project, rel.id, pat=pat, api_version="7.0")
                        return extract_envs(data)

                    def is_done(status: str) -> bool:
                        s = (status or "").lower()
                        return s in {"succeeded", "rejected", "canceled", "failed"}

                    want_ids = set(stage_ids)
                    want_names = set(getattr(tgt, "release_stage_names", []) or [])
                    timeout_sec = 60 * 60
                    start_wait = time.time()
                    deadline = start_wait + timeout_sec
                    last_line = ""
                    triggered: set[str] = set()  # 已触发部署的 envId，避免每轮重复触发

                    def select_envs(envs):
                        by_def_id = [e for e in envs if (e.definition_environment_id or "") in want_ids]
                        if by_def_id:
                            return by_def_id, "definitionEnvironmentId"
                        by_name = [e for e in envs if e.name in want_names]
                        if by_name:
                            return by_name, "name"
                        return [], "none"

                    while time.time() < deadline:
                        if should_stop():
                            emit_log("已停止：用户取消（发布已触发，停止后不会回滚）")
                            emit_stopped("等待发布")
                            return

                        envs = fetch_envs()
                        selected, mode = select_envs(envs)
                        parts = [f"{e.name}(defEnvId={e.definition_environment_id}, envId={e.id})={e.status}" for e in selected]
                        line = f"监控[{tgt.name}](mode={mode})：" + " | ".join(parts) if parts else f"监控[{tgt.name}]：等待阶段进入 release"
                        if line != last_line:
                            emit_log(line)
                            last_line = line

                        for e in selected:
                            if (e.status or "").lower() == "notstarted" and str(e.id) not in triggered:
                                emit_log(f"触发部署：{e.name} (envId={e.id}, defEnvId={e.definition_environment_id})")
                                start_release_environment(lib.base_url, proj.collection, proj.project, rel.id, e.id, pat=pat)
                                triggered.add(str(e.id))

                        if selected and all(is_done(e.status) for e in selected):
                            failed = [e for e in selected if (e.status or "").lower() not in ("succeeded",)]
                            if failed:
                                any_canceled = any((e.status or "").lower() in {"canceled", "cancelled"} for e in failed)
                                msg = "Release 完成但存在失败阶段：\n" + "\n".join([f"- {e.name} ({e.id}) status={e.status}" for e in failed])
                                if any_canceled:
                                    emit_error("ADO 平台已取消：Release", msg + (f"\n\n{rel.url or ''}"))
                                else:
                                    emit_error("ADO 平台报错：Release", msg + (f"\n\n{rel.url or ''}"))
                                return
                            emit_log(f"✅ Target {tgt.name} Release 成功")
                            break

                        for _ in range(10):
                            if should_stop():
                                emit_log("已停止：用户取消（发布已触发，停止后不会回滚）")
                                return
                            time.sleep(1.0)

                    else:
                        waited = int(time.time() - start_wait)
                        stages = ",".join(stage_ids)
                        emit_error(
                            "发布超时",
                            "ADO 平台超时：等待 Release 阶段完成超时\n"
                            + f"target={tgt.name}\n"
                            + f"release_def_id={tgt.release_id} release_id={rel.id}\n"
                            + f"stages={stages}\n"
                            + f"已等待={waited}s（超时={timeout_sec}s）\n"
                            + f"url={rel.url or ''}",
                        )
                        return

                # all targets done
                last_url = rel.url if 'rel' in locals() and rel else ""
                notify_telegram(
                    "success",
                    summary="✅ 任务成功",
                    details=f"{task_label}\nbranch={deploy_branch}\ntargets={len(targets)}\n{last_url}",
                )

                try:
                    from app_ado.task_history import TaskRunRecord, append_record
                    import time as _time

                    append_record(
                        TaskRunRecord(
                            ts=int(_time.time()),
                            task_id=str(task.id),
                            task_label=task_label,
                            triggered_by=("tg" if tg_reply_chat_id else "ui"),
                            requester_chat_id=str(tg_reply_chat_id or ""),
                            requester_username=str(tg_reply_username or ""),
                            result="success",
                            summary=f"GitFlow完成; 发布targets={len(targets)}",
                        )
                    )
                except Exception:
                    pass

                return

            except Exception as e:
                emit_error("运行异常", str(e))
            finally:
                q.put(("done", ""))

        # UI init
        card.set_actions_enabled(False)
        self._clear_run_log(card)
        self._active_log_dialog = RunLogDialog(self.window(), title=f"运行：{task_label}")
        self._active_log_dialog.show()

        def flush():
            finished = False
            try:
                while True:
                    kind, payload = q.get_nowait()
                    if kind == "log":
                        if isValid(card):
                            self._append_run_log(card, payload)
                        if hasattr(self, "_active_log_dialog") and isValid(self._active_log_dialog):
                            self._active_log_dialog.log(payload)
                    elif kind == "error":
                        parts = payload.split("\n", 1)
                        title = parts[0]
                        details = parts[1] if len(parts) > 1 else ""
                        if isValid(self.window()):
                            show_error_dialog(self.window(), title, details)
                    elif kind == "done":
                        finished = True
            except Exception:
                pass

            if finished:
                if isValid(card):
                    card.set_actions_enabled(True)
                self._running_tasks.pop(str(flow_id), None)
                self._update_run_states()
                # Clear dialog reference once task is done
                if hasattr(self, "_active_log_dialog"):
                    del self._active_log_dialog
                return
            QtCore.QTimer.singleShot(120, flush)

        try:
            th = threading.Thread(target=worker, daemon=True)
            th.start()
            QtCore.QTimer.singleShot(120, flush)
        except Exception as ex:
            self._running_tasks.pop(str(flow_id), None)
            self._update_run_states()
            try:
                card.set_actions_enabled(True)
            except Exception:
                pass
            show_error_dialog(self.window(), "无法启动任务", str(ex))

    def _stop_task_ui(self, task_id: str) -> None:
        ctx = self._running_tasks.get(str(task_id))
        if not ctx:
            return

        label = str(ctx.get("label") or task_id)
        ok = show_confirm_dialog(
            self.window(),
            "确认停止？",
            f"停止任务：{label}\n\n说明：将尽快停止本地等待/监控流程；已触发的构建/发布不会自动回滚。",
        )
        if not ok:
            return

        # loading state
        try:
            card = ctx.get("card")
            if card:
                card.set_stop_pending(True)
                card.append_log("停止中…")
        except Exception:
            pass

        ctx["stop_source"] = "ui"
        try:
            ev = ctx.get("stop_event")
            if ev:
                ev.set()
        except Exception:
            pass

    def _stop_tasks_from_tg(self) -> None:
        """Stop tasks triggered by requester (or owner stops all)."""
        try:
            from app_ado.store import load_ui_settings

            s = load_ui_settings()
            owner = str(s.telegram_chat_id or "")
        except Exception:
            owner = ""

        req = str(self._stop_requester_chat_id or "")
        is_owner = bool(owner and req and req == owner)

        for tid, ctx in list(self._running_tasks.items()):
            by_chat = str(ctx.get("by_chat_id") or "")
            if not is_owner and (not req or req != by_chat):
                continue
            ctx["stop_source"] = "tg"
            ctx["stop_requester_chat_id"] = req
            ctx["stop_requester_username"] = str(self._stop_requester_username or "")
            try:
                ev = ctx.get("stop_event")
                if ev:
                    ev.set()
            except Exception:
                pass
            try:
                card = ctx.get("card")
                if card:
                    card.append_log("收到停止请求[TG]：将尽快停止（不回滚已触发的构建/发布）")
            except Exception:
                pass
