from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import httpx


DEFAULT_WORK_ITEM_FIELDS = [
    "System.Id",
    "System.Title",
    "System.State",
    "System.WorkItemType",
    "System.AssignedTo",
    "System.CreatedDate",
    "System.ChangedDate",
    "System.AreaPath",
    "System.IterationPath",
    "System.Tags",
    "System.BoardColumn",
    "System.BoardColumnDone",
    "Microsoft.VSTS.Common.Priority",
    "Microsoft.VSTS.Common.Severity",
]


@dataclass(frozen=True)
class WorkItemRef:
    id: int
    url: str | None = None


@dataclass(frozen=True)
class WorkItem:
    id: int
    rev: int | None
    title: str
    state: str | None
    work_item_type: str | None
    assigned_to: str | None
    board_column: str | None
    board_column_done: bool | None
    url: str | None
    fields: dict[str, Any]
    relations: list[dict[str, Any]]


@dataclass(frozen=True)
class WorkItemComment:
    work_item_id: int
    comment_id: int
    text: str
    created_by: str | None
    created_date: str | None
    modified_by: str | None
    modified_date: str | None
    is_deleted: bool
    url: str | None


@dataclass(frozen=True)
class WorkItemUpdate:
    update_id: int
    work_item_id: int
    rev: int | None
    revised_by: str | None
    revised_date: str | None
    fields: dict[str, Any]
    relations: dict[str, Any]
    url: str | None


@dataclass(frozen=True)
class BoardReference:
    id: str
    name: str
    url: str | None = None


@dataclass(frozen=True)
class BoardColumn:
    id: str
    name: str
    column_type: str | None
    item_limit: int | None
    is_split: bool
    description: str | None
    state_mappings: dict[str, str]


def _auth_header(pat: str) -> str:
    token = base64.b64encode(f":{pat}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


def _client(pat: str, *, timeout_sec: float = 15.0) -> httpx.Client:
    timeout = httpx.Timeout(timeout_sec, connect=5.0)
    return httpx.Client(
        timeout=timeout,
        headers={"Authorization": _auth_header(pat), "Accept": "application/json"},
        follow_redirects=False,
    )


def _binary_client(pat: str, *, timeout_sec: float = 30.0) -> httpx.Client:
    """专门给附件 / 内联图片用：跟随重定向（ADO 常 302 到 CDN 签名 URL），Accept 不限。"""
    timeout = httpx.Timeout(timeout_sec, connect=5.0)
    return httpx.Client(
        timeout=timeout,
        headers={"Authorization": _auth_header(pat), "Accept": "*/*"},
        follow_redirects=True,
    )


def _raise_http_error(r: httpx.Response, *, url: str) -> None:
    if r.is_error:
        raise RuntimeError(f"HTTP {r.status_code} 请求失败:\n[接口] {url}\n[响应] {r.text}")


def _infer_suffix(url: str, content_type: str | None) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query or "")
    for name in query.get("fileName") or query.get("filename") or []:
        suffix = Path(str(name)).suffix.strip()
        if suffix:
            return suffix
    path = parsed.path or ""
    suffix = Path(path).suffix.strip()
    if suffix:
        return suffix
    ct = str(content_type or "").lower()
    if "png" in ct:
        return ".png"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "gif" in ct:
        return ".gif"
    if "webp" in ct:
        return ".webp"
    if "bmp" in ct:
        return ".bmp"
    if "svg" in ct:
        return ".svg"
    return ".bin"


def _normalize_identity(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v or None
    if isinstance(value, dict):
        for key in ("displayName", "uniqueName", "name"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
    return str(value).strip() or None


def _parse_work_item(payload: dict[str, Any]) -> WorkItem:
    fields = dict(payload.get("fields") or {})
    relations = list(payload.get("relations") or [])
    return WorkItem(
        id=int(payload.get("id") or 0),
        rev=int(payload["rev"]) if payload.get("rev") is not None else None,
        title=str(fields.get("System.Title") or ""),
        state=str(fields.get("System.State")) if fields.get("System.State") is not None else None,
        work_item_type=str(fields.get("System.WorkItemType")) if fields.get("System.WorkItemType") is not None else None,
        assigned_to=_normalize_identity(fields.get("System.AssignedTo")),
        board_column=str(fields.get("System.BoardColumn")) if fields.get("System.BoardColumn") is not None else None,
        board_column_done=bool(fields.get("System.BoardColumnDone")) if fields.get("System.BoardColumnDone") is not None else None,
        url=str(payload.get("url")) if payload.get("url") else None,
        fields=fields,
        relations=relations,
    )


def query_by_wiql(
    base_url: str,
    collection: str,
    project: str,
    wiql: str,
    *,
    pat: str,
    api_version: str = "7.0",
    timeout_sec: float = 15.0,
) -> list[WorkItemRef]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/wit/wiql"
    with _client(pat, timeout_sec=timeout_sec) as c:
        r = c.post(url, params={"api-version": api_version}, json={"query": wiql})
        _raise_http_error(r, url=url)
        data: Any = r.json()

    out: list[WorkItemRef] = []
    for item in data.get("workItems") or []:
        wid = item.get("id")
        if wid is None:
            continue
        out.append(WorkItemRef(id=int(wid), url=str(item.get("url")) if item.get("url") else None))
    return out


def get_work_item(
    base_url: str,
    work_item_id: int | str,
    *,
    collection: str | None = None,
    project: str | None = None,
    pat: str,
    fields: list[str] | None = None,
    expand_relations: bool = False,
    api_version: str = "7.0",
    timeout_sec: float = 15.0,
) -> WorkItem:
    if collection and project:
        url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/wit/workitems/{int(work_item_id)}"
    elif collection:
        url = f"{base_url.rstrip('/')}/{collection}/_apis/wit/workitems/{int(work_item_id)}"
    else:
        url = f"{base_url.rstrip('/')}/_apis/wit/workitems/{int(work_item_id)}"
    params: dict[str, Any] = {"api-version": api_version}
    if expand_relations:
        params["$expand"] = "relations"
    elif fields:
        params["fields"] = ",".join(fields)
    with _client(pat, timeout_sec=timeout_sec) as c:
        r = c.get(url, params=params)
        _raise_http_error(r, url=url)
        data: Any = r.json()
    return _parse_work_item(data)


def create_work_item(
    base_url: str,
    collection: str,
    project: str,
    work_item_type: str,
    *,
    pat: str,
    fields: dict[str, Any],
    relations: list[dict[str, Any]] | None = None,
    validate_only: bool = False,
    api_version: str = "7.0",
    timeout_sec: float = 15.0,
) -> WorkItem:
    type_seg = quote(work_item_type, safe="")
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/wit/workitems/${type_seg}"
    ops: list[dict[str, Any]] = []
    for key, value in fields.items():
        if value is None:
            continue
        ops.append({"op": "add", "path": f"/fields/{key}", "value": value})
    for rel in relations or []:
        ops.append({"op": "add", "path": "/relations/-", "value": rel})

    params: dict[str, Any] = {"api-version": api_version}
    if validate_only:
        params["validateOnly"] = "true"

    timeout = httpx.Timeout(timeout_sec, connect=5.0)
    with httpx.Client(
        timeout=timeout,
        headers={
            "Authorization": _auth_header(pat),
            "Accept": "application/json",
            "Content-Type": "application/json-patch+json",
        },
        follow_redirects=False,
    ) as c:
        r = c.post(url, params=params, json=ops)
        _raise_http_error(r, url=url)
        data: Any = r.json()
    return _parse_work_item(data)


def download_authenticated_file(
    url: str,
    *,
    pat: str,
    dest_path: str | Path,
    timeout_sec: float = 30.0,
) -> Path:
    target = Path(dest_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _binary_client(pat, timeout_sec=timeout_sec) as c:
        r = c.get(url, params={"download": "true"})
        _raise_http_error(r, url=url)
        suffix = target.suffix or _infer_suffix(url, r.headers.get("content-type"))
        if not target.suffix and suffix:
            target = target.with_suffix(suffix)
        target.write_bytes(r.content)
    return target


def fetch_attachment_bytes(
    url: str,
    *,
    pat: str,
    timeout_sec: float = 30.0,
) -> tuple[bytes, str | None]:
    with _binary_client(pat, timeout_sec=timeout_sec) as c:
        r = c.get(url, params={"download": "true"})
        _raise_http_error(r, url=url)
        return r.content, r.headers.get("content-type")


def get_work_items(
    base_url: str,
    ids: list[int | str],
    *,
    collection: str | None = None,
    project: str | None = None,
    pat: str,
    fields: list[str] | None = None,
    expand_relations: bool = False,
    error_policy: str = "omit",
    api_version: str = "7.0",
    timeout_sec: float = 15.0,
) -> list[WorkItem]:
    work_ids = [int(x) for x in ids if str(x).strip()]
    if not work_ids:
        return []

    if collection and project:
        url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/wit/workitemsbatch"
    elif collection:
        url = f"{base_url.rstrip('/')}/{collection}/_apis/wit/workitemsbatch"
    else:
        url = f"{base_url.rstrip('/')}/_apis/wit/workitemsbatch"
    out: list[WorkItem] = []
    chunk_size = 200
    with _client(pat, timeout_sec=timeout_sec) as c:
        for i in range(0, len(work_ids), chunk_size):
            body: dict[str, Any] = {
                "ids": work_ids[i:i + chunk_size],
                "errorPolicy": error_policy,
            }
            if expand_relations:
                body["$expand"] = "relations"
            else:
                body["fields"] = fields or DEFAULT_WORK_ITEM_FIELDS

            r = c.post(url, params={"api-version": api_version}, json=body)
            _raise_http_error(r, url=url)
            data: Any = r.json()
            for item in data.get("value") or []:
                wid = item.get("id")
                if wid is None:
                    continue
                out.append(_parse_work_item(item))
    return out


HIERARCHY_FORWARD_REL = "System.LinkTypes.Hierarchy-Forward"


def _extract_child_id_from_relation_url(url: str) -> int | None:
    if not url:
        return None
    path = urlparse(url).path or ""
    tail = path.rsplit("/", 1)[-1].strip()
    if not tail:
        return None
    try:
        return int(tail)
    except ValueError:
        return None


def get_descendant_work_items(
    base_url: str,
    root_id: int | str,
    *,
    collection: str | None = None,
    project: str | None = None,
    pat: str,
    fields: list[str] | None = None,
    api_version: str = "7.0",
    timeout_sec: float = 15.0,
    max_depth: int = 8,
) -> list[WorkItem]:
    root_int = int(root_id)
    visited: set[int] = {root_int}
    ordered_ids: list[int] = []
    frontier: list[int] = [root_int]
    depth = 0

    while frontier and depth < max_depth:
        layer = get_work_items(
            base_url,
            list(frontier),
            collection=collection,
            project=project,
            pat=pat,
            fields=fields,
            expand_relations=True,
            api_version=api_version,
            timeout_sec=timeout_sec,
        )
        next_frontier: list[int] = []
        for parent_item in layer:
            for rel in parent_item.relations or []:
                if str(rel.get("rel") or "") != HIERARCHY_FORWARD_REL:
                    continue
                child_id = _extract_child_id_from_relation_url(str(rel.get("url") or ""))
                if child_id is None or child_id in visited:
                    continue
                visited.add(child_id)
                ordered_ids.append(child_id)
                next_frontier.append(child_id)
        frontier = next_frontier
        depth += 1

    if not ordered_ids:
        return []

    return get_work_items(
        base_url,
        ordered_ids,
        collection=collection,
        project=project,
        pat=pat,
        fields=fields,
        api_version=api_version,
        timeout_sec=timeout_sec,
    )


def get_work_item_comments(
    base_url: str,
    collection: str,
    project: str,
    work_item_id: int | str,
    *,
    pat: str,
    top: int = 50,
    include_deleted: bool = False,
    expand: str | None = None,
    api_version: str = "7.0-preview.4",
    timeout_sec: float = 15.0,
) -> list[WorkItemComment]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/wit/workItems/{int(work_item_id)}/comments"
    params: dict[str, Any] = {"api-version": api_version, "$top": int(top)}
    if expand:
        params["$expand"] = expand

    with _client(pat, timeout_sec=timeout_sec) as c:
        r = c.get(url, params=params)
        _raise_http_error(r, url=url)
        data: Any = r.json()

    out: list[WorkItemComment] = []
    for item in data.get("comments") or []:
        is_deleted = bool(item.get("isDeleted"))
        if is_deleted and not include_deleted:
            continue
        # ADO REST 评论接口返回的主键字段是 "id"（部分版本兼容 "commentId"）。
        cid = item.get("id")
        if cid is None:
            cid = item.get("commentId")
        if cid is None:
            continue
        out.append(
            WorkItemComment(
                work_item_id=int(work_item_id),
                comment_id=int(cid),
                text=str(item.get("text") or ""),
                created_by=_normalize_identity(item.get("createdBy")),
                created_date=str(item.get("createdDate")) if item.get("createdDate") else None,
                modified_by=_normalize_identity(item.get("modifiedBy")),
                modified_date=str(item.get("modifiedDate")) if item.get("modifiedDate") else None,
                is_deleted=is_deleted,
                url=str(item.get("url")) if item.get("url") else None,
            )
        )
    return out


def get_work_item_updates(
    base_url: str,
    collection: str,
    project: str,
    work_item_id: int | str,
    *,
    pat: str,
    top: int = 50,
    api_version: str = "7.0",
    timeout_sec: float = 15.0,
) -> list[WorkItemUpdate]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/wit/workItems/{int(work_item_id)}/updates"
    params: dict[str, Any] = {"api-version": api_version, "$top": int(top)}

    with _client(pat, timeout_sec=timeout_sec) as c:
        r = c.get(url, params=params)
        _raise_http_error(r, url=url)
        data: Any = r.json()

    out: list[WorkItemUpdate] = []
    for item in data.get("value") or []:
        update_id = item.get("id")
        if update_id is None:
            continue
        out.append(
            WorkItemUpdate(
                update_id=int(update_id),
                work_item_id=int(item.get("workItemId") or work_item_id),
                rev=int(item["rev"]) if item.get("rev") is not None else None,
                revised_by=_normalize_identity(item.get("revisedBy")),
                revised_date=str(item.get("revisedDate")) if item.get("revisedDate") else None,
                fields=dict(item.get("fields") or {}),
                relations=dict(item.get("relations") or {}),
                url=str(item.get("url")) if item.get("url") else None,
            )
        )
    return out


def list_boards(
    base_url: str,
    collection: str,
    project: str,
    team: str,
    *,
    pat: str,
    api_version: str = "7.0",
    timeout_sec: float = 15.0,
) -> list[BoardReference]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/{quote(team, safe='')}/_apis/work/boards"
    with _client(pat, timeout_sec=timeout_sec) as c:
        r = c.get(url, params={"api-version": api_version})
        _raise_http_error(r, url=url)
        data: Any = r.json()

    out: list[BoardReference] = []
    for item in data.get("value") or []:
        name = str(item.get("name") or "").strip()
        bid = str(item.get("id") or "").strip()
        if not (name and bid):
            continue
        out.append(BoardReference(id=bid, name=name, url=str(item.get("url")) if item.get("url") else None))
    out.sort(key=lambda x: x.name.lower())
    return out


def list_board_columns(
    base_url: str,
    collection: str,
    project: str,
    team: str,
    board: str,
    *,
    pat: str,
    api_version: str = "7.0",
    timeout_sec: float = 15.0,
) -> list[BoardColumn]:
    team_seg = quote(team, safe="")
    board_seg = quote(board, safe="")
    url = f"{base_url.rstrip('/')}/{collection}/{project}/{team_seg}/_apis/work/boards/{board_seg}/columns"
    with _client(pat, timeout_sec=timeout_sec) as c:
        r = c.get(url, params={"api-version": api_version})
        _raise_http_error(r, url=url)
        data: Any = r.json()

    out: list[BoardColumn] = []
    for item in data.get("value") or []:
        state_mappings = item.get("stateMappings") or {}
        out.append(
            BoardColumn(
                id=str(item.get("id") or ""),
                name=str(item.get("name") or ""),
                column_type=str(item.get("columnType")) if item.get("columnType") is not None else None,
                item_limit=int(item["itemLimit"]) if item.get("itemLimit") is not None else None,
                is_split=bool(item.get("isSplit")),
                description=str(item.get("description")) if item.get("description") is not None else None,
                state_mappings={str(k): str(v) for k, v in state_mappings.items()},
            )
        )
    return out


def _build_column_wiql(
    project: str,
    column: BoardColumn,
    *,
    work_item_types: list[str] | None = None,
    extra_where: list[str] | None = None,
) -> str:
    project_escaped = project.replace("'", "''")
    column_name_escaped = column.name.replace("'", "''")
    conditions = [f"[System.TeamProject] = '{project_escaped}'"]
    states: list[str] = []
    wanted_types = {x.strip() for x in (work_item_types or []) if x.strip()}
    for wit_name, state_name in (column.state_mappings or {}).items():
        if wanted_types and wit_name not in wanted_types:
            continue
        if state_name and state_name not in states:
            states.append(state_name)

    if states:
        quoted_states = ", ".join("'" + s.replace("'", "''") + "'" for s in states)
        conditions.append(f"[System.State] IN ({quoted_states})")
    else:
        conditions.append(f"[System.BoardColumn] = '{column_name_escaped}'")

    if wanted_types:
        quoted_types = ", ".join("'" + x.replace("'", "''") + "'" for x in wanted_types)
        conditions.append(f"[System.WorkItemType] IN ({quoted_types})")

    for expr in extra_where or []:
        expr = str(expr).strip()
        if expr:
            conditions.append(expr)

    return (
        "SELECT [System.Id] "
        "FROM WorkItems "
        f"WHERE {' AND '.join(conditions)} "
        "ORDER BY [Microsoft.VSTS.Common.Priority] ASC, [System.ChangedDate] DESC"
    )


def list_work_items_by_column(
    base_url: str,
    collection: str,
    project: str,
    team: str,
    board: str,
    column_name: str,
    *,
    pat: str,
    work_item_types: list[str] | None = None,
    fields: list[str] | None = None,
    extra_where: list[str] | None = None,
    api_version: str = "7.0",
    timeout_sec: float = 15.0,
) -> list[WorkItem]:
    columns = list_board_columns(
        base_url,
        collection,
        project,
        team,
        board,
        pat=pat,
        api_version=api_version,
        timeout_sec=timeout_sec,
    )
    target = next((x for x in columns if x.name == column_name), None)
    if target is None:
        raise RuntimeError(f"找不到版块列：{column_name}")

    refs = query_by_wiql(
        base_url,
        collection,
        project,
        _build_column_wiql(project, target, work_item_types=work_item_types, extra_where=extra_where),
        pat=pat,
        api_version=api_version,
        timeout_sec=timeout_sec,
    )
    return get_work_items(
        base_url,
        [x.id for x in refs],
        collection=collection,
        project=project,
        pat=pat,
        fields=fields or DEFAULT_WORK_ITEM_FIELDS,
        api_version=api_version,
        timeout_sec=timeout_sec,
    )


def list_work_items_by_board_column_value(
    base_url: str,
    collection: str,
    project: str,
    column_name: str,
    *,
    pat: str,
    work_item_types: list[str] | None = None,
    fields: list[str] | None = None,
    extra_where: list[str] | None = None,
    expand_relations: bool = False,
    api_version: str = "7.0",
    timeout_sec: float = 15.0,
) -> list[WorkItem]:
    project_escaped = project.replace("'", "''")
    column_escaped = column_name.replace("'", "''")
    conditions = [
        f"[System.TeamProject] = '{project_escaped}'",
        f"[System.BoardColumn] = '{column_escaped}'",
    ]

    wanted_types = [str(x).strip() for x in (work_item_types or []) if str(x).strip()]
    if wanted_types:
        quoted_types = ", ".join("'" + x.replace("'", "''") + "'" for x in wanted_types)
        conditions.append(f"[System.WorkItemType] IN ({quoted_types})")

    for expr in extra_where or []:
        expr = str(expr).strip()
        if expr:
            conditions.append(expr)

    wiql = (
        "SELECT [System.Id] "
        "FROM WorkItems "
        f"WHERE {' AND '.join(conditions)} "
        "ORDER BY [Microsoft.VSTS.Common.Priority] ASC, [System.ChangedDate] DESC"
    )
    refs = query_by_wiql(
        base_url,
        collection,
        project,
        wiql,
        pat=pat,
        api_version=api_version,
        timeout_sec=timeout_sec,
    )
    return get_work_items(
        base_url,
        [x.id for x in refs],
        collection=collection,
        project=project,
        pat=pat,
        fields=fields or DEFAULT_WORK_ITEM_FIELDS,
        expand_relations=expand_relations,
        api_version=api_version,
        timeout_sec=timeout_sec,
    )
