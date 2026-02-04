from __future__ import annotations

from ui_app.settings_store import UiSettings
from ui_app.tasks_store import FlowTaskConfig


def flow_subtitle_cn(settings: UiSettings, flow: FlowTaskConfig) -> str:
    if not flow.project_id:
        return "（未配置：请选择项目/仓库/分支）"

    proj_name = None
    collection = None
    for p in settings.projects:
        if p.id == flow.project_id:
            proj_name = p.project
            collection = p.collection
            break

    repo = flow.repo_name or (flow.repo_id or "")
    if flow.source_branch and flow.target_branch:
        merge = f"把「{flow.source_branch}」合并到「{flow.target_branch}」"
    else:
        merge = "请选择源分支/目标分支"

    bits = []
    if proj_name:
        bits.append(f"项目：{proj_name} ({collection})" if collection else f"项目：{proj_name}")
    if repo:
        bits.append(f"仓库：{repo}")
    bits.append(merge)
    if flow.build_name:
        bits.append(f"构建：{flow.build_name}")
    if flow.release_name:
        if flow.release_stage_name:
            bits.append(f"发布：{flow.release_name} → {flow.release_stage_name}")
        else:
            bits.append(f"发布：{flow.release_name}")

    return " | ".join(bits)
