"""Pure Python MCP stdio server. No UI fallback and no child processes."""

import argparse
import dataclasses
import json
import os
import re
import select
import signal
import sys
import threading
import time
from pathlib import Path

from toolbox_backend.adapters.ado_read import AdoFailure, AdoRead, within
from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.adapters.credentials import KeyringCredentials
from toolbox_backend.mcp.cache import AttachmentCache
from toolbox_backend.mcp.policy import evaluate_change_policy, load_policy, merge_policy
from toolbox_backend.mcp.runner import LINE_LIMIT, PROTOCOLS, redact_mcp, validate_data_dir

FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{0,127}$")
WRITE_DENY = frozenset(
    {
        "System.Id",
        "System.Rev",
        "System.State",
        "System.Reason",
        "System.CreatedBy",
        "System.CreatedDate",
        "System.ChangedBy",
        "System.ChangedDate",
        "System.AuthorizedAs",
        "System.AuthorizedDate",
        "System.RevisedDate",
        "System.Watermark",
        "System.TeamProject",
        "System.NodeName",
        "System.ExternalLinkCount",
        "System.HyperLinkCount",
        "System.AttachedFileCount",
        "System.RelatedLinkCount",
        "System.History",
        "System.WorkItemType",
    }
)
DEFAULT_FIELDS = [
    "System.Id",
    "System.Title",
    "System.State",
    "System.WorkItemType",
    "System.AssignedTo",
    "System.BoardColumn",
    "System.Description",
    "System.Tags",
]
TOOLS = json.loads(Path(__file__).with_name("tools.json").read_text())


def positive(value):
    if type(value) is not int or not 1 <= value <= 2147483647:
        raise ValueError("invalid work item id")
    return value


def text(args, key, *, default=None, maximum=8192):
    value = args.get(key, default)
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > maximum:
        raise ValueError("invalid argument")
    return value.strip()


def fields(args):
    values = args.get("fields", DEFAULT_FIELDS)
    if (
        not isinstance(values, list)
        or not 1 <= len(values) <= 50
        or any(not isinstance(f, str) or not FIELD.fullmatch(f) for f in values)
    ):
        raise ValueError("invalid fields")
    return values


def work_item(item):
    f = item.get("fields") or {}
    return {
        **item,
        "title": f.get("System.Title"),
        "state": f.get("System.State"),
        "work_item_type": f.get("System.WorkItemType"),
        "board_column": f.get("System.BoardColumn"),
    }


class AdoServer:
    def __init__(self, data_dir, credentials=None, ado=None):
        self.data_dir = Path(data_dir)
        self.store = ConfigStore(self.data_dir)
        self.credentials = credentials if credentials is not None else KeyringCredentials()
        self.ado = ado or AdoRead()
        self.cache = AttachmentCache(self.data_dir)

    def tools(self):
        enabled = self.store._read().mcp.ado.allow_create_work_item
        return [
            {"name": name, "description": tool["description"], "inputSchema": tool["schema"]}
            for name, tool in TOOLS.items()
            if name != "ado_create_work_item" or enabled
        ]

    @staticmethod
    def context(config, args):
        # Require a complete pair. IDs never silently fall back to names after a typo.
        if args.get("library_id") and args.get("project_id"):
            libs = [x for x in config.ado.libraries if x.id == args["library_id"]]
            projects = [x for x in config.ado.projects if x.id == args["project_id"]]
        elif args.get("library_name") and args.get("project_name"):

            def normal(v):
                return str(v).strip().lower()

            libs = [
                x for x in config.ado.libraries if normal(x.name) == normal(args["library_name"])
            ]
            projects = [
                x for x in config.ado.projects if normal(x.project) == normal(args["project_name"])
            ]
        else:
            raise ValueError("必须显式传入 library/project 名称或 ID")
        if len(libs) != 1:
            raise ValueError("找不到或无法唯一确定 library")
        projects = [p for p in projects if p.library_id == libs[0].id]
        if len(projects) != 1:
            raise ValueError("找不到或无法唯一确定 project")
        return libs[0], projects[0]

    def call(self, name, args):
        try:
            if not isinstance(args, dict) or name not in TOOLS:
                raise ValueError("未知工具或参数无效")
            config = self.store._read()
            if name == "ado_create_work_item" and not config.mcp.ado.allow_create_work_item:
                raise ValueError("创建工单工具未启用")
            library, project = self.context(config, args)
            pat = self.credentials.get("ado_pat:" + library.id)
            if not pat:
                raise ValueError("请在设置中配置该库的 PAT")
            prefix = [project.collection, project.project]

            def request(method, segments, params=None, body=None, **kwargs):
                return self.ado._json(
                    library,
                    pat,
                    method,
                    prefix + segments,
                    {"api-version": "7.0", **(params or {})},
                    body,
                    **kwargs,
                )[0]

            def get_item(ident):
                return work_item(
                    request(
                        "GET",
                        ["_apis", "wit", "workitems", positive(ident)],
                        {
                            "fields": ",".join(fields(args)),
                            **({"$expand": "relations"} if args.get("expand_relations") else {}),
                        },
                    )
                )

            def query(wiql):
                refs = request("POST", ["_apis", "wit", "wiql"], body={"query": wiql}).get(
                    "workItems", []
                )
                if not isinstance(refs, list):
                    raise ValueError("invalid response")
                selected = refs[: config.mcp.ado.query_max_items]
                ids = [positive(x["id"]) for x in selected]
                items = []
                for start in range(0, len(ids), 200):
                    items += request(
                        "GET",
                        ["_apis", "wit", "workitems"],
                        {
                            "ids": ",".join(map(str, ids[start : start + 200])),
                            "fields": ",".join(fields(args)),
                        },
                    ).get("value", [])
                return {
                    "count": len(items),
                    "work_items": [work_item(x) for x in items],
                    "truncated": len(refs) > len(selected),
                }

            if name == "ado_get_work_item":
                result = {"work_item": get_item(args.get("work_item_id"))}
            elif name == "ado_get_work_item_comments":
                ident = positive(args.get("work_item_id"))
                top = args.get("top", 50)
                if type(top) is not int or not 1 <= top <= 200:
                    raise ValueError("invalid top")
                try:
                    comments = request(
                        "GET",
                        ["_apis", "wit", "workitems", ident, "comments"],
                        {
                            "api-version": "7.0-preview.3",
                            "$top": top,
                            "includeDeleted": str(bool(args.get("include_deleted"))).lower(),
                        },
                    )
                    result = {
                        "work_item_id": ident,
                        "source": "comments_api",
                        "comments": comments.get("comments", []),
                    }
                except AdoFailure as exc:
                    if exc.status not in {400, 404}:
                        raise
                    updates = request(
                        "GET", ["_apis", "wit", "workitems", ident, "updates"], {"$top": top}
                    )
                    result = {
                        "work_item_id": ident,
                        "source": "updates_fallback",
                        "comments": [],
                        "updates": updates.get("value", []),
                    }
            elif name == "ado_query_work_items":
                fields(args)
                result = query(text(args, "wiql", maximum=65536))
            elif name in {"ado_list_board_columns", "ado_list_work_items_by_column"}:
                team, board = text(args, "team"), text(args, "board")
                columns = request("GET", [team, "_apis", "work", "boards", board, "columns"]).get(
                    "value", []
                )
                if name == "ado_list_board_columns":
                    result = {"team": team, "board": board, "columns": columns}
                else:
                    column = text(args, "column_name")
                    target = next((c for c in columns if c.get("name") == column), None)
                    if target is None:
                        raise ValueError("找不到版块列")
                    types = args.get("work_item_types", [])
                    if (
                        not isinstance(types, list)
                        or len(types) > 50
                        or any(not isinstance(t, str) or len(t) > 128 for t in types)
                    ):
                        raise ValueError("invalid work item types")

                    def quote(value):
                        return "'" + value.replace("'", "''") + "'"

                    states = list(
                        dict.fromkeys(
                            v
                            for k, v in target.get("stateMappings", {}).items()
                            if (not types or k in types) and v
                        )
                    )
                    conditions = ["[System.TeamProject] = " + quote(project.project)]
                    conditions += (
                        ["[System.State] IN (" + ",".join(map(quote, states)) + ")"]
                        if states
                        else ["[System.BoardColumn] = " + quote(column)]
                    )
                    if types:
                        conditions += [
                            "[System.WorkItemType] IN (" + ",".join(map(quote, types)) + ")"
                        ]
                    result = query(
                        "SELECT [System.Id] FROM WorkItems WHERE " + " AND ".join(conditions)
                    )
            elif name == "ado_get_attachment":
                url = text(args, "attachment_url", maximum=4096)
                if not within(library, url):
                    raise ValueError("附件地址不同源或越界")
                maximum = config.mcp.ado.attachment_max_mb << 20

                def fetch():
                    return self.ado._read(
                        library, pat, "GET", url, media=True, limit=maximum, seconds=30
                    )[0]

                ident = positive(args["work_item_id"]) if "work_item_id" in args else None
                path, cached, size = self.cache.store(
                    library.id,
                    ident,
                    url,
                    fetch,
                    max_bytes=maximum,
                    total_bytes=config.mcp.ado.attachment_cache_mb << 20,
                    force=bool(args.get("force_redownload")),
                )
                result = {
                    "url": url,
                    "saved_path": str(path),
                    "filename": path.name,
                    "stored_bytes": size,
                    "from_cache": cached,
                    "compressed": False,
                    "compress_skip_reason": "Pillow 不在后端依赖中，已跳过压缩",
                }
            elif name == "ado_evaluate_change_policy":
                policy = load_policy(self.data_dir / "mcp/ai_change_policy.yaml")
                policy = merge_policy(policy, config.imported.ai.get("default_policy"))
                override = config.imported.ai.get("project_overrides", {}).get(project.id)
                if (
                    override
                    and not override.get("use_default_policy", True)
                    and not project.id.startswith("proj:")
                ):
                    policy = merge_policy(policy, override.get("policy"))
                paths = args.get("target_paths", [])
                if (
                    not isinstance(paths, list)
                    or len(paths) > 1000
                    or any(not isinstance(p, str) or len(p) > 4096 for p in paths)
                ):
                    raise ValueError("invalid target paths")
                item = get_item(args.get("work_item_id"))
                result = dataclasses.asdict(
                    evaluate_change_policy(
                        policy,
                        work_item=item,
                        target_paths=paths,
                        change_summary=args.get("change_summary"),
                    )
                )
            else:
                extra = args.get("extra_fields", {})
                if (
                    not isinstance(extra, dict)
                    or len(extra) > 20
                    or any(
                        not isinstance(k, str)
                        or not FIELD.fullmatch(k)
                        or k.casefold() in {f.casefold() for f in WRITE_DENY}
                        or type(v) not in {str, int, float}
                        or len(str(v).encode()) > 8192
                        for k, v in extra.items()
                    )
                ):
                    raise ValueError("禁止的系统字段或字段值无效")
                values = {"System.Title": text(args, "title"), **extra}
                for key, field in {
                    "description": "System.Description",
                    "acceptance_criteria": "Microsoft.VSTS.Common.AcceptanceCriteria",
                    "area_path": "System.AreaPath",
                    "iteration_path": "System.IterationPath",
                    "assigned_to": "System.AssignedTo",
                }.items():
                    if key in args:
                        values[field] = text(args, key)
                if "tags" in args:
                    tags = args["tags"]
                    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
                        raise ValueError("invalid tags")
                    values["System.Tags"] = "; ".join(tags)
                patch = [
                    {"op": "add", "path": "/fields/" + key, "value": value}
                    for key, value in values.items()
                ]
                if "parent_work_item_id" in args:
                    parent = get_item(args["parent_work_item_id"])
                    if not parent.get("url") or not within(library, parent["url"]):
                        raise ValueError("invalid parent URL")
                    patch.append(
                        {
                            "op": "add",
                            "path": "/relations/-",
                            "value": {
                                "rel": "System.LinkTypes.Hierarchy-Reverse",
                                "url": parent["url"],
                            },
                        }
                    )
                item = request(
                    "POST",
                    [
                        "_apis",
                        "wit",
                        "workitems",
                        "$" + text(args, "work_item_type", default="用户情景"),
                    ],
                    {"validateOnly": str(bool(args.get("validate_only"))).lower()},
                    patch,
                    content_type="application/json-patch+json",
                )
                result = {
                    "validate_only": bool(args.get("validate_only")),
                    "work_item": work_item(item),
                }
            result = {"library": library.name, "project": project.project, **result}
            return {
                "content": [
                    {"type": "text", "text": redact_mcp(json.dumps(result, ensure_ascii=False))}
                ]
            }
        except (ValueError, OSError, KeyError, TypeError, AdoFailure) as exc:
            message = (
                exc.message
                if isinstance(exc, AdoFailure)
                else (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "工具执行失败，请检查配置或策略基线"
                )
            )
            return {"isError": True, "content": [{"type": "text", "text": redact_mcp(message)}]}
        except Exception:
            return {
                "isError": True,
                "content": [{"type": "text", "text": "工具执行失败，请检查配置和凭据"}],
            }


def error(ident, code, message):
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}


def handle_request(server, payload):
    if (
        not isinstance(payload, dict)
        or payload.get("jsonrpc") != "2.0"
        or not isinstance(payload.get("method"), str)
    ):
        return error(None, -32600, "Invalid Request")
    ident, method = payload.get("id"), payload["method"]
    params = payload.get("params", {})
    if not isinstance(params, dict):
        return error(ident, -32602, "Invalid params")
    if "id" not in payload:
        return None
    if method == "initialize":
        version = params.get("protocolVersion")
        result = {
            "protocolVersion": version if version in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "toolbox_ado", "version": "1"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": server.tools()}
    elif method == "tools/call":
        result = server.call(params.get("name"), params.get("arguments", {}))
    else:
        return error(ident, -32601, "Method not found")
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        data_dir = validate_data_dir(args.data_dir)
    except OSError, ValueError:
        print("无效或不安全的数据目录", file=sys.stderr)
        return 2
    # Lazy Keychain construction after the ownership/permissions gate.
    server = AdoServer(data_dir)
    parent, next_parent_check = os.getppid(), time.monotonic() + 2
    stopped = threading.Event()

    def stop(*_):
        stopped.set()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def watch_parent():
        while not stopped.wait(2):
            if os.getppid() != parent:
                os.kill(os.getpid(), signal.SIGTERM)
                return

    threading.Thread(target=watch_parent, daemon=True).start()
    pending = bytearray()
    oversized = False

    def send(payload):
        if payload is not None:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    while not stopped.is_set():
        if time.monotonic() >= next_parent_check:
            if os.getppid() != parent:
                break
            next_parent_check = time.monotonic() + 2
        readable, _, _ = select.select([sys.stdin.fileno()], [], [], 0.1)
        if not readable:
            continue
        chunk = os.read(sys.stdin.fileno(), 65536)
        if not chunk:
            break
        pending.extend(chunk)
        while b"\n" in pending:
            line, _, rest = pending.partition(b"\n")
            pending[:] = rest
            if oversized or len(line) > LINE_LIMIT:
                send(error(None, -32600, "Request line too long"))
                oversized = False
                continue
            try:
                payload = json.loads(line)
            except ValueError, RecursionError:
                send(error(None, -32700, "Parse error"))
                continue
            try:
                send(handle_request(server, payload))
            except Exception:
                send(
                    error(
                        payload.get("id") if isinstance(payload, dict) else None,
                        -32603,
                        "Internal error",
                    )
                )
        if len(pending) > LINE_LIMIT:
            oversized = True
            pending.clear()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError, KeyboardInterrupt:
        sys.exit(0)
