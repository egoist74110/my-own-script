"""Read exactly four legacy files. Never import or call the legacy application."""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from toolbox_backend.domain.settings import Ado, Config, DynamicTask, Imported, Tasks

FILES = ("ui_settings.yaml", "tasks.yaml", "lark_settings.yaml", "figma_settings.yaml")
MAX_FILE_BYTES = 1 << 20


@dataclass
class LegacyPlan:
    fingerprint: str
    originals: dict[str, bytes]
    config: Config
    summary: dict


def migrate_tasks(raw: dict) -> tuple[Tasks, str]:
    flows = raw.get("flows", [])
    items = raw.get("tasks", [])
    if not isinstance(flows, list) or not isinstance(items, list):
        raise ValueError("任务或流程必须为列表")
    if any(not isinstance(item, dict) for item in [*flows, *items]):
        raise ValueError("任务或流程元素必须为对象")
    if "tasks" in raw:
        tasks = [DynamicTask.model_validate(item) for item in items]
        if tasks and all(t.sort_order == 0 for t in tasks):
            for index, task in enumerate(tasks, 1):
                task.sort_order = index * 10
        for task in tasks:
            gf = task.git_flow
            if not gf.build_branch.strip():
                gf.build_branch = (
                    gf.merges[-1].target
                    if gf.merges
                    else next((x.strip() for x in reversed(gf.update_branches) if x.strip()), "")
                )
        return Tasks(items=tasks, legacy_flows=flows), "kept_tasks"
    tasks = []
    for flow in flows:
        fid = flow.get("id", "sync_merge_build_release")
        # All imported identifiers, including legacy flow identities, obey the same boundary.
        from toolbox_backend.domain.settings import identifier

        identifier(fid)
        source, target = flow.get("source_branch", ""), flow.get("target_branch", "")
        merging = fid == "sync_merge_build_release"
        cmd = re.sub(r"_+", "_", re.sub(r"[^a-z0-9_]", "_", fid.lower().strip())).strip("_")
        targets = flow.get("targets", [])
        if not targets and any(
            flow.get(k) for k in ("build_id", "release_id", "release_stage_ids")
        ):
            targets = [
                {
                    k: flow[k]
                    for k in (
                        "build_kind",
                        "build_id",
                        "build_name",
                        "release_id",
                        "release_name",
                        "release_stage_ids",
                        "release_stage_names",
                    )
                    if k in flow
                }
            ]
        labels = {
            "sync_build_release": ("同步 + 构建 + 发布", "同步 + 构建 + 发布（无合并）"),
            "sync_merge_build_release": ("同步/合并 + 构建 + 发布", "同步/合并 + 构建 + 发布"),
        }
        display, desc = labels.get(fid, (fid, ""))
        tasks.append(
            DynamicTask.model_validate(
                {
                    "id": str(uuid.uuid4()),
                    "enabled": flow.get("enabled", True),
                    "name": display,
                    "tg_command": (cmd or "task")[:32],
                    "tg_desc": desc,
                    **{
                        k: flow[k]
                        for k in (
                            "project_id",
                            "local_repo_path",
                            "repo_id",
                            "repo_name",
                        )
                        if k in flow
                    },
                    "git_flow": {
                        "build_branch": target,
                        "update_branches": [
                            x for x in ([source, target] if merging else [target]) if x
                        ],
                        "merges": [{"source": source, "target": target}]
                        if merging and source and target
                        else [],
                        "push_branches": [target] if merging and target else [],
                    },
                    "targets": targets,
                    "legacy_flow_id": fid,
                }
            )
        )
    return Tasks(items=tasks, legacy_flows=flows), "migrated_from_flows" if flows else "empty"


class LegacyConfig:
    def __init__(self, directory: Path):
        self.directory = directory

    def read(self) -> LegacyPlan:
        originals = {}
        parsed = {}
        errors: list[str] = []
        warnings: list[str] = []
        file_states = []
        digest = hashlib.sha256()
        root = self.directory.resolve()
        for filename in FILES:
            digest.update(filename.encode() + b"\0")
            path = root / filename
            try:
                if not path.resolve().is_relative_to(root):
                    raise ValueError("文件符号链接越界")
                with path.open("rb") as stream:
                    data = stream.read(MAX_FILE_BYTES + 1)
                if len(data) > MAX_FILE_BYTES:
                    raise ValueError("文件超过 1 MiB")
                digest.update(b"present\0" + len(data).to_bytes(8, "big") + data)
                originals[filename] = data
                value = yaml.safe_load(data)
                if value is None:
                    value = {}
                if not isinstance(value, dict):
                    raise ValueError("配置必须为对象")
                # Refuse YAML timestamps, binary values, non-string keys and cycles.
                encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
                value = json.loads(encoded)
                parsed[filename] = value
                file_states.append({"name": filename, "state": "present"})
            except FileNotFoundError:
                digest.update(b"missing\0")
                file_states.append({"name": filename, "state": "missing"})
            except OSError, ValueError, TypeError, yaml.YAMLError, RecursionError:
                # Parser/validation exceptions may contain user data. Never echo them.
                errors.append(f"{filename}: 无法安全解析或文件越界/超限")
                file_states.append({"name": filename, "state": "error"})
        config = Config()
        rule = "empty"
        try:
            ui = parsed.get("ui_settings.yaml", {})
            tasks_raw = parsed.get("tasks.yaml", {})
            ado_keys = {
                "libraries",
                "projects",
                "local_repos",
                "active_library_id",
                "active_project_id",
            }
            ado = {key: ui[key] for key in ado_keys if key in ui}
            projects = []
            for project in ado.get("projects", []):
                aliases = {
                    "id": ("id", "project_id"),
                    "library_id": ("library_id", "repo_id"),
                    "collection": ("collection", "collection_name"),
                    "project": ("project", "name", "project_name"),
                }
                normalized = {}
                for key, candidates in aliases.items():
                    for candidate in candidates:
                        if project.get(candidate) not in (None, ""):
                            normalized[key] = project[candidate]
                            if key != candidate:
                                warnings.append("历史项目别名字段已规范化")
                            break
                projects.append(normalized)
            ado["projects"] = projects
            config.ado = Ado.model_validate(ado)
            config.tasks, rule = migrate_tasks(tasks_raw)
            telegram = {
                k.removeprefix("telegram_"): v for k, v in ui.items() if k.startswith("telegram_")
            }
            mapping = {
                getattr(t, "legacy_flow_id", ""): t.id
                for t in config.tasks.items
                if getattr(t, "legacy_flow_id", "")
            }
            groups = telegram.get("acl_groups", [])
            if isinstance(groups, list):
                for group in groups:
                    if isinstance(group, dict) and isinstance(group.get("task_ids"), list):
                        group["task_ids"] = [mapping.get(str(t), str(t)) for t in group["task_ids"]]
            from toolbox_backend.domain.telegram import migrate_telegram

            config.telegram = migrate_telegram(telegram)
            config.imported = Imported.model_validate(
                {
                    "work_items": {
                        k.removeprefix("work_items_"): v
                        for k, v in ui.items()
                        if k.startswith("work_items_")
                    },
                    "ai": ui.get("ai", {}),
                    "lark": parsed.get("lark_settings.yaml", {}),
                    "figma": parsed.get("figma_settings.yaml", {}),
                    "extra": {
                        "ui_settings": {
                            k: v
                            for k, v in ui.items()
                            if k not in ado_keys | {"ai"}
                            and not k.startswith(("telegram_", "work_items_"))
                        },
                        "tasks": {
                            k: v for k, v in tasks_raw.items() if k not in {"tasks", "flows"}
                        },
                    },
                }
            )
            # Check unknown task fields for JSON serializability as well.
            config.model_dump_json()
            for lib in config.ado.libraries:
                if lib.base_url.startswith("http:"):
                    warnings.append("ADO 地址使用 HTTP 明文传输")
        except ValidationError, ValueError, TypeError, AttributeError, RecursionError:
            errors.append("旧配置字段、标识或引用校验失败")
        summary = {
            "source_dir": str(self.directory),
            "files": file_states,
            "libraries": [lib.model_dump() for lib in config.ado.libraries],
            "projects": [p.model_dump() for p in config.ado.projects],
            "tasks_rule": rule,
            "task_count": len(config.tasks.items),
            "preserved_sections": ["telegram", "work_items", "ai", "lark", "figma", "extra"],
            "warnings": sorted(set(warnings)),
            "errors": errors,
        }
        return LegacyPlan(digest.hexdigest(), originals, config, summary)
