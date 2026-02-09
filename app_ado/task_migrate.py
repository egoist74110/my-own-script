from __future__ import annotations

import re
import uuid
from typing import Any

from app_ado.models import DeployTarget, DynamicTaskConfig, FlowTaskConfig, GitFlow, GitMergeRule, TaskSettings


_CMD_RE = re.compile(r"^[a-z0-9_]{1,32}$")


def _default_desc(flow_id: str) -> str:
    if flow_id == "sync_build_release":
        return "同步 + 构建 + 发布（无合并）"
    if flow_id == "sync_merge_build_release":
        return "同步/合并 + 构建 + 发布"
    return ""


def _default_name(flow_id: str) -> str:
    if flow_id == "sync_build_release":
        return "同步 + 构建 + 发布"
    if flow_id == "sync_merge_build_release":
        return "同步/合并 + 构建 + 发布"
    return flow_id


def _default_command(flow_id: str) -> str:
    # Keep old id as default command to minimize surprise; user can edit later.
    cmd = flow_id.lower().strip().replace("-", "_")
    cmd = re.sub(r"[^a-z0-9_]", "_", cmd)
    cmd = re.sub(r"_+", "_", cmd).strip("_")
    if not cmd:
        cmd = "task"
    return cmd[:32]


def _migrate_targets(flow: FlowTaskConfig) -> list[DeployTarget]:
    targets = list(getattr(flow, "targets", []) or [])
    if targets:
        return targets

    # back-compat single target
    if flow.build_id or flow.release_id or (flow.release_stage_ids or []):
        return [
            DeployTarget(
                name="目标1",
                enabled=True,
                build_kind=flow.build_kind,
                build_id=flow.build_id,
                build_name=flow.build_name,
                release_id=flow.release_id,
                release_name=flow.release_name,
                release_stage_ids=list(flow.release_stage_ids or []),
                release_stage_names=list(flow.release_stage_names or []),
            )
        ]

    return []


def migrate_task_settings(raw: Any) -> tuple[TaskSettings, bool]:
    """Return (settings, changed)."""
    s = TaskSettings.model_validate(raw or {})

    # If tasks already exist, still run light migrations (schema evolution).
    if s.tasks:
        changed = False
        for t in (s.tasks or []):
            try:
                gf = t.git_flow
                build_branch = (getattr(gf, "build_branch", "") or "").strip()
                if not build_branch:
                    merges = list(getattr(gf, "merges", []) or [])
                    update_branches = [str(x).strip() for x in (getattr(gf, "update_branches", []) or []) if str(x).strip()]
                    # prefer last merge target, else last update branch
                    inferred = (merges[-1].target if merges else (update_branches[-1] if update_branches else ""))
                    if inferred:
                        gf.build_branch = inferred
                        changed = True
            except Exception:
                continue
        return s, changed

    changed = False

    # Migrate legacy flows -> tasks
    if s.flows:
        new_tasks: list[DynamicTaskConfig] = []
        for flow in s.flows:
            flow_id = flow.id or ""
            # Git flow mapping
            if flow_id == "sync_merge_build_release":
                update_branches = [x for x in [flow.source_branch, flow.target_branch] if x]
                merges = [GitMergeRule(source=flow.source_branch, target=flow.target_branch)] if (flow.source_branch and flow.target_branch) else []
                push_branches = [flow.target_branch] if flow.target_branch else []
            else:
                update_branches = [flow.target_branch] if flow.target_branch else []
                merges = []
                push_branches = []

            build_branch = (flow.target_branch or "") or (merges[-1].target if merges else (update_branches[-1] if update_branches else ""))
            git_flow = GitFlow(build_branch=build_branch, update_branches=update_branches, merges=merges, push_branches=push_branches)

            cmd = _default_command(flow_id)
            # Ensure cmd is valid
            if not _CMD_RE.match(cmd):
                cmd = f"task_{uuid.uuid4().hex[:8]}"

            t = DynamicTaskConfig(
                id=str(uuid.uuid4()),
                enabled=getattr(flow, "enabled", True),
                name=_default_name(flow_id),
                tg_command=cmd,
                tg_desc=_default_desc(flow_id),
                project_id=flow.project_id,
                local_repo_path=flow.local_repo_path,
                repo_id=flow.repo_id,
                repo_name=flow.repo_name,
                git_flow=git_flow,
                targets=_migrate_targets(flow),
                legacy_flow_id=flow_id,
            )
            new_tasks.append(t)

        s.tasks = new_tasks
        changed = True

    return s, changed
