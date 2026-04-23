from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app_ado.ado_work_item_http import (
    DEFAULT_WORK_ITEM_FIELDS,
    get_work_item,
    get_work_item_comments,
    get_work_item_updates,
    get_work_items,
    list_board_columns,
    list_work_items_by_column,
    query_by_wiql,
)
from app_ado.ai_policy import evaluate_change_policy, load_effective_ai_change_policy, policy_path
from app_ado.secrets import get_pat
from app_ado.store import load_ui_settings


logging.basicConfig(level=logging.ERROR, stream=sys.stderr)

SERVER_NAME = "ado-work-items"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"


def _json_dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _send(payload: dict[str, Any]) -> None:
    sys.stdout.write(_json_dump(payload) + "\n")
    sys.stdout.flush()


def _send_result(req_id: Any, result: dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _send_error(req_id: Any, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def _tool_result_text(data: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}], "isError": False}


def _tool_error_text(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _normalize_name(value: str) -> str:
    return value.strip().lower()


def _resolve_context(arguments: dict[str, Any]) -> tuple[Any, Any, str]:
    settings = load_ui_settings()

    library_id = str(arguments.get("library_id") or settings.active_library_id or "").strip()
    project_id = str(arguments.get("project_id") or settings.active_project_id or "").strip()
    library_name = str(arguments.get("library_name") or "").strip()
    project_name = str(arguments.get("project_name") or "").strip()

    library = None
    if library_id:
        library = next((x for x in settings.libraries if x.id == library_id), None)
    if library is None and library_name:
        library = next((x for x in settings.libraries if _normalize_name(x.name) == _normalize_name(library_name)), None)
    if library is None:
        raise RuntimeError("找不到 library 配置，请传 library_id/library_name，或先在 UI 中设置 active_library_id。")

    project = None
    if project_id:
        project = next((x for x in settings.projects if x.id == project_id), None)
    if project is None and project_name:
        project = next(
            (
                x for x in settings.projects
                if x.library_id == library.id and _normalize_name(x.project) == _normalize_name(project_name)
            ),
            None,
        )
    if project is None:
        project = next((x for x in settings.projects if x.id == settings.active_project_id and x.library_id == library.id), None)
    if project is None:
        raise RuntimeError("找不到 project 配置，请传 project_id/project_name，或先在 UI 中设置 active_project_id。")

    pat = get_pat(library.id)
    if not pat:
        raise RuntimeError(f"找不到 PAT：library_id={library.id}")

    return library, project, pat


def _parse_fields(arguments: dict[str, Any]) -> list[str]:
    raw = arguments.get("fields")
    if not raw:
        return list(DEFAULT_WORK_ITEM_FIELDS)
    if not isinstance(raw, list):
        raise RuntimeError("fields 必须是字符串数组")
    out: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            out.append(text)
    return out or list(DEFAULT_WORK_ITEM_FIELDS)


def _tool_ado_get_work_item(arguments: dict[str, Any]) -> dict[str, Any]:
    library, project, pat = _resolve_context(arguments)
    work_item_id = arguments.get("work_item_id")
    if work_item_id is None:
        raise RuntimeError("缺少参数 work_item_id")
    item = get_work_item(
        library.base_url,
        int(work_item_id),
        collection=project.collection,
        project=project.project,
        pat=pat,
        fields=_parse_fields(arguments),
        expand_relations=bool(arguments.get("expand_relations")),
    )
    return _tool_result_text(
        {
            "library": library.name,
            "project": project.project,
            "work_item": {
                "id": item.id,
                "title": item.title,
                "state": item.state,
                "work_item_type": item.work_item_type,
                "assigned_to": item.assigned_to,
                "board_column": item.board_column,
                "board_column_done": item.board_column_done,
                "url": item.url,
                "fields": item.fields,
                "relations": item.relations,
            },
        }
    )


def _tool_ado_get_work_item_comments(arguments: dict[str, Any]) -> dict[str, Any]:
    library, project, pat = _resolve_context(arguments)
    work_item_id = arguments.get("work_item_id")
    if work_item_id is None:
        raise RuntimeError("缺少参数 work_item_id")
    top = int(arguments.get("top") or 50)
    try:
        comments = get_work_item_comments(
            library.base_url,
            project.collection,
            project.project,
            int(work_item_id),
            pat=pat,
            top=top,
            include_deleted=bool(arguments.get("include_deleted")),
        )
        return _tool_result_text(
            {
                "library": library.name,
                "project": project.project,
                "work_item_id": int(work_item_id),
                "source": "comments_api",
                "comments": [
                    {
                        "comment_id": x.comment_id,
                        "text": x.text,
                        "created_by": x.created_by,
                        "created_date": x.created_date,
                        "modified_by": x.modified_by,
                        "modified_date": x.modified_date,
                        "is_deleted": x.is_deleted,
                        "url": x.url,
                    }
                    for x in comments
                ],
            }
        )
    except Exception:
        updates = get_work_item_updates(
            library.base_url,
            project.collection,
            project.project,
            int(work_item_id),
            pat=pat,
            top=top,
        )
        return _tool_result_text(
            {
                "library": library.name,
                "project": project.project,
                "work_item_id": int(work_item_id),
                "source": "updates_fallback",
                "note": "当前 ADO Server comments API 不可用，已自动降级为 work item updates 时间线。",
                "comments": [],
                "updates": [
                    {
                        "update_id": x.update_id,
                        "rev": x.rev,
                        "revised_by": x.revised_by,
                        "revised_date": x.revised_date,
                        "fields": x.fields,
                        "relations": x.relations,
                        "url": x.url,
                    }
                    for x in updates
                ],
            }
        )


def _tool_ado_query_work_items(arguments: dict[str, Any]) -> dict[str, Any]:
    library, project, pat = _resolve_context(arguments)
    wiql = str(arguments.get("wiql") or "").strip()
    if not wiql:
        raise RuntimeError("缺少参数 wiql")
    refs = query_by_wiql(library.base_url, project.collection, project.project, wiql, pat=pat)
    items = get_work_items(
        library.base_url,
        [x.id for x in refs],
        collection=project.collection,
        project=project.project,
        pat=pat,
        fields=_parse_fields(arguments),
        expand_relations=bool(arguments.get("expand_relations")),
    )
    return _tool_result_text(
        {
            "library": library.name,
            "project": project.project,
            "count": len(items),
            "work_items": [
                {
                    "id": x.id,
                    "title": x.title,
                    "state": x.state,
                    "work_item_type": x.work_item_type,
                    "assigned_to": x.assigned_to,
                    "board_column": x.board_column,
                    "url": x.url,
                    "fields": x.fields,
                }
                for x in items
            ],
        }
    )


def _tool_ado_list_board_columns(arguments: dict[str, Any]) -> dict[str, Any]:
    library, project, pat = _resolve_context(arguments)
    team = str(arguments.get("team") or "").strip()
    board = str(arguments.get("board") or "").strip()
    if not team:
        raise RuntimeError("缺少参数 team")
    if not board:
        raise RuntimeError("缺少参数 board")
    columns = list_board_columns(library.base_url, project.collection, project.project, team, board, pat=pat)
    return _tool_result_text(
        {
            "library": library.name,
            "project": project.project,
            "team": team,
            "board": board,
            "columns": [
                {
                    "id": x.id,
                    "name": x.name,
                    "column_type": x.column_type,
                    "item_limit": x.item_limit,
                    "is_split": x.is_split,
                    "description": x.description,
                    "state_mappings": x.state_mappings,
                }
                for x in columns
            ],
        }
    )


def _tool_ado_list_work_items_by_column(arguments: dict[str, Any]) -> dict[str, Any]:
    library, project, pat = _resolve_context(arguments)
    team = str(arguments.get("team") or "").strip()
    board = str(arguments.get("board") or "").strip()
    column_name = str(arguments.get("column_name") or "").strip()
    if not team:
        raise RuntimeError("缺少参数 team")
    if not board:
        raise RuntimeError("缺少参数 board")
    if not column_name:
        raise RuntimeError("缺少参数 column_name")

    raw_types = arguments.get("work_item_types") or []
    if raw_types and not isinstance(raw_types, list):
        raise RuntimeError("work_item_types 必须是字符串数组")
    items = list_work_items_by_column(
        library.base_url,
        project.collection,
        project.project,
        team,
        board,
        column_name,
        pat=pat,
        work_item_types=[str(x) for x in raw_types],
        fields=_parse_fields(arguments),
    )
    return _tool_result_text(
        {
            "library": library.name,
            "project": project.project,
            "team": team,
            "board": board,
            "column_name": column_name,
            "count": len(items),
            "work_items": [
                {
                    "id": x.id,
                    "title": x.title,
                    "state": x.state,
                    "work_item_type": x.work_item_type,
                    "assigned_to": x.assigned_to,
                    "board_column": x.board_column,
                    "url": x.url,
                    "fields": x.fields,
                }
                for x in items
            ],
        }
    )


def _tool_ado_evaluate_change_policy(arguments: dict[str, Any]) -> dict[str, Any]:
    library, project, pat = _resolve_context(arguments)
    work_item_id = arguments.get("work_item_id")
    if work_item_id is None:
        raise RuntimeError("缺少参数 work_item_id")

    raw_paths = arguments.get("target_paths") or []
    if raw_paths and not isinstance(raw_paths, list):
        raise RuntimeError("target_paths 必须是字符串数组")

    policy = load_effective_ai_change_policy(project.id)
    item = get_work_item(
        library.base_url,
        int(work_item_id),
        collection=project.collection,
        project=project.project,
        pat=pat,
        fields=_parse_fields({"fields": list(DEFAULT_WORK_ITEM_FIELDS) + ["System.Description", "System.Tags"]}),
        expand_relations=bool(arguments.get("expand_relations")),
    )
    evaluation = evaluate_change_policy(
        policy,
        work_item={
            "id": item.id,
            "title": item.title,
            "state": item.state,
            "work_item_type": item.work_item_type,
            "board_column": item.board_column,
            "fields": item.fields,
        },
        target_paths=[str(x) for x in raw_paths],
        change_summary=str(arguments.get("change_summary") or ""),
    )
    return _tool_result_text(
        {
            "library": library.name,
            "project": project.project,
            "policy_file": str(policy_path()),
            "work_item_id": item.id,
            "work_item_title": item.title,
            "work_item_type": item.work_item_type,
            "decision": evaluation.decision,
            "reasons": evaluation.reasons,
            "matched_deny_keywords": evaluation.matched_deny_keywords,
            "matched_review_keywords": evaluation.matched_review_keywords,
            "forbidden_paths_hit": evaluation.forbidden_paths_hit,
            "review_paths_hit": evaluation.review_paths_hit,
            "target_paths": evaluation.target_paths,
            "recommended_action": evaluation.recommended_action,
        }
    )


TOOLS: dict[str, dict[str, Any]] = {
    "ado_get_work_item": {
        "description": "按 work item id 读取 ADO 工作项详情。",
        "schema": {
            "type": "object",
            "properties": {
                "work_item_id": {"type": "integer"},
                "library_id": {"type": "string"},
                "library_name": {"type": "string"},
                "project_id": {"type": "string"},
                "project_name": {"type": "string"},
                "fields": {"type": "array", "items": {"type": "string"}},
                "expand_relations": {"type": "boolean"},
            },
            "required": ["work_item_id"],
        },
        "handler": _tool_ado_get_work_item,
    },
    "ado_get_work_item_comments": {
        "description": "读取指定工作项的评论列表。",
        "schema": {
            "type": "object",
            "properties": {
                "work_item_id": {"type": "integer"},
                "library_id": {"type": "string"},
                "library_name": {"type": "string"},
                "project_id": {"type": "string"},
                "project_name": {"type": "string"},
                "top": {"type": "integer"},
                "include_deleted": {"type": "boolean"},
            },
            "required": ["work_item_id"],
        },
        "handler": _tool_ado_get_work_item_comments,
    },
    "ado_query_work_items": {
        "description": "执行 WIQL 查询并返回工作项详情列表。",
        "schema": {
            "type": "object",
            "properties": {
                "wiql": {"type": "string"},
                "library_id": {"type": "string"},
                "library_name": {"type": "string"},
                "project_id": {"type": "string"},
                "project_name": {"type": "string"},
                "fields": {"type": "array", "items": {"type": "string"}},
                "expand_relations": {"type": "boolean"},
            },
            "required": ["wiql"],
        },
        "handler": _tool_ado_query_work_items,
    },
    "ado_list_board_columns": {
        "description": "列出指定 team/board 的版块列配置。",
        "schema": {
            "type": "object",
            "properties": {
                "team": {"type": "string"},
                "board": {"type": "string"},
                "library_id": {"type": "string"},
                "library_name": {"type": "string"},
                "project_id": {"type": "string"},
                "project_name": {"type": "string"},
            },
            "required": ["team", "board"],
        },
        "handler": _tool_ado_list_board_columns,
    },
    "ado_list_work_items_by_column": {
        "description": "按 team/board/column 查询版块列中的工作项。",
        "schema": {
            "type": "object",
            "properties": {
                "team": {"type": "string"},
                "board": {"type": "string"},
                "column_name": {"type": "string"},
                "library_id": {"type": "string"},
                "library_name": {"type": "string"},
                "project_id": {"type": "string"},
                "project_name": {"type": "string"},
                "work_item_types": {"type": "array", "items": {"type": "string"}},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["team", "board", "column_name"],
        },
        "handler": _tool_ado_list_work_items_by_column,
    },
    "ado_evaluate_change_policy": {
        "description": "按本地策略评估某个 work item 是否允许 AI 自动改代码。",
        "schema": {
            "type": "object",
            "properties": {
                "work_item_id": {"type": "integer"},
                "library_id": {"type": "string"},
                "library_name": {"type": "string"},
                "project_id": {"type": "string"},
                "project_name": {"type": "string"},
                "target_paths": {"type": "array", "items": {"type": "string"}},
                "change_summary": {"type": "string"},
                "expand_relations": {"type": "boolean"},
            },
            "required": ["work_item_id"],
        },
        "handler": _tool_ado_evaluate_change_policy,
    },
}


def _handle_initialize(req_id: Any, params: dict[str, Any]) -> None:
    client_protocol = str(params.get("protocolVersion") or "")
    protocol = client_protocol or PROTOCOL_VERSION
    _send_result(
        req_id,
        {
            "protocolVersion": protocol,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": "Use active_library_id and active_project_id from local UI settings when caller does not specify context.",
        },
    )


def _handle_tools_list(req_id: Any) -> None:
    tools = []
    for name, meta in TOOLS.items():
        tools.append(
            {
                "name": name,
                "description": meta["description"],
                "inputSchema": meta["schema"],
            }
        )
    _send_result(req_id, {"tools": tools})


def _handle_tools_call(req_id: Any, params: dict[str, Any]) -> None:
    name = str(params.get("name") or "").strip()
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        _send_result(req_id, _tool_error_text("arguments 必须是对象"))
        return
    tool = TOOLS.get(name)
    if tool is None:
        _send_result(req_id, _tool_error_text(f"未知工具：{name}"))
        return
    try:
        result = tool["handler"](arguments)
    except Exception as e:
        logging.error("tool call failed: %s\n%s", e, traceback.format_exc())
        _send_result(req_id, _tool_error_text(str(e)))
        return
    _send_result(req_id, result)


def _handle_request(payload: dict[str, Any]) -> None:
    req_id = payload.get("id")
    method = str(payload.get("method") or "")
    params = payload.get("params") or {}
    if params is None:
        params = {}
    if not isinstance(params, dict):
        _send_error(req_id, -32602, "params must be an object")
        return

    if method == "initialize":
        _handle_initialize(req_id, params)
        return
    if method == "tools/list":
        _handle_tools_list(req_id)
        return
    if method == "tools/call":
        _handle_tools_call(req_id, params)
        return
    if method == "ping":
        _send_result(req_id, {})
        return
    if req_id is not None:
        _send_error(req_id, -32601, f"Method not found: {method}")


def main() -> int:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            _send_error(None, -32700, "Parse error")
            continue
        if not isinstance(payload, dict):
            _send_error(payload.get("id") if isinstance(payload, dict) else None, -32600, "Invalid Request")
            continue
        try:
            _handle_request(payload)
        except Exception as e:
            logging.error("request failed: %s\n%s", e, traceback.format_exc())
            _send_error(payload.get("id"), -32603, str(e))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
