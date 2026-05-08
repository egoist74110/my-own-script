from __future__ import annotations

import math
import threading

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import CardWidget, ComboBox, InfoBar, InfoBarPosition, LineEdit, PushButton

from app_ado.ado_work_item_http import WorkItem, get_descendant_work_items, get_work_item, list_work_items_by_board_column_value
from app_ado.ai_policy import evaluate_change_policy, load_effective_ai_change_policy
from app_ado.ai_work_item_flow import build_mcp_prompt, build_prompt, load_work_item_context, open_ai_in_terminal, selected_ai_profile, selected_local_repo
from app_ado.models import ProjectEntry, project_entry_collection, project_entry_id, project_entry_library_id, project_entry_name
from app_ado.secrets import get_pat
from app_ado.store import load_ui_settings, save_ui_settings
from app_ado.ui.dialogs import show_error_dialog
from ok.gui.widget.Tab import Tab


BOARD_COLUMNS = ["新建", "待开发", "开发中", "测试", "已关闭"]
PAGE_SIZES = [5, 10, 50, 100, 200]


class WorkItemMiniCard(CardWidget):
    analyze_clicked = QtCore.Signal(int)
    fix_clicked = QtCore.Signal(int)
    mcp_clicked = QtCore.Signal(int)
    related_clicked = QtCore.Signal(int)

    def __init__(self, item: WorkItem, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QtWidgets.QLabel(f"#{item.id} {item.title}")
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: 600;")

        meta = QtWidgets.QLabel(
            f"状态：{item.state or '-'}\n"
            f"指派：{item.assigned_to or '-'}\n"
            f"类型：{item.work_item_type or '-'}"
        )
        meta.setWordWrap(True)
        meta.setStyleSheet("color:#666;")

        row = QtWidgets.QHBoxLayout()
        self.btn_analyze = PushButton("分析")
        self.btn_fix = PushButton("修复")
        self.btn_mcp = PushButton("MCP")
        self.btn_related = PushButton("关联单")
        self.btn_analyze.setFixedWidth(72)
        self.btn_fix.setFixedWidth(72)
        self.btn_mcp.setFixedWidth(72)
        self.btn_related.setFixedWidth(72)
        row.addWidget(self.btn_analyze)
        row.addWidget(self.btn_fix)
        row.addWidget(self.btn_mcp)
        row.addWidget(self.btn_related)
        row.addStretch(1)

        self.btn_analyze.clicked.connect(lambda: self.analyze_clicked.emit(self.item.id))
        self.btn_fix.clicked.connect(lambda: self.fix_clicked.emit(self.item.id))
        self.btn_mcp.clicked.connect(lambda: self.mcp_clicked.emit(self.item.id))
        self.btn_related.clicked.connect(lambda: self.related_clicked.emit(self.item.id))

        root.addWidget(title)
        root.addWidget(meta)
        root.addLayout(row)


class RelatedWorkItemsDialog(QtWidgets.QDialog):
    analyze_requested = QtCore.Signal(int)
    fix_requested = QtCore.Signal(int)
    mcp_requested = QtCore.Signal(int)

    def __init__(
        self,
        root_id: int,
        library,
        project: ProjectEntry,
        pat: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._root_id = int(root_id)
        self._library = library
        self._project = project
        self._pat = pat

        self.setWindowTitle(f"#{self._root_id} 关联单")
        self.resize(560, 640)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        self.title_label = QtWidgets.QLabel(f"#{self._root_id} 关联单（含子项）")
        self.title_label.setStyleSheet("font-weight: 600;")
        self.btn_refresh = PushButton("刷新")
        self.btn_close = PushButton("关闭")
        self.btn_refresh.setFixedWidth(80)
        self.btn_close.setFixedWidth(80)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.btn_refresh)
        header.addWidget(self.btn_close)
        outer.addLayout(header)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.list_view = QtWidgets.QWidget()
        self.list_layout = QtWidgets.QVBoxLayout(self.list_view)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list_view)
        outer.addWidget(self.scroll, 1)

        self.btn_refresh.clicked.connect(self._reload)
        self.btn_close.clicked.connect(self.reject)

        QtCore.QTimer.singleShot(0, self._reload)

    def _clear_list(self) -> None:
        while self.list_layout.count():
            entry = self.list_layout.takeAt(0)
            w = entry.widget()
            if w is not None:
                w.deleteLater()
        self.list_layout.addStretch(1)

    def _show_message(self, text: str) -> None:
        self._clear_list()
        label = QtWidgets.QLabel(text)
        label.setStyleSheet("color:#666; padding:16px;")
        label.setAlignment(QtCore.Qt.AlignCenter)
        self.list_layout.insertWidget(0, label)

    def _add_card(self, item: WorkItem, *, is_root: bool) -> None:
        card = WorkItemMiniCard(item)
        if is_root:
            card.setStyleSheet("WorkItemMiniCard { border:1px solid #d0d7de; }")
        card.analyze_clicked.connect(self.analyze_requested.emit)
        card.fix_clicked.connect(self.fix_requested.emit)
        card.mcp_clicked.connect(self.mcp_requested.emit)
        card.related_clicked.connect(lambda _wid: None)
        card.btn_related.setEnabled(False)
        self.list_layout.insertWidget(self.list_layout.count() - 1, card)

    def _reload(self) -> None:
        self.btn_refresh.setEnabled(False)
        self._show_message("加载中…")

        result: dict = {}

        def run() -> None:
            try:
                root = get_work_item(
                    self._library.base_url,
                    self._root_id,
                    collection=self._project.collection,
                    project=self._project.project,
                    pat=self._pat,
                )
                children = get_descendant_work_items(
                    self._library.base_url,
                    self._root_id,
                    collection=self._project.collection,
                    project=self._project.project,
                    pat=self._pat,
                )
                result["root"] = root
                result["children"] = children
            except Exception as exc:
                result["error"] = exc

            QtCore.QTimer.singleShot(0, finish)

        def finish() -> None:
            self.btn_refresh.setEnabled(True)
            err = result.get("error")
            if err is not None:
                self._show_message(f"加载失败：{err}")
                return
            root = result.get("root")
            children = result.get("children") or []
            self._clear_list()
            if root is not None:
                self._add_card(root, is_root=True)
            for child in children:
                self._add_card(child, is_root=False)
            self.title_label.setText(
                f"#{self._root_id} 关联单（含 {len(children)} 个子项）"
            )
            if not children:
                hint = QtWidgets.QLabel("没有子项工单。")
                hint.setStyleSheet("color:#666; padding:8px;")
                self.list_layout.insertWidget(self.list_layout.count() - 1, hint)

        threading.Thread(target=run, daemon=True).start()


class WorkItemsTab(Tab):
    icon = None
    name = "工单"

    def __init__(self):
        super().__init__()
        self._loaded_items: list[WorkItem] = []
        self._filtered_items: list[WorkItem] = []
        self._current_page: int = 1
        self.list_scroll: QtWidgets.QScrollArea | None = None
        self.list_view: QtWidgets.QWidget | None = None
        self.list_layout: QtWidgets.QVBoxLayout | None = None

        self._build_filter_card()
        self._build_pagination_card()
        self._build_list_area()

        QtCore.QTimer.singleShot(120, self._refresh)

    def _toast(self, title: str, content: str, ok: bool = True) -> None:
        if ok:
            InfoBar.success(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
        else:
            InfoBar.error(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    def _build_filter_card(self) -> None:
        w = CardWidget(self)
        form = QtWidgets.QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.project_combo = ComboBox()
        self.project_combo.setFixedWidth(260)
        self.btn_refresh_projects = PushButton("刷新项目")
        self.btn_refresh_projects.setFixedWidth(88)

        self.column_combo = ComboBox()
        self.column_combo.setFixedWidth(180)
        for name in BOARD_COLUMNS:
            self.column_combo.addItem(name, userData=name)

        self.search_edit = LineEdit()
        self.search_edit.setPlaceholderText("搜索工单标题 / 编号")

        self.assignee_edit = LineEdit()
        self.assignee_edit.setPlaceholderText("过滤指派对象（模糊）")

        self.btn_refresh = PushButton("刷新")
        self.btn_refresh.setFixedWidth(88)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_refresh)
        row.addStretch(1)

        form.addRow("项目", self._row(self.project_combo, self.btn_refresh_projects))
        form.addRow("版块", self.column_combo)
        form.addRow("搜索工单", self.search_edit)
        form.addRow("过滤指派", self.assignee_edit)
        form.addRow(row)

        self.project_combo.currentIndexChanged.connect(self._save_selection_state)
        self.btn_refresh_projects.clicked.connect(self._reload_projects)
        self.column_combo.currentIndexChanged.connect(self._on_column_changed)
        self.search_edit.textChanged.connect(self._apply_filters)
        self.assignee_edit.textChanged.connect(self._apply_filters)
        self.btn_refresh.clicked.connect(self._refresh)

        self.add_card("工单筛选", w)
        self._load_filter_state()

    def _build_pagination_card(self) -> None:
        w = CardWidget(self)
        form = QtWidgets.QHBoxLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)

        self.page_size_combo = ComboBox()
        self.page_size_combo.setFixedWidth(100)
        for size in PAGE_SIZES:
            self.page_size_combo.addItem(str(size), userData=size)

        self.lbl_page = QtWidgets.QLabel("第 1 / 1 页")
        self.page_edit = LineEdit()
        self.page_edit.setFixedWidth(80)
        self.page_edit.setPlaceholderText("页码")
        self.btn_go_page = PushButton("跳转")
        self.btn_prev = PushButton("上一页")
        self.btn_next = PushButton("下一页")

        form.addWidget(QtWidgets.QLabel("每页"))
        form.addWidget(self.page_size_combo)
        form.addWidget(self.lbl_page)
        form.addWidget(self.page_edit)
        form.addWidget(self.btn_go_page)
        form.addWidget(self.btn_prev)
        form.addWidget(self.btn_next)
        form.addStretch(1)

        self.page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)
        self.btn_go_page.clicked.connect(self._go_to_page)
        self.btn_prev.clicked.connect(lambda: self._set_page(self._current_page - 1))
        self.btn_next.clicked.connect(lambda: self._set_page(self._current_page + 1))

        self.add_card("分页", w)
        self._load_page_size_state()

    def _row(self, a: QtWidgets.QWidget, b: QtWidgets.QWidget) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(a)
        h.addWidget(b)
        h.addStretch(1)
        return w

    def _build_list_area(self) -> None:
        self.list_scroll = QtWidgets.QScrollArea(self)
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.list_scroll.setStyleSheet("QScrollArea{border:0;background:transparent;}")

        self.list_view = QtWidgets.QWidget()
        self.list_layout = QtWidgets.QVBoxLayout(self.list_view)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.setAlignment(QtCore.Qt.AlignTop)

        self.list_scroll.setWidget(self.list_view)
        self.add_widget(self.list_scroll)

    def _load_filter_state(self) -> None:
        settings = load_ui_settings()
        selected_project = settings.work_items_project_id or settings.active_project_id
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        idx = 0
        for p in settings.projects:
            project_id = project_entry_id(p)
            project_name = project_entry_name(p)
            if not project_id or not project_name:
                continue
            i = self.project_combo.count()
            self.project_combo.addItem(project_name, userData=project_id)
            if selected_project and project_id == selected_project:
                idx = i
        if self.project_combo.count() > 0:
            self.project_combo.setCurrentIndex(idx)
        self.project_combo.blockSignals(False)

        selected_column = settings.work_items_board.strip() if (settings.work_items_board or "").strip() else "开发中"
        for i in range(self.column_combo.count()):
            if self.column_combo.itemData(i) == selected_column:
                self.column_combo.setCurrentIndex(i)
                break

    def _reload_projects(self) -> None:
        prev_project_id = str(self.project_combo.currentData() or "")
        settings = load_ui_settings()
        if prev_project_id:
            settings.work_items_project_id = prev_project_id
            save_ui_settings(settings)
        self._load_filter_state()
        self._refresh()

    def _load_page_size_state(self) -> None:
        default_size = 5
        for i in range(self.page_size_combo.count()):
            if int(self.page_size_combo.itemData(i)) == default_size:
                self.page_size_combo.setCurrentIndex(i)
                break

    def _save_selection_state(self) -> None:
        settings = load_ui_settings()
        settings.work_items_project_id = str(self.project_combo.currentData() or "")
        settings.work_items_board = str(self.column_combo.currentData() or "开发中")
        save_ui_settings(settings)


    def _selected_project(self):
        settings = load_ui_settings()
        pid = self.project_combo.currentData() or settings.active_project_id
        return next((x for x in settings.projects if project_entry_id(x) == pid), None)

    def _normalized_project(self, project) -> ProjectEntry:
        project_id = project_entry_id(project)
        library_id = project_entry_library_id(project)
        collection = project_entry_collection(project)
        project_name = project_entry_name(project)
        if not project_id or not library_id or not collection or not project_name:
            raise RuntimeError("项目配置缺少必要字段（id/library_id/collection/project）")
        return ProjectEntry(
            id=project_id,
            library_id=library_id,
            collection=collection,
            project=project_name,
        )

    def _current_context(self) -> tuple[object, ProjectEntry, str]:
        settings = load_ui_settings()
        raw_proj = self._selected_project()
        if raw_proj is None:
            raise RuntimeError("请先在【代码配置】里新增并选择项目")
        proj = self._normalized_project(raw_proj)
        library_id = proj.library_id
        lib = next((x for x in settings.libraries if x.id == library_id), None)
        if lib is None:
            raise RuntimeError("请先在【代码配置】里选择代码库")
        pat = get_pat(lib.id)
        if not pat:
            raise RuntimeError(f"当前代码库未配置 PAT：{lib.name}")
        return lib, proj, pat

    def _on_column_changed(self) -> None:
        self._save_selection_state()
        self._refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._reload_projects)

    def _refresh(self) -> None:
        proj = self._selected_project()
        if proj is None:
            self._render_empty("请先选择项目")
            return

        self._save_selection_state()
        self.btn_refresh.setEnabled(False)
        self._render_empty("正在加载工单…")

        column_name = str(self.column_combo.currentData() or "开发中")

        def run() -> None:
            payload: dict[str, object] = {}
            try:
                lib, proj2, pat = self._current_context()
                payload["items"] = list_work_items_by_board_column_value(
                    lib.base_url,
                    proj2.collection,
                    proj2.project,
                    column_name,
                    pat=pat,
                )
            except Exception as e:
                payload["error"] = str(e)

            def finish() -> None:
                self.btn_refresh.setEnabled(True)
                if "error" in payload:
                    self._render_empty("加载失败")
                    show_error_dialog(self, "工单加载失败", str(payload["error"]))
                    return
                self._loaded_items = list(payload.get("items") or [])
                self._current_page = 1
                self._apply_filters()
                self._toast("已刷新", f"{column_name} 共 {len(self._loaded_items)} 条")

            QtCore.QTimer.singleShot(0, self, finish)

        threading.Thread(target=run, daemon=True).start()

    def _apply_filters(self) -> None:
        keyword = (self.search_edit.text() or "").strip().lower()
        assignee = (self.assignee_edit.text() or "").strip().lower()

        items = list(self._loaded_items)
        if keyword:
            items = [
                x for x in items
                if keyword in str(x.id).lower() or keyword in (x.title or "").lower()
            ]
        if assignee:
            items = [
                x for x in items
                if assignee in (x.assigned_to or "").lower()
            ]

        self._filtered_items = items
        self._set_page(1, keep_if_valid=False)

    def _page_size(self) -> int:
        return int(self.page_size_combo.currentData() or 5)

    def _page_count(self) -> int:
        if not self._filtered_items:
            return 1
        return max(1, math.ceil(len(self._filtered_items) / self._page_size()))

    def _set_page(self, page: int, *, keep_if_valid: bool = True) -> None:
        total = self._page_count()
        if keep_if_valid:
            page = min(max(1, page), total)
        else:
            page = 1 if total > 0 else 1
        self._current_page = page
        self._render_page()

    def _on_page_size_changed(self) -> None:
        self._set_page(1, keep_if_valid=False)

    def _go_to_page(self) -> None:
        text = self.page_edit.text().strip()
        if not text:
            return
        try:
            page = int(text)
        except ValueError:
            show_error_dialog(self, "错误", "页码必须是数字")
            return
        self._set_page(page)

    def _clear_list(self) -> None:
        if self.list_layout is None:
            return
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_empty(self, text: str) -> None:
        if self.list_layout is None:
            return
        self._clear_list()
        label = QtWidgets.QLabel(text)
        label.setStyleSheet("color:#666;")
        label.setAlignment(QtCore.Qt.AlignCenter)
        self.list_layout.addWidget(label)
        self.lbl_page.setText("第 1 / 1 页")
        self.btn_prev.setEnabled(False)
        self.btn_next.setEnabled(False)

    def _render_page(self) -> None:
        if self.list_layout is None or self.list_view is None:
            return
        self._clear_list()
        total_items = len(self._filtered_items)
        total_pages = self._page_count()
        size = self._page_size()
        start = (self._current_page - 1) * size
        end = start + size
        page_items = self._filtered_items[start:end]

        if not page_items:
            self._render_empty("当前筛选条件下暂无工单")
            return

        for work_item in page_items:
            item_card = WorkItemMiniCard(work_item, self.list_view)
            item_card.analyze_clicked.connect(self._analyze_item)
            item_card.fix_clicked.connect(self._fix_item)
            item_card.mcp_clicked.connect(self._copy_mcp_item_prompt)
            item_card.related_clicked.connect(self._open_related_dialog)
            self.list_layout.addWidget(item_card)

        self.lbl_page.setText(f"第 {self._current_page} / {total_pages} 页  共 {total_items} 条")
        self.btn_prev.setEnabled(self._current_page > 1)
        self.btn_next.setEnabled(self._current_page < total_pages)

    def _analyze_item(self, work_item_id: int) -> None:
        self._run_ai_flow(work_item_id, mode="analyze")

    def _fix_item(self, work_item_id: int) -> None:
        self._run_ai_flow(work_item_id, mode="fix")

    def _copy_mcp_item_prompt(self, work_item_id: int) -> None:
        settings = load_ui_settings()
        proj = self._selected_project()
        if proj is None:
            show_error_dialog(self, "错误", "请先选择项目")
            return
        prompt = build_mcp_prompt(settings=settings, project=proj, work_item_id=work_item_id, mode="analyze")
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        app.clipboard().setText(prompt)
        self._toast("已复制", f"工单 #{work_item_id} 的 MCP 提示词已复制")

    def _open_related_dialog(self, work_item_id: int) -> None:
        try:
            library, project, pat = self._current_context()
        except Exception as exc:
            show_error_dialog(self, "无法打开关联单", str(exc))
            return
        dlg = RelatedWorkItemsDialog(work_item_id, library, project, pat, parent=self)
        dlg.analyze_requested.connect(self._analyze_item)
        dlg.fix_requested.connect(self._fix_item)
        dlg.mcp_requested.connect(self._copy_mcp_item_prompt)
        dlg.exec()

    def _run_ai_flow(self, work_item_id: int, *, mode: str) -> None:
        settings = load_ui_settings()
        if not settings.local_repos:
            show_error_dialog(self, "缺少本地仓库", "请先到【代码配置】页添加并配置本地仓库")
            return

        repo_id = self._choose_local_repo(settings)
        if not repo_id:
            return

        settings.work_items_local_repo_id = repo_id
        save_ui_settings(settings)

        self.btn_refresh.setEnabled(False)
        self._toast("处理中", f"正在准备工单 #{work_item_id}")

        def run() -> None:
            payload: dict[str, object] = {}
            try:
                settings = load_ui_settings()
                profile = selected_ai_profile(settings)
                if profile is None or not profile.command.strip():
                    raise RuntimeError("请先在 AI配置 里选择并保存 AI 工具")
                repo = selected_local_repo(settings)
                if repo is None or not repo.path.strip():
                    raise RuntimeError("请先选择一个本地仓库")

                lib, proj, pat = self._current_context()
                context = load_work_item_context(lib, proj, pat, work_item_id)
                policy_cfg = load_effective_ai_change_policy(proj.id, settings=settings)
                policy = evaluate_change_policy(policy_cfg, work_item=context.work_item.__dict__)

                if mode == "fix" and settings.ai.enabled and settings.ai.require_policy_check_before_code_change:
                    if policy.decision == "deny":
                        raise RuntimeError("当前策略禁止直接修复，该工单只允许分析。")

                payload["profile_name"] = profile.name
                payload["repo_name"] = repo.name
                payload["repo_path"] = repo.path
                payload["prompt"] = build_prompt(
                    mode=mode,
                    settings=settings,
                    project=proj,
                    context=context,
                    policy=policy,
                )
                payload["command"] = profile.command.strip()
                payload["policy"] = policy
            except Exception as e:
                payload["error"] = str(e)

            def finish() -> None:
                self.btn_refresh.setEnabled(True)
                if "error" in payload:
                    show_error_dialog(self, "执行失败", str(payload["error"]))
                    return

                prompt = str(payload["prompt"] or "")
                app = QtWidgets.QApplication.instance()
                if app is not None:
                    app.clipboard().setText(prompt)

                policy = payload.get("policy")
                if mode == "fix" and getattr(policy, "decision", "") == "review":
                    ok = QtWidgets.QMessageBox.question(
                        self,
                        "需要确认",
                        "当前工单命中复核规则。继续启动 AI 吗？",
                    )
                    if ok != QtWidgets.QMessageBox.Yes:
                        return

                try:
                    open_ai_in_terminal(str(payload["command"] or ""), repo_path=str(payload["repo_path"] or ""))
                except Exception as e:
                    show_error_dialog(self, "启动 AI 失败", str(e))
                    return

                action = "分析" if mode == "analyze" else "修复"
                name = str(payload["profile_name"] or "AI")
                repo_name = str(payload["repo_name"] or "本地仓库")
                self._toast("已启动", f"{name} 已在 {repo_name} 打开，{action} Prompt 已复制")

            QtCore.QTimer.singleShot(0, self, finish)

        threading.Thread(target=run, daemon=True).start()

    def _choose_local_repo(self, settings) -> str | None:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("选择本地仓库")
        dlg.setModal(True)
        dlg.resize(620, 140)

        form = QtWidgets.QFormLayout(dlg)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        combo = QtWidgets.QComboBox()
        combo.setFixedWidth(460)
        idx = 0
        for i, repo in enumerate(settings.local_repos):
            combo.addItem(f"{repo.name}  ({repo.path})", userData=repo.id)
            if settings.work_items_local_repo_id and repo.id == settings.work_items_local_repo_id:
                idx = i
        if combo.count() > 0:
            combo.setCurrentIndex(idx)

        row = QtWidgets.QHBoxLayout()
        btn_cancel = PushButton("取消")
        btn_ok = PushButton("确定")
        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        row.addStretch(1)

        form.addRow("本地仓库", combo)
        form.addRow(row)

        btn_cancel.clicked.connect(dlg.reject)
        btn_ok.clicked.connect(dlg.accept)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return None
        return str(combo.currentData() or "")
