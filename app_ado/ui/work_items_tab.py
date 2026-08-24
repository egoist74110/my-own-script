from __future__ import annotations

import math
import threading
from typing import Callable, Optional

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import CardWidget, ComboBox, InfoBar, InfoBarPosition, LineEdit, PushButton

from app_ado.ado_work_item_http import (
    HIERARCHY_FORWARD_REL,
    WorkItem,
    WorkItemComment,
    get_descendant_work_items,
    get_work_item,
    get_work_item_comments,
    list_work_items_by_board_column_value,
)
from app_ado.ai_work_item_flow import build_mcp_prompt
from app_ado.models import ProjectEntry, project_entry_collection, project_entry_id, project_entry_library_id, project_entry_name
from app_ado.secrets import get_pat
from app_ado.store import load_ui_settings, save_ui_settings
from app_ado.ui.ai_dev_tab import AiDevTab
from app_ado.ui.dialogs import show_error_dialog
from app_ado.work_item_view import (
    collect_image_urls,
    download_images_to_cache,
    rewrite_html_images,
)
from ok.gui.widget.Tab import Tab


BOARD_COLUMNS = ["新建", "待开发", "开发中", "测试", "已关闭"]
PAGE_SIZES = [5, 10, 50, 100, 200]


def _has_child_relations(item: WorkItem) -> bool:
    for rel in item.relations or []:
        if str(rel.get("rel") or "") == HIERARCHY_FORWARD_REL:
            return True
    return False


class WorkItemMiniCard(CardWidget):
    view_clicked = QtCore.Signal(int)
    mcp_clicked = QtCore.Signal(int)
    copy_prompt_clicked = QtCore.Signal(int)
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
        self.btn_view = PushButton("查看")
        self.btn_view.setFixedWidth(72)
        self.btn_mcp = PushButton("MCP分析")
        self.btn_mcp.setFixedWidth(96)
        self.btn_copy_prompt = PushButton("复制提示词")
        self.btn_copy_prompt.setFixedWidth(96)
        row.addWidget(self.btn_view)
        row.addWidget(self.btn_mcp)
        row.addWidget(self.btn_copy_prompt)

        self.btn_related: PushButton | None = None
        if _has_child_relations(item):
            self.btn_related = PushButton("关联单")
            self.btn_related.setFixedWidth(72)
            row.addWidget(self.btn_related)
            self.btn_related.clicked.connect(lambda: self.related_clicked.emit(self.item.id))

        row.addStretch(1)

        self.btn_view.clicked.connect(lambda: self.view_clicked.emit(self.item.id))
        self.btn_mcp.clicked.connect(lambda: self.mcp_clicked.emit(self.item.id))
        self.btn_copy_prompt.clicked.connect(lambda: self.copy_prompt_clicked.emit(self.item.id))

        root.addWidget(title)
        root.addWidget(meta)
        root.addLayout(row)


class RelatedWorkItemsDialog(QtWidgets.QDialog):
    mcp_requested = QtCore.Signal(int)
    copy_prompt_requested = QtCore.Signal(int)
    view_requested = QtCore.Signal(int)

    def __init__(
        self,
        root_item: WorkItem,
        library,
        project: ProjectEntry,
        pat: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._root_item = root_item
        self._root_id = int(root_item.id)
        self._library = library
        self._project = project
        self._pat = pat

        self.setWindowTitle(f"#{self._root_id} 关联单")
        self.resize(560, 640)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        self.title_label = QtWidgets.QLabel(f"#{self._root_id} 关联单")
        self.title_label.setStyleSheet("font-weight: 600;")
        self.status_label = QtWidgets.QLabel("加载子项中…")
        self.status_label.setStyleSheet("color:#666;")
        self.btn_refresh = PushButton("刷新")
        self.btn_close = PushButton("关闭")
        self.btn_refresh.setFixedWidth(80)
        self.btn_close.setFixedWidth(80)
        header.addWidget(self.title_label)
        header.addSpacing(12)
        header.addWidget(self.status_label)
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

        QtCore.QTimer.singleShot(0, self, self._reload_children)

    def _clear_list(self) -> None:
        while self.list_layout.count():
            entry = self.list_layout.takeAt(0)
            w = entry.widget()
            if w is not None:
                w.deleteLater()
        self.list_layout.addStretch(1)

    def _add_card(self, item: WorkItem) -> None:
        card = WorkItemMiniCard(item)
        card.view_clicked.connect(self.view_requested.emit)
        card.mcp_clicked.connect(self._on_card_mcp_clicked)
        card.copy_prompt_clicked.connect(self.copy_prompt_requested.emit)
        if card.btn_related is not None:
            card.btn_related.setEnabled(False)
        self.list_layout.insertWidget(self.list_layout.count() - 1, card)

    def _on_card_mcp_clicked(self, work_item_id: int) -> None:
        # 选了子工单后关掉关联单弹窗，避免 modal 拦截后续 AI 开发面板切换
        self.accept()
        self.mcp_requested.emit(work_item_id)

    def _reload(self) -> None:
        self._clear_list()
        self._reload_children()

    def _reload_children(self) -> None:
        self.btn_refresh.setEnabled(False)
        self.status_label.setText("加载子项中…")

        result: dict = {}

        def run() -> None:
            try:
                result["children"] = get_descendant_work_items(
                    self._library.base_url,
                    self._root_id,
                    collection=self._project.collection,
                    project=self._project.project,
                    pat=self._pat,
                )
            except Exception as exc:
                result["error"] = exc
            QtCore.QTimer.singleShot(0, self, finish)

        def finish() -> None:
            self.btn_refresh.setEnabled(True)
            err = result.get("error")
            if err is not None:
                self.status_label.setText(f"加载失败：{err}")
                return
            children = [x for x in (result.get("children") or []) if int(x.id) != self._root_id]
            self._clear_list()
            for child in children:
                self._add_card(child)
            self.status_label.setText(f"含 {len(children)} 个子项" if children else "没有子项")

        threading.Thread(target=run, daemon=True).start()


_DEFAULT_AI_PROFILE_ID = "claude_code"


class WorkItemDetailDialog(QtWidgets.QDialog):
    """工单查看弹窗：拉一次详情 + 评论 + 内嵌图片，渲染 HTML。

    所有 HTTP 都在后台线程里跑，主线程只做 setHtml；图片用本地 file:// URL 内嵌进 QTextBrowser。
    """

    def __init__(
        self,
        *,
        work_item_id: int,
        library,
        project: ProjectEntry,
        pat: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._work_item_id = int(work_item_id)
        self._library = library
        self._project = project
        self._pat = pat

        self.setWindowTitle(f"#{self._work_item_id} 工单查看")
        self.resize(880, 680)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        self.header_label = QtWidgets.QLabel(f"#{self._work_item_id} 加载中…")
        self.header_label.setStyleSheet("font-weight: 600; font-size: 14px;")
        self.header_label.setWordWrap(True)
        outer.addWidget(self.header_label)

        self.meta_label = QtWidgets.QLabel("")
        self.meta_label.setStyleSheet("color:#666;")
        self.meta_label.setWordWrap(True)
        self.meta_label.setOpenExternalLinks(True)
        outer.addWidget(self.meta_label)

        self.browser = QtWidgets.QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        # 让图片优先按 viewport 宽度伸缩，避免横向滚动
        self.browser.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
        outer.addWidget(self.browser, 1)

        bottom = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet("color:#888;")
        bottom.addWidget(self.status_label, 1)
        self.btn_close = PushButton("关闭")
        self.btn_close.clicked.connect(self.reject)
        bottom.addWidget(self.btn_close)
        outer.addLayout(bottom)

        QtCore.QTimer.singleShot(0, self, self._load)

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------

    def _load(self) -> None:
        self.status_label.setText("正在加载详情…")
        payload: dict = {}

        def run() -> None:
            try:
                item = get_work_item(
                    self._library.base_url,
                    self._work_item_id,
                    collection=self._project.collection,
                    project=self._project.project,
                    pat=self._pat,
                    expand_relations=True,
                )
                try:
                    comments = get_work_item_comments(
                        self._library.base_url,
                        self._project.collection,
                        self._project.project,
                        self._work_item_id,
                        pat=self._pat,
                        top=50,
                    )
                except Exception:
                    comments = []
                urls = collect_image_urls(item, comments)
                url_to_local = download_images_to_cache(
                    urls, pat=self._pat, sub_key=str(self._work_item_id)
                )
                payload["item"] = item
                payload["comments"] = comments
                payload["url_to_local"] = url_to_local
            except Exception as exc:
                payload["error"] = str(exc)
            QtCore.QTimer.singleShot(0, self, finish)

        def finish() -> None:
            err = payload.get("error")
            if err:
                self.status_label.setText(f"加载失败：{err}")
                self.browser.setPlainText(str(err))
                return
            self._render(payload["item"], payload["comments"], payload["url_to_local"])
            n_imgs = len(payload["url_to_local"])
            n_comments = len(payload["comments"])
            self.status_label.setText(
                f"已加载（{n_comments} 条评论，{n_imgs} 张图片）"
            )

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------

    def _render(self, item: WorkItem, comments: list[WorkItemComment], url_to_local: dict) -> None:
        fields = item.fields or {}
        self.header_label.setText(f"#{item.id}  {item.title or '-'}")

        meta_parts = [
            f"状态：{item.state or '-'}",
            f"类型：{item.work_item_type or '-'}",
            f"指派：{item.assigned_to or '-'}",
        ]
        priority = fields.get("Microsoft.VSTS.Common.Priority")
        if priority is not None:
            meta_parts.append(f"优先级：{priority}")
        area = str(fields.get("System.AreaPath") or "")
        if area:
            meta_parts.append(f"Area：{area}")
        tags = str(fields.get("System.Tags") or "")
        if tags:
            meta_parts.append(f"Tags：{tags}")
        url = item.url or ""
        if url:
            meta_parts.append(f'<a href="{url}">在浏览器打开</a>')
        self.meta_label.setText(" · ".join(meta_parts))

        desc_html = str(fields.get("System.Description") or "")
        parts: list[str] = []
        parts.append("<h3 style='margin:4px 0 8px 0'>描述</h3>")
        parts.append(desc_html or "<p style='color:#999'>（无描述）</p>")

        if comments:
            parts.append("<hr/>")
            parts.append(f"<h3 style='margin:8px 0 6px 0'>评论（{len(comments)}）</h3>")
            for c in comments:
                who = c.created_by or "-"
                when = c.created_date or "-"
                body = c.text or ""
                parts.append(
                    f"<div style='border-left:3px solid #ddd; padding:4px 10px; margin:6px 0'>"
                    f"<div style='color:#888; font-size:12px'>{who} · {when}</div>"
                    f"<div>{body}</div>"
                    f"</div>"
                )

        html = rewrite_html_images("".join(parts), url_to_local)
        self.browser.setHtml(html)


class WorkItemsTab(Tab):
    icon = None
    name = "工单"

    def __init__(
        self,
        *,
        ai_dev_tab: Optional[AiDevTab] = None,
        on_navigate_to_ai_dev: Optional[Callable[[], None]] = None,
    ):
        super().__init__()
        self._loaded_items: list[WorkItem] = []
        self._filtered_items: list[WorkItem] = []
        self._current_page: int = 1
        self.list_scroll: QtWidgets.QScrollArea | None = None
        self.list_view: QtWidgets.QWidget | None = None
        self.list_layout: QtWidgets.QVBoxLayout | None = None
        self._ai_dev_tab = ai_dev_tab
        self._on_navigate_to_ai_dev = on_navigate_to_ai_dev

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
                    expand_relations=True,
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
            item_card.view_clicked.connect(self._open_detail_view)
            item_card.mcp_clicked.connect(self._open_mcp_analysis)
            item_card.copy_prompt_clicked.connect(self._copy_mcp_prompt)
            item_card.related_clicked.connect(self._open_related_dialog)
            self.list_layout.addWidget(item_card)

        self.lbl_page.setText(f"第 {self._current_page} / {total_pages} 页  共 {total_items} 条")
        self.btn_prev.setEnabled(self._current_page > 1)
        self.btn_next.setEnabled(self._current_page < total_pages)

    def _open_related_dialog(self, work_item_id: int) -> None:
        root_item = next((x for x in self._loaded_items if int(x.id) == int(work_item_id)), None)
        if root_item is None:
            show_error_dialog(self, "无法打开关联单", "未找到当前工单数据，请先刷新列表")
            return
        try:
            library, project, pat = self._current_context()
        except Exception as exc:
            show_error_dialog(self, "无法打开关联单", str(exc))
            return
        dlg = RelatedWorkItemsDialog(root_item, library, project, pat, parent=self)
        dlg.mcp_requested.connect(self._open_mcp_analysis)
        dlg.copy_prompt_requested.connect(self._copy_mcp_prompt)
        dlg.view_requested.connect(self._open_detail_view)
        dlg.exec()

    # ------------------------------------------------------------------
    # 查看：弹窗展示工单详情（HTML 描述 + 内嵌图片 + 评论）
    # ------------------------------------------------------------------

    def _open_detail_view(self, work_item_id: int) -> None:
        try:
            library, project, pat = self._current_context()
        except Exception as exc:
            show_error_dialog(self, "无法查看工单", str(exc))
            return
        dlg = WorkItemDetailDialog(
            work_item_id=int(work_item_id),
            library=library,
            project=project,
            pat=pat,
            parent=self,
        )
        dlg.exec()

    # ------------------------------------------------------------------
    # 复制提示词：生成 MCP 分析提示词并写入剪贴板
    # ------------------------------------------------------------------

    def _copy_mcp_prompt(self, work_item_id: int) -> None:
        raw_proj = self._selected_project()
        if raw_proj is None:
            show_error_dialog(self, "错误", "请先选择项目")
            return
        try:
            project = self._normalized_project(raw_proj)
        except Exception as exc:
            show_error_dialog(self, "错误", str(exc))
            return

        try:
            prompt = build_mcp_prompt(project=project, work_item_id=int(work_item_id))
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.clipboard().setText(prompt)
            self._toast("已复制", f"#{work_item_id} MCP 分析提示词已复制到剪贴板")
        except Exception as exc:
            self._toast("复制失败", str(exc), ok=False)

    # ------------------------------------------------------------------
    # MCP 分析：选仓库 → 选 AI → 在 AI 开发面板里新开一个会话并自动发提示词
    # ------------------------------------------------------------------

    def _open_mcp_analysis(self, work_item_id: int) -> None:
        settings = load_ui_settings()
        if not settings.local_repos:
            show_error_dialog(self, "缺少本地仓库", "请先到【代码配置】页添加并配置本地仓库")
            return

        raw_proj = self._selected_project()
        if raw_proj is None:
            show_error_dialog(self, "错误", "请先选择项目")
            return
        try:
            project = self._normalized_project(raw_proj)
        except Exception as exc:
            show_error_dialog(self, "错误", str(exc))
            return

        repo_id = self._choose_local_repo(settings)
        if not repo_id:
            return
        repo = next((r for r in settings.local_repos if r.id == repo_id), None)
        if repo is None:
            return

        profile_id = self._choose_ai_profile()
        if not profile_id:
            return

        settings.work_items_local_repo_id = repo_id
        save_ui_settings(settings)

        prompt = build_mcp_prompt(project=project, work_item_id=int(work_item_id))

        if self._ai_dev_tab is None:
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.clipboard().setText(prompt)
            self._toast("已复制", "AI 开发模块未加载，已把 MCP 提示词复制到剪贴板", ok=False)
            return

        ok = self._ai_dev_tab.launch_session_with_prompt(
            profile_id=profile_id,
            repo=repo,
            initial_prompt=prompt,
        )
        if not ok:
            return
        if self._on_navigate_to_ai_dev is not None:
            try:
                self._on_navigate_to_ai_dev()
            except Exception:
                pass

    def _choose_local_repo(self, settings) -> str | None:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("选择仓库")
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

    def _choose_ai_profile(self) -> str | None:
        settings = load_ui_settings()
        profiles = [p for p in (settings.ai.tool.profiles or []) if (p.command or "").strip()]
        if not profiles:
            show_error_dialog(self, "未配置 AI", "请先到【AI 配置】里给 AI CLI 设好启动命令")
            return None

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("选择 AI")
        dlg.setModal(True)
        dlg.resize(360, 130)

        form = QtWidgets.QFormLayout(dlg)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        combo = QtWidgets.QComboBox()
        combo.setFixedWidth(220)
        default_idx = 0
        for i, profile in enumerate(profiles):
            combo.addItem(profile.name or profile.id, userData=profile.id)
            if profile.id == _DEFAULT_AI_PROFILE_ID:
                default_idx = i
        combo.setCurrentIndex(default_idx)

        row = QtWidgets.QHBoxLayout()
        btn_cancel = PushButton("取消")
        btn_ok = PushButton("确定")
        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        row.addStretch(1)

        form.addRow("AI", combo)
        form.addRow(row)

        btn_cancel.clicked.connect(dlg.reject)
        btn_ok.clicked.connect(dlg.accept)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return None
        return str(combo.currentData() or "")
