"""Read-only work items and event-loop-owned opaque media registration."""

import asyncio
import html
import re
import secrets
import time
import unicodedata
from collections import OrderedDict, deque
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlsplit

from toolbox_backend.adapters.ado_read import AdoFailure, build_url, safe_origin, within
from toolbox_backend.adapters.html_sanitize import plain_text, sanitize_html
from toolbox_backend.api.work_item_schemas import (
    Attachment,
    ChildItem,
    ChildrenResponse,
    Comment,
    CommentsResponse,
    HtmlFields,
    Update,
    UpdateField,
    UpdatesResponse,
    WorkItemDetail,
    WorkItemLink,
    WorkItemsResponse,
    WorkItemSummary,
)
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.logging_setup import contains_secret
from toolbox_backend.services.settings import account, find

COLUMNS = ["新建", "待开发", "开发中", "测试", "已关闭"]
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
# One gate for all outbound reads in this process, including S1.
OUTBOUND = asyncio.Semaphore(6)
QUEUE_TIMEOUT_S = 15.0


async def outbound(fn, *args, **kwargs):
    try:
        await asyncio.wait_for(OUTBOUND.acquire(), QUEUE_TIMEOUT_S)
    except TimeoutError:
        raise SettingsError("busy", "远端请求繁忙，请稍后重试", 503) from None
    try:
        task = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Cancellation cannot stop a worker thread: retain the permit until it closes.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            # Retrieve any worker failure while preserving the caller's cancellation.
            if not task.cancelled():
                task.exception()
            raise
    finally:
        OUTBOUND.release()


def failure(exc):
    if exc.category == "not_found":
        return SettingsError("not_found", "工单或接口不存在", 404)
    if exc.category == "no_credential":
        return SettingsError("no_credential", "未配置 PAT", 409)
    return SettingsError("ado_request_failed", exc.message, 502, category=exc.category)


def prepare_html(value):
    """Worker-only cleaning: collect immutable URLs, never touch the registry."""
    candidates = []

    def collect(url):
        candidates.append(url)
        return "candidate-" + str(len(candidates) - 1), None

    return sanitize_html(value, collect), tuple(candidates)


MEDIA_PLACEHOLDER = re.compile(r'<img\b[^>]*\bdata-media-id="candidate-(\d+)"[^>]*>')


def integer(value, default=None):
    if type(value) is int and 1 <= value <= 2147483647:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        digits = value.lstrip("0")
        if len(digits) > 10:
            return default
        parsed = int(digits or "0")
        return parsed if 1 <= parsed <= 2147483647 else default
    return default


def text(value):
    return str(value) if value is not None else None


def identity(value):
    if isinstance(value, dict):
        return next(
            (str(value[k]) for k in ("displayName", "uniqueName", "name") if value.get(k)), None
        )
    return text(value)


def summary(item):
    fields = item.get("fields", {})
    if not isinstance(fields, dict) or integer(item.get("id")) is None:
        raise AdoFailure("bad_response", "远端响应格式无效")
    return WorkItemSummary(
        id=integer(item["id"]),
        title=str(fields.get("System.Title") or ""),
        type=text(fields.get("System.WorkItemType")),
        state=text(fields.get("System.State")),
        assigned_to=identity(fields.get("System.AssignedTo")),
        board_column=text(fields.get("System.BoardColumn")),
        priority=integer(fields.get("Microsoft.VSTS.Common.Priority")),
        severity=text(fields.get("Microsoft.VSTS.Common.Severity")),
        tags=[s.strip() for s in str(fields.get("System.Tags") or "").split(";") if s.strip()],
        area_path=text(fields.get("System.AreaPath")),
        iteration_path=text(fields.get("System.IterationPath")),
        created_date=text(fields.get("System.CreatedDate")),
        changed_date=text(fields.get("System.ChangedDate")),
    )


def relation_id(relation):
    try:
        return integer(urlsplit(str(relation.get("url") or "")).path.rstrip("/").rsplit("/", 1)[-1])
    except ValueError:
        return None


def filename(name):
    return (
        "".join(
            c for c in str(name) if c not in "/\\" and not unicodedata.category(c).startswith("C")
        )[:255]
        or "attachment"
    )


def image_type(body):
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    if body.startswith(b"BM"):
        return "image/bmp"
    return None


@dataclass(frozen=True)
class MediaEntry:
    library_id: str
    project_id: str
    url: str
    kind: str
    name: str
    created_at: float
    base_url: str


class MediaRegistry:
    def __init__(self, *, ttl_s=1800, limit=4096, clock=None):
        self.ttl_s, self.limit, self.clock = ttl_s, limit, clock or time.monotonic
        self.entries = OrderedDict()
        self.keys = {}

    def _remove(self, ident):
        entry = self.entries.pop(ident)
        self.keys.pop((entry.project_id, entry.url, entry.kind), None)

    def _expire(self):
        now = self.clock()
        while self.entries:
            ident, entry = next(iter(self.entries.items()))
            if now - entry.created_at < self.ttl_s:
                break
            self._remove(ident)

    def register(self, project_id, library, url, kind, name=""):
        self._expire()
        # Resolve relative references against the configured library base URL.
        try:
            parsed = urlsplit(url)
            candidate = urljoin(library.base_url.rstrip("/") + "/", url)
        except ValueError:
            return None, ""
        if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
            return None, ""
        if not url or not within(library, candidate):
            return None, safe_origin(candidate) if url else ""
        # kind is part of the key: an inline image and the same attachment URL are served
        # differently (image vs download), so they must not share one registration.
        key = (project_id, candidate, kind)
        ident = self.keys.get(key)
        if ident:
            # An edited base prefix must not reuse an old registration.
            if self.entries[ident].base_url == library.base_url:
                return ident, None
            self._remove(ident)
        ident = secrets.token_urlsafe(16)
        self.entries[ident] = MediaEntry(
            library.id, project_id, candidate, kind, filename(name), self.clock(), library.base_url
        )
        self.keys[key] = ident
        while len(self.entries) > self.limit:
            self._remove(next(iter(self.entries)))
        return ident, None

    def get(self, ident):
        self._expire()
        if ident not in self.entries:
            raise SettingsError("media_expired", "媒体已过期，请刷新详情", 404)
        return self.entries[ident]


class WorkItemsService:
    def __init__(self, settings_service, http):
        self.settings = settings_service
        self.http = http
        self.media = MediaRegistry()

    async def snapshot(self, project_id, *, require_pat=True):
        def select(tx):
            project = find(tx.config.ado.projects, project_id)
            library = find(tx.config.ado.libraries, project.library_id)
            return project, library, self.settings._get(account(library.id))

        project, library, pat = await self.settings.store.run(None, select)
        if require_pat and not pat:
            raise SettingsError("no_credential", "未配置 PAT", 409)
        return project, library, pat

    async def request(self, ctx, method, suffix, params=None, body=None):
        project, library, pat = ctx
        try:
            return await outbound(
                self.http.request_json,
                library,
                pat,
                method,
                [project.collection, project.project, "_apis", "wit", *suffix],
                {"api-version": "7.0", **(params or {})},
                body,
            )
        except AdoFailure as exc:
            raise failure(exc) from None

    @staticmethod
    def values(payload, key="value"):
        values = payload.get(key)
        if not isinstance(values, list) or any(not isinstance(x, dict) for x in values):
            raise SettingsError(
                "ado_request_failed", "远端响应格式无效", 502, category="bad_response"
            )
        return values

    async def batch(self, ctx, ids, *, relations=False):
        result = []
        for start in range(0, len(ids), 200):
            body = {"ids": ids[start : start + 200], "errorPolicy": "omit"}
            body.update(
                {"$expand": "relations"} if relations else {"fields": DEFAULT_WORK_ITEM_FIELDS}
            )
            payload = await self.request(ctx, "POST", ["workitemsbatch"], body=body)
            allowed = set(ids[start : start + 200])
            # Do not accept unsolicited items from a malformed server response.
            seen = set()
            for item in self.values(payload):
                ident = integer(item.get("id"))
                if ident in allowed and ident not in seen:
                    result.append(item)
                    seen.add(ident)
        return result

    async def listing(self, project_id, column):
        ctx = await self.snapshot(project_id)
        project = ctx[0].project.replace("'", "''")
        column = column.replace("'", "''")
        query = (
            "SELECT [System.Id] FROM WorkItems WHERE "
            f"[System.TeamProject] = '{project}' AND [System.BoardColumn] = '{column}' "
            "ORDER BY [Microsoft.VSTS.Common.Priority] ASC, [System.ChangedDate] DESC"
        )
        payload = await self.request(ctx, "POST", ["wiql"], {"$top": 500}, {"query": query})
        refs = self.values(payload, "workItems")
        ids = list(dict.fromkeys(integer(x.get("id")) for x in refs[:500]))
        if None in ids:
            raise SettingsError(
                "ado_request_failed", "远端响应格式无效", 502, category="bad_response"
            )
        items = await self.batch(ctx, ids)
        try:
            shaped = [summary(x) for x in items]
        except AdoFailure as exc:
            raise failure(exc) from None
        return WorkItemsResponse(
            items=shaped, truncated=len(refs) >= 500, omitted=len(ids) - len(items)
        )

    async def raw_detail(self, ctx, ident):
        item = await self.request(ctx, "GET", ["workitems", str(ident)], {"$expand": "relations"})
        if integer(item.get("id")) != ident or not isinstance(item.get("fields"), dict):
            raise SettingsError(
                "ado_request_failed", "远端响应格式无效", 502, category="bad_response"
            )
        return item

    def register(self, ctx, kind="image", name="", *, budget=None):
        project, library, _ = ctx

        def register(url):
            if budget is not None and budget[0] >= 200:
                return None, None
            result = self.media.register(project.id, library, url, kind, name)
            if budget is not None and result[0]:
                budget[0] += 1
            return result

        return register

    async def clean_html(self, value, ctx, budget):
        cleaned, candidates = await asyncio.to_thread(prepare_html, value)
        if cleaned.html is None:
            return cleaned
        register = self.register(ctx, budget=budget)

        def replace(match):
            if budget[0] >= 200:
                return '<span data-blocked-origin="">[图片过多未显示]</span>'
            mid, blocked = register(candidates[int(match[1])])
            if mid:
                return match[0].replace(
                    'data-media-id="candidate-' + match[1] + '"',
                    'data-media-id="' + html.escape(mid, quote=True) + '"',
                    1,
                )
            return (
                '<span data-blocked-origin="' + html.escape(blocked or "", quote=True) + '">'
                + ("[已拦截外部图片]" if blocked else "[内嵌图片未显示]") + '</span>'
            )

        return cleaned.model_copy(update={"html": MEDIA_PLACEHOLDER.sub(replace, cleaned.html)})

    async def detail(self, project_id, ident):
        ctx = await self.snapshot(project_id)
        item = await self.raw_detail(ctx, ident)
        fields = item["fields"]
        html_fields = {}
        budget = [0]
        for key, field in [
            ("description", "System.Description"),
            ("repro_steps", "Microsoft.VSTS.TCM.ReproSteps"),
            ("acceptance_criteria", "Microsoft.VSTS.Common.AcceptanceCriteria"),
        ]:
            value = fields.get(field)
            html_fields[key] = (
                await self.clean_html(str(value), ctx, budget) if value is not None else None
            )
        parent, children, attachments, links = None, [], [], []
        for rel in self.relations(item):
            kind, url = str(rel.get("rel") or ""), str(rel.get("url") or "")
            attrs = rel.get("attributes") if isinstance(rel.get("attributes"), dict) else {}
            if kind == "System.LinkTypes.Hierarchy-Reverse":
                parent = relation_id(rel)
            elif kind == "System.LinkTypes.Hierarchy-Forward":
                child = relation_id(rel)
                if child and child not in children:
                    children.append(child)
            elif kind == "AttachedFile":
                name = filename(attrs.get("name") or "attachment")
                is_image = name.lower().endswith(
                    (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg")
                )
                # All relations remain downloadable even when they are images.
                mid, blocked = self.register(ctx, "attachment", name, budget=budget)(url)
                size = attrs.get("resourceSize")
                attachments.append(
                    Attachment(
                        name=name,
                        size=size if type(size) is int and size >= 0 else None,
                        is_image=is_image,
                        media_id=mid,
                        blocked_origin=blocked,
                    )
                )
            else:
                link_kind, label, link_url = "other", str(attrs.get("name") or kind), None
                if kind == "ArtifactLink" and url.startswith("vstfs:///Git/PullRequestId/"):
                    link_kind, label = "pull_request", "PR #" + unquote(url).rsplit("/", 1)[-1]
                elif kind == "ArtifactLink" and url.startswith("vstfs:///Git/Commit/"):
                    link_kind, label = "commit", unquote(url).rsplit("/", 1)[-1]
                elif kind == "Hyperlink":
                    link_kind = "hyperlink"
                    if safe_origin(url) and urlsplit(url).username is None:
                        link_url = url
                links.append(WorkItemLink(kind=link_kind, label=label, url=link_url))
        project, library, _ = ctx
        return WorkItemDetail(
            **summary(item).model_dump(),
            rev=integer(item.get("rev")),
            web_url=build_url(
                library, [project.collection, project.project, "_workitems", "edit", str(ident)]
            ),
            html=HtmlFields(**html_fields),
            parent_id=parent,
            child_ids=children,
            attachments=attachments,
            links=links,
        )

    @staticmethod
    def relations(item):
        rels = item.get("relations", [])
        if not isinstance(rels, list) or any(not isinstance(x, dict) for x in rels):
            raise SettingsError(
                "ado_request_failed", "远端响应格式无效", 502, category="bad_response"
            )
        return rels

    async def comments(self, project_id, ident):
        ctx = await self.snapshot(project_id)
        payload = await self.request(
            ctx,
            "GET",
            ["workItems", str(ident), "comments"],
            {"api-version": "7.0-preview.4", "$top": 100},
        )
        values, comments = self.values(payload, "comments"), []
        budget = [0]
        for value in values[:100]:
            cid = integer(value.get("id")) or integer(value.get("commentId"))
            if not cid or value.get("isDeleted"):
                continue
            cleaned = await self.clean_html(str(value.get("text") or ""), ctx, budget)
            comments.append(
                Comment(
                    id=cid,
                    author=identity(value.get("createdBy")),
                    created_date=text(value.get("createdDate")),
                    modified_date=text(value.get("modifiedDate")),
                    **cleaned.model_dump(),
                )
            )
        return CommentsResponse(
            comments=comments,
            truncated=len(values) >= 100 or bool(payload.get("continuationToken")),
        )

    async def updates(self, project_id, ident):
        ctx = await self.snapshot(project_id)
        payload = await self.request(
            ctx, "GET", ["workItems", str(ident), "updates"], {"$top": 100}
        )
        values, updates = self.values(payload), []
        for value in values[:100]:
            uid = integer(value.get("id"))
            if not uid:
                continue
            fields, rels = value.get("fields") or {}, value.get("relations") or {}
            if (
                not isinstance(fields, dict)
                or not isinstance(rels, dict)
                or any(not isinstance(rels.get(key, []), list) for key in ("added", "removed"))
            ):
                raise SettingsError(
                    "ado_request_failed", "远端响应格式无效", 502, category="bad_response"
                )
            updates.append(
                Update(
                    id=uid,
                    rev=integer(value.get("rev")),
                    revised_by=identity(value.get("revisedBy")),
                    revised_date=text(value.get("revisedDate")),
                    fields=[
                        UpdateField(
                            name=k,
                            old=plain_text(v.get("oldValue")),
                            new=plain_text(v.get("newValue")),
                        )
                        for k, v in fields.items()
                        if isinstance(v, dict)
                    ],
                    relations_added=len(rels.get("added") or []),
                    relations_removed=len(rels.get("removed") or []),
                )
            )
        return UpdatesResponse(
            updates=updates, truncated=len(values) >= 100 or bool(payload.get("continuationToken"))
        )

    async def children(self, project_id, ident):
        ctx = await self.snapshot(project_id)
        root = await self.raw_detail(ctx, ident)
        queue, visited, result = deque(), {ident}, []
        truncated = False
        admitted = 0

        def enqueue(item, parent, depth):
            nonlocal truncated, admitted
            for rel in self.relations(item):
                if rel.get("rel") != "System.LinkTypes.Hierarchy-Forward":
                    continue
                child = relation_id(rel)
                if child and child not in visited:
                    visited.add(child)
                    if depth > 8 or admitted >= 500:
                        truncated = True
                    else:
                        admitted += 1
                        queue.append((child, parent, depth))

        enqueue(root, ident, 1)
        while queue:
            # Breadth-first, bounded batches; same depth to keep ordering and parents.
            depth, group = queue[0][2], []
            while queue and queue[0][2] == depth and len(group) < 200:
                group.append(queue.popleft())
            items = await self.batch(ctx, [x[0] for x in group], relations=True)
            by_id = {integer(x.get("id")): x for x in items}
            for cid, parent, child_depth in group:
                if cid not in by_id:
                    continue
                item = by_id[cid]
                try:
                    result.append(
                        ChildItem(**summary(item).model_dump(), parent_id=parent, depth=child_depth)
                    )
                except AdoFailure as exc:
                    raise failure(exc) from None
                enqueue(item, cid, child_depth + 1)
        return ChildrenResponse(items=result, truncated=truncated)

    async def fetch_media(self, ident):
        entry = self.media.get(ident)
        try:
            ctx = await self.snapshot(entry.project_id, require_pat=False)
        except SettingsError as exc:
            if exc.code == "not_found":
                raise SettingsError("media_expired", "媒体已过期，请刷新详情", 404) from None
            raise
        project, library, pat = ctx
        if (
            library.id != entry.library_id
            or library.base_url != entry.base_url
            or not within(library, entry.url)
        ):
            raise SettingsError("media_expired", "媒体已过期，请刷新详情", 404)
        if not pat:
            raise SettingsError("no_credential", "未配置 PAT", 409)
        try:
            body = await outbound(self.http.fetch_media, library, pat, entry.url, entry.kind)
        except AdoFailure as exc:
            raise failure(exc) from None
        if contains_secret(body.decode("utf-8", errors="replace")):
            raise SettingsError(
                "ado_request_failed", "远端响应格式无效", 502, category="bad_response"
            )
        mime = image_type(body) if entry.kind == "image" else "application/octet-stream"
        if mime is None:
            raise SettingsError("unsupported_media", "非图片附件，可下载", 415)
        return body, mime, entry
