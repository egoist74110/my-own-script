from __future__ import annotations

from app_ado.models import FlowTaskConfig, UiSettings


def flow_summary_cn(settings: UiSettings, flow: FlowTaskConfig) -> str:
    proj = next((p for p in settings.projects if p.id == flow.project_id), None)
    bits: list[str] = []
    if proj:
        bits.append(f"项目：{proj.project} ({proj.collection})")
    if flow.repo_name:
        bits.append(f"仓库：{flow.repo_name}")
    if flow.source_branch and flow.target_branch:
        bits.append(f"把「{flow.source_branch}」合并到「{flow.target_branch}」")
    if flow.build_name:
        bits.append(f"构建：{flow.build_name}")
    if flow.release_name:
        if flow.release_stage_names:
            bits.append(f"发布：{flow.release_name} → {', '.join(flow.release_stage_names)}")
        else:
            bits.append(f"发布：{flow.release_name}")
    return " | ".join(bits) if bits else "（未配置）"
