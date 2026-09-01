from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import sys
import traceback
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app_ado.ado_work_item_http import (
    DEFAULT_WORK_ITEM_FIELDS,
    create_work_item,
    fetch_attachment_bytes,
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

    # 显式入参优先；仅当既未传 id 也未传 name 时，才回落到 UI 的 active_*。
    # （旧实现把 active_* 灌进 *_id 变量，导致 `if *_id:` 恒真、显式传入的 *_name 永远被忽略。）
    arg_library_id = str(arguments.get("library_id") or "").strip()
    arg_library_name = str(arguments.get("library_name") or "").strip()
    arg_project_id = str(arguments.get("project_id") or "").strip()
    arg_project_name = str(arguments.get("project_name") or "").strip()

    library = None
    if arg_library_id:
        library = next((x for x in settings.libraries if x.id == arg_library_id), None)
    if library is None and arg_library_name:
        library = next((x for x in settings.libraries if _normalize_name(x.name) == _normalize_name(arg_library_name)), None)
    if library is None and not arg_library_id and not arg_library_name:
        library = next((x for x in settings.libraries if x.id == settings.active_library_id), None)
    if library is None:
        raise RuntimeError("找不到 library 配置，请传 library_id/library_name，或先在 UI 中设置 active_library_id。")

    project = None
    if arg_project_id:
        project = next((x for x in settings.projects if x.id == arg_project_id), None)
    if project is None and arg_project_name:
        project = next(
            (
                x for x in settings.projects
                if x.library_id == library.id and _normalize_name(x.project) == _normalize_name(arg_project_name)
            ),
            None,
        )
    if project is None and not arg_project_id and not arg_project_name:
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


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ATTACHMENT_CACHE_ROOT = _PROJECT_ROOT / ".cache" / "ado-attachments"


def _safe_path_segment(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\s]+", "_", str(value or "").strip())
    cleaned = cleaned.strip("._") or fallback
    return cleaned[:120]


def _attachment_filename_from_url(url: str, fallback: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query or "")
    for v in (query.get("fileName") or query.get("filename") or []):
        text = str(v).strip()
        if text:
            return _safe_path_segment(text, fallback)
    return _safe_path_segment(fallback, "attachment.bin")


def _attachment_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in (parsed.path or "").split("/") if p]
    for i, p in enumerate(parts):
        if p == "attachments" and i + 1 < len(parts):
            return _safe_path_segment(parts[i + 1], "attachment")[:64]
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _compress_image_inplace(path: Path, mime_type: str | None) -> tuple[bool, str | None]:
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return False, "Pillow 未安装，跳过压缩"

    ct = (mime_type or "").lower()
    suffix = path.suffix.lower()
    is_png = "png" in ct or suffix == ".png"
    is_jpeg = "jpeg" in ct or "jpg" in ct or suffix in (".jpg", ".jpeg")
    if not (is_png or is_jpeg):
        return False, f"非 PNG/JPEG（{suffix or ct or '未知'}），不压缩"

    try:
        with Image.open(path) as img:
            img.load()
            buf = BytesIO()
            if is_png:
                img.save(buf, format="PNG", optimize=True)
            else:
                img.save(buf, format="JPEG", quality=92, optimize=True, progressive=True)
            data = buf.getvalue()
    except Exception as e:
        return False, f"压缩失败：{e}"

    if len(data) >= path.stat().st_size:
        return False, "优化后未变小，保留原文件"
    path.write_bytes(data)
    return True, None


def _tool_ado_get_attachment(arguments: dict[str, Any]) -> dict[str, Any]:
    library, project, pat = _resolve_context(arguments)

    attachment_url = str(arguments.get("attachment_url") or "").strip()
    if not attachment_url:
        raise RuntimeError("缺少参数 attachment_url")

    parsed = urlparse(attachment_url)
    base_parsed = urlparse(str(library.base_url))
    if not parsed.netloc or parsed.netloc.lower() != base_parsed.netloc.lower():
        raise RuntimeError(
            f"attachment_url 的 host ({parsed.netloc!r}) 与 library.base_url ({base_parsed.netloc!r}) 不一致，拒绝下载"
        )

    work_item_id_raw = arguments.get("work_item_id")
    if work_item_id_raw is None:
        wi_segment = "wi_unknown"
    else:
        wi_segment = f"wi_{int(work_item_id_raw)}"

    library_segment = _safe_path_segment(getattr(library, "name", "") or library.id, fallback="library")
    attachment_id = _attachment_id_from_url(attachment_url)
    filename = _attachment_filename_from_url(attachment_url, fallback=f"{attachment_id}.bin")

    cache_dir = _ATTACHMENT_CACHE_ROOT / library_segment / wi_segment
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{attachment_id}_{filename}"

    force = bool(arguments.get("force_redownload"))
    compress_arg = arguments.get("compress")
    compress = True if compress_arg is None else bool(compress_arg)

    if cache_path.exists() and not force:
        stored_bytes = cache_path.stat().st_size
        guessed_mime, _ = mimetypes.guess_type(str(cache_path))
        return _tool_result_text(
            {
                "library": library.name,
                "project": project.project,
                "url": attachment_url,
                "saved_path": str(cache_path),
                "filename": filename,
                "mime_type": guessed_mime,
                "stored_bytes": stored_bytes,
                "from_cache": True,
                "compressed": "unknown",
                "instruction": f"附件已在本地缓存。请使用 Read 工具读取 {cache_path} 查看图像内容。",
            }
        )

    data, mime_type = fetch_attachment_bytes(attachment_url, pat=pat)
    original_bytes = len(data)
    cache_path.write_bytes(data)

    compressed = False
    compress_skip_reason: str | None = None
    if compress:
        compressed, compress_skip_reason = _compress_image_inplace(cache_path, mime_type)

    stored_bytes = cache_path.stat().st_size
    ratio = round(stored_bytes / original_bytes, 3) if original_bytes else None

    payload: dict[str, Any] = {
        "library": library.name,
        "project": project.project,
        "url": attachment_url,
        "saved_path": str(cache_path),
        "filename": filename,
        "mime_type": mime_type,
        "original_bytes": original_bytes,
        "stored_bytes": stored_bytes,
        "compression_ratio": ratio,
        "compressed": compressed,
        "from_cache": False,
        "instruction": f"附件已下载到本地。请使用 Read 工具读取 {cache_path} 查看图像内容。",
    }
    if compress_skip_reason:
        payload["compress_skip_reason"] = compress_skip_reason
    return _tool_result_text(payload)


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


def _tool_ado_create_work_item(arguments: dict[str, Any]) -> dict[str, Any]:
    library, project, pat = _resolve_context(arguments)

    work_item_type = str(arguments.get("work_item_type") or "").strip()
    title = str(arguments.get("title") or "").strip()
    if not title:
        raise RuntimeError("缺少参数 title")
    if not work_item_type:
        # 兜底：AI 漏传类型时按「用户情景」建单，测试在用户情景看板可见
        work_item_type = "用户情景"

    fields: dict[str, Any] = {"System.Title": title}
    if arguments.get("description"):
        fields["System.Description"] = str(arguments["description"])
    if arguments.get("acceptance_criteria"):
        fields["Microsoft.VSTS.Common.AcceptanceCriteria"] = str(arguments["acceptance_criteria"])
    if arguments.get("tags"):
        tags = arguments["tags"]
        fields["System.Tags"] = "; ".join(str(x) for x in tags) if isinstance(tags, list) else str(tags)
    if arguments.get("area_path"):
        fields["System.AreaPath"] = str(arguments["area_path"])
    if arguments.get("iteration_path"):
        fields["System.IterationPath"] = str(arguments["iteration_path"])
    if arguments.get("assigned_to"):
        fields["System.AssignedTo"] = str(arguments["assigned_to"])

    extra_fields = arguments.get("extra_fields")
    if extra_fields:
        if not isinstance(extra_fields, dict):
            raise RuntimeError("extra_fields 必须是对象")
        for k, v in extra_fields.items():
            fields[str(k)] = v

    relations: list[dict[str, Any]] = []
    parent_id = arguments.get("parent_work_item_id")
    if parent_id is not None:
        parent = get_work_item(
            library.base_url,
            int(parent_id),
            collection=project.collection,
            project=project.project,
            pat=pat,
            fields=["System.Id"],
        )
        parent_url = parent.url or (
            f"{library.base_url.rstrip('/')}/{project.collection}/{project.project}"
            f"/_apis/wit/workItems/{int(parent_id)}"
        )
        relations.append({"rel": "System.LinkTypes.Hierarchy-Reverse", "url": parent_url})

    validate_only = bool(arguments.get("validate_only"))
    item = create_work_item(
        library.base_url,
        project.collection,
        project.project,
        work_item_type,
        pat=pat,
        fields=fields,
        relations=relations,
        validate_only=validate_only,
    )
    return _tool_result_text(
        {
            "library": library.name,
            "project": project.project,
            "validate_only": validate_only,
            "work_item": {
                "id": item.id,
                "title": item.title,
                "state": item.state,
                "work_item_type": item.work_item_type,
                "url": item.url,
                "fields": item.fields,
            },
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
    "ado_get_attachment": {
        "description": "下载并缓存 ADO 工作项附件到项目本地 .cache/ado-attachments 目录，PNG/JPEG 自动做无损或接近无损压缩，返回保存路径。下载完成后请使用 Read 工具读取 saved_path 查看附件内容。",
        "schema": {
            "type": "object",
            "properties": {
                "attachment_url": {"type": "string"},
                "work_item_id": {"type": "integer"},
                "library_id": {"type": "string"},
                "library_name": {"type": "string"},
                "project_id": {"type": "string"},
                "project_name": {"type": "string"},
                "compress": {"type": "boolean"},
                "force_redownload": {"type": "boolean"},
            },
            "required": ["attachment_url"],
        },
        "handler": _tool_ado_get_attachment,
    },
    "ado_create_work_item": {
        "description": "新建一个 ADO 工作项。默认类型用「用户情景」（User Story），这样测试能在用户情景看板看到；可选挂到某个 parent work item 下。",
        "schema": {
            "type": "object",
            "properties": {
                "work_item_type": {
                    "type": "string",
                    "description": (
                        "工作项类型。新需求、客户/测试反馈一律用「用户情景」（User Story）；"
                        "只有明确拆分子任务时才用「任务」；其他可选类型：测试用例、Bug 等。"
                    ),
                },
                "title": {"type": "string"},
                "description": {"type": "string"},
                "acceptance_criteria": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "area_path": {"type": "string"},
                "iteration_path": {"type": "string"},
                "assigned_to": {"type": "string"},
                "parent_work_item_id": {"type": "integer"},
                "extra_fields": {"type": "object"},
                "validate_only": {"type": "boolean", "description": "true 时只做字段校验，不真正创建"},
                "library_id": {"type": "string"},
                "library_name": {"type": "string"},
                "project_id": {"type": "string"},
                "project_name": {"type": "string"},
            },
            "required": ["work_item_type", "title"],
        },
        "handler": _tool_ado_create_work_item,
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
    # stdin EOF(客户端关管道)会让下面的 for 循环自然结束退出;再加孤儿兜底:
    # 客户端被强杀、本进程被 reparent 到 launchd 时也自杀,避免常驻泄漏。
    try:
        from app_lark.proc_supervise import install_orphan_reaper

        install_orphan_reaper()
    except Exception:
        pass
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
