"""工单模块的 TG 桥。

权限：当前只放给 owner（telegram_chat_id 命中的那个人）。
将来加权限组时改 `can_use` 一处即可。

设计模式参考 ai_dev_tg_bridge：bridge 提供 (text, reply_markup) 返回值，
tg_control 负责 reply。无后台线程，所有 ADO 调用同步进行。
"""

from __future__ import annotations

import time
from typing import Any

from app_ado.ado_work_item_http import (
    HIERARCHY_FORWARD_REL,
    WorkItem,
    get_descendant_work_items,
    get_work_item,
    list_work_items_by_board_column_value,
)
from app_ado.ai_work_item_flow import build_mcp_prompt
from app_ado.models import LibraryEntry, ProjectEntry, UiSettings
from app_ado.secrets import get_pat
from app_ado.store import load_ui_settings, save_ui_settings
from app_ado.tg_work_items_inline import (
    BOARD_COLUMNS,
    wi_detail_menu,
    wi_list_menu,
    wi_main_menu,
    wi_pick_column_menu,
    wi_pick_project_menu,
    wi_related_menu,
)


_CACHE_TTL_SEC = 600.0
_PAGE_SIZE = 10
_MCP_PROMPT_CHUNK = 3500  # Telegram text 限制 4096，留点 buffer 给 markdown 包裹


def _has_child_relations(item: WorkItem) -> bool:
    for rel in item.relations or []:
        if str(rel.get("rel") or "") == HIERARCHY_FORWARD_REL:
            return True
    return False


def _short_title(title: str, *, limit: int = 50) -> str:
    t = (title or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


class WorkItemsBridge:
    def __init__(self) -> None:
        # chat_id -> {project_id, column_idx, page, cached_items, cache_ts, last_open_id}
        self._chat_state: dict[str, dict[str, Any]] = {}

    # ---------------- ACL ----------------

    def can_use(self, role: str, group: dict | None) -> bool:
        return role == "owner"

    # ---------------- state ----------------

    def _state(self, chat_id: str) -> dict[str, Any]:
        return self._chat_state.setdefault(
            str(chat_id),
            {
                "project_id": "",
                "column_idx": 2,  # 默认开发中
                "page": 1,
                "cached_items": [],
                "cache_ts": 0.0,
                "last_open_id": 0,
            },
        )

    def _settings(self) -> UiSettings:
        return load_ui_settings()

    def _resolve_project(self, settings: UiSettings, st: dict[str, Any]) -> ProjectEntry | None:
        pid = (st.get("project_id") or "").strip()
        if not pid:
            pid = (settings.work_items_project_id or settings.active_project_id or "").strip()
            if pid:
                st["project_id"] = pid
        if not pid:
            return None
        return next((x for x in settings.projects if x.id == pid), None)

    def _resolve_library(self, settings: UiSettings, project: ProjectEntry) -> LibraryEntry | None:
        return next((x for x in settings.libraries if x.id == project.library_id), None)

    def _project_label(self, settings: UiSettings, st: dict[str, Any]) -> str:
        proj = self._resolve_project(settings, st)
        return proj.project if proj else "(未选)"

    def _column_label(self, st: dict[str, Any]) -> str:
        idx = int(st.get("column_idx") or 0)
        if 0 <= idx < len(BOARD_COLUMNS):
            return BOARD_COLUMNS[idx]
        return BOARD_COLUMNS[2]

    # ---------------- actions ----------------

    def handle_main(self, chat_id: str) -> tuple[str, dict]:
        s = self._settings()
        st = self._state(chat_id)
        text = "📋 工单"
        return text, wi_main_menu(
            project_label=self._project_label(s, st),
            column_label=self._column_label(st),
        )

    def handle_toggle_mcp(self, chat_id: str) -> tuple[str, dict]:
        from app_ado.mcp_server_manager import (
            is_ado_work_items_mcp_running,
            start_ado_work_items_mcp,
            stop_ado_work_items_mcp,
        )
        if is_ado_work_items_mcp_running():
            ok, msg = stop_ado_work_items_mcp()
            text = f"工单MCP 已关闭（{msg}）" if ok else f"关闭失败：{msg}"
        else:
            ok, msg = start_ado_work_items_mcp()
            text = f"工单MCP 已开启（{msg}）" if ok else f"开启失败：{msg}"
        s = self._settings()
        st = self._state(chat_id)
        return text, wi_main_menu(
            project_label=self._project_label(s, st),
            column_label=self._column_label(st),
        )

    def handle_pick_project(self, chat_id: str) -> tuple[str, dict]:
        s = self._settings()
        st = self._state(chat_id)
        current = (st.get("project_id") or s.work_items_project_id or s.active_project_id or "").strip()
        items = [(p.id, p.project) for p in (s.projects or []) if p.id and p.project]
        if not items:
            return "尚未在桌面端【代码配置】里配置项目。", wi_main_menu(
                project_label=self._project_label(s, st), column_label=self._column_label(st)
            )
        return "选择项目：", wi_pick_project_menu(items, current)

    def handle_set_project(self, chat_id: str, project_id: str) -> tuple[str, dict]:
        s = self._settings()
        st = self._state(chat_id)
        proj = next((x for x in s.projects if x.id == project_id), None)
        if proj is None:
            return f"项目不存在：{project_id}", wi_main_menu(
                project_label=self._project_label(s, st), column_label=self._column_label(st)
            )
        st["project_id"] = proj.id
        st["cached_items"] = []
        st["cache_ts"] = 0.0
        st["page"] = 1
        # 同步写回桌面端，保持两边一致
        try:
            s.work_items_project_id = proj.id
            save_ui_settings(s)
        except Exception:
            pass
        return f"已切换项目：{proj.project}", wi_main_menu(
            project_label=proj.project, column_label=self._column_label(st)
        )

    def handle_pick_column(self, chat_id: str) -> tuple[str, dict]:
        st = self._state(chat_id)
        return "选择版块：", wi_pick_column_menu(int(st.get("column_idx") or 0))

    def handle_set_column(self, chat_id: str, column_idx: int) -> tuple[str, dict]:
        s = self._settings()
        st = self._state(chat_id)
        if not (0 <= column_idx < len(BOARD_COLUMNS)):
            return "版块下标越界", wi_main_menu(
                project_label=self._project_label(s, st), column_label=self._column_label(st)
            )
        st["column_idx"] = column_idx
        st["cached_items"] = []
        st["cache_ts"] = 0.0
        st["page"] = 1
        col_name = BOARD_COLUMNS[column_idx]
        # 同步写回桌面端
        try:
            s.work_items_board = col_name
            save_ui_settings(s)
        except Exception:
            pass
        return f"已切换版块：{col_name}", wi_main_menu(
            project_label=self._project_label(s, st), column_label=col_name
        )

    def _ensure_items(self, st: dict[str, Any], *, force: bool) -> tuple[str | None, list[WorkItem]]:
        cached = list(st.get("cached_items") or [])
        cache_ts = float(st.get("cache_ts") or 0.0)
        fresh = (time.time() - cache_ts) < _CACHE_TTL_SEC
        if cached and fresh and not force:
            return None, cached

        s = self._settings()
        proj = self._resolve_project(s, st)
        if proj is None:
            return "请先在【代码配置】里新增并选择项目。", []
        lib = self._resolve_library(s, proj)
        if lib is None:
            return "项目缺少代码库配置。", []
        pat = get_pat(lib.id)
        if not pat:
            return f"代码库未配置 PAT：{lib.name}", []

        col_name = self._column_label(st)
        try:
            items = list_work_items_by_board_column_value(
                lib.base_url,
                proj.collection,
                proj.project,
                col_name,
                pat=pat,
                expand_relations=True,
            )
        except Exception as ex:
            return f"加载工单失败：{ex}", []

        st["cached_items"] = items
        st["cache_ts"] = time.time()
        return None, items

    def handle_list(self, chat_id: str, page: int, *, force: bool = False) -> tuple[str, dict]:
        s = self._settings()
        st = self._state(chat_id)
        err, items = self._ensure_items(st, force=force)
        if err is not None:
            return err, wi_main_menu(
                project_label=self._project_label(s, st), column_label=self._column_label(st)
            )

        total = len(items)
        total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        if page <= 0:
            page = int(st.get("page") or 1)
        page = max(1, min(page, total_pages))
        st["page"] = page

        start = (page - 1) * _PAGE_SIZE
        page_items = items[start:start + _PAGE_SIZE]
        rows = [
            (int(it.id), _short_title(it.title), (it.state or ""))
            for it in page_items
        ]
        col_name = self._column_label(st)
        proj_name = self._project_label(s, st)
        if not rows:
            text = f"📋 {proj_name} · {col_name}\n（当前版块没有工单）"
        else:
            text = f"📋 {proj_name} · {col_name}\n共 {total} 条，第 {page}/{total_pages} 页"
        return text, wi_list_menu(rows, page=page, total_pages=total_pages)

    def handle_refresh(self, chat_id: str) -> tuple[str, dict]:
        st = self._state(chat_id)
        st["page"] = 1
        return self.handle_list(chat_id, 1, force=True)

    def _fetch_item(self, st: dict[str, Any], work_item_id: int) -> tuple[str | None, WorkItem | None, LibraryEntry | None, ProjectEntry | None, str | None]:
        cached = next((x for x in (st.get("cached_items") or []) if int(x.id) == work_item_id), None)
        s = self._settings()
        proj = self._resolve_project(s, st)
        if proj is None:
            return "请先选择项目", None, None, None, None
        lib = self._resolve_library(s, proj)
        if lib is None:
            return "项目缺少代码库配置", None, None, None, None
        pat = get_pat(lib.id)
        if not pat:
            return f"代码库未配置 PAT：{lib.name}", None, None, None, None
        if cached is not None and cached.relations:
            return None, cached, lib, proj, pat
        try:
            item = get_work_item(
                lib.base_url,
                work_item_id,
                collection=proj.collection,
                project=proj.project,
                pat=pat,
                expand_relations=True,
            )
        except Exception as ex:
            return f"读取工单失败：{ex}", None, None, None, None
        return None, item, lib, proj, pat

    def handle_open(self, chat_id: str, work_item_id: int) -> tuple[str, dict]:
        s = self._settings()
        st = self._state(chat_id)
        err, item, lib, proj, _pat = self._fetch_item(st, work_item_id)
        if err is not None or item is None:
            return err or "未知错误", wi_main_menu(
                project_label=self._project_label(s, st), column_label=self._column_label(st)
            )
        st["last_open_id"] = int(item.id)

        area = str(item.fields.get("System.AreaPath") or "")
        tags = str(item.fields.get("System.Tags") or "")
        priority = item.fields.get("Microsoft.VSTS.Common.Priority")
        url = item.url or ""

        lines = [
            f"#{item.id} {item.title}",
            f"状态：{item.state or '-'}",
            f"类型：{item.work_item_type or '-'}",
            f"指派：{item.assigned_to or '-'}",
        ]
        if priority is not None:
            lines.append(f"优先级：{priority}")
        if area:
            lines.append(f"Area：{area}")
        if tags:
            lines.append(f"Tags：{tags}")
        if url:
            lines.append(f"链接：{url}")

        text = "\n".join(lines)
        return text, wi_detail_menu(int(item.id), has_children=_has_child_relations(item))

    def handle_mcp_prompt(self, chat_id: str, work_item_id: int, mode: str) -> tuple[list[str], dict | None]:
        """返回 (text 分块列表, 详情菜单)。第一块前会拼一行提示语。"""
        s = self._settings()
        st = self._state(chat_id)
        proj = self._resolve_project(s, st)
        if proj is None:
            return ["请先选择项目"], None
        mode_norm = "fix" if mode == "f" else "analyze"
        try:
            prompt = build_mcp_prompt(
                settings=s,
                project=proj,
                work_item_id=int(work_item_id),
                mode=mode_norm,
            )
        except Exception as ex:
            return [f"生成 MCP 提示词失败：{ex}"], None

        label = "分析" if mode_norm == "analyze" else "修复"
        header = f"📋 工单 #{work_item_id} 的 MCP {label} 提示词（请整段复制后粘到 AI CLI）："
        chunks: list[str] = [header]
        rest = prompt
        while rest:
            chunks.append(rest[:_MCP_PROMPT_CHUNK])
            rest = rest[_MCP_PROMPT_CHUNK:]

        # last chunk 附返回菜单
        return chunks, wi_detail_menu(int(work_item_id), has_children=False)

    def handle_related(self, chat_id: str, work_item_id: int) -> tuple[str, dict]:
        s = self._settings()
        st = self._state(chat_id)
        proj = self._resolve_project(s, st)
        if proj is None:
            return "请先选择项目", wi_main_menu(
                project_label=self._project_label(s, st), column_label=self._column_label(st)
            )
        lib = self._resolve_library(s, proj)
        if lib is None:
            return "项目缺少代码库配置", wi_main_menu(
                project_label=self._project_label(s, st), column_label=self._column_label(st)
            )
        pat = get_pat(lib.id)
        if not pat:
            return f"代码库未配置 PAT：{lib.name}", wi_main_menu(
                project_label=self._project_label(s, st), column_label=self._column_label(st)
            )

        try:
            children = get_descendant_work_items(
                lib.base_url,
                int(work_item_id),
                collection=proj.collection,
                project=proj.project,
                pat=pat,
            )
        except Exception as ex:
            return f"读取关联单失败：{ex}", wi_detail_menu(int(work_item_id), has_children=False)

        children = [c for c in children if int(c.id) != int(work_item_id)]
        rows = [(int(c.id), _short_title(c.title), (c.state or "")) for c in children]
        if not rows:
            return f"#{work_item_id} 没有子工单。", wi_detail_menu(int(work_item_id), has_children=False)
        text = f"🔗 #{work_item_id} 的关联子单（{len(rows)} 条）："
        return text, wi_related_menu(int(work_item_id), rows)
