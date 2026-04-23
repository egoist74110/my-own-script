from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app_ado.models import AiPolicyConfig, ProjectAiSettings, UiSettings
from app_ado.store import load_ui_settings


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def policy_path() -> Path:
    return _repo_root() / "config" / "ai_change_policy.yaml"


@dataclass(frozen=True)
class PolicyEvaluation:
    decision: str
    reasons: list[str]
    matched_deny_keywords: list[str]
    matched_review_keywords: list[str]
    forbidden_paths_hit: list[str]
    review_paths_hit: list[str]
    target_paths: list[str]
    recommended_action: str


def load_ai_change_policy() -> dict[str, Any]:
    p = policy_path()
    if not p.exists():
        raise RuntimeError(f"找不到策略文件：{p}")
    raw = yaml.safe_load(p.read_text("utf-8")) or {}
    if not isinstance(raw, dict):
        raise RuntimeError("策略文件格式错误，根节点必须是对象")
    return raw


def _policy_model_to_dict(policy: AiPolicyConfig) -> dict[str, Any]:
    return {
        "default_decision": policy.default_decision,
        "allowed_work_item_types": list(policy.allowed_work_item_types),
        "review_work_item_types": list(policy.review_work_item_types),
        "deny_work_item_types": list(policy.deny_work_item_types),
        "deny_keywords": list(policy.deny_keywords),
        "review_keywords": list(policy.review_keywords),
        "forbidden_paths": list(policy.forbidden_paths),
        "review_paths": list(policy.review_paths),
        "max_target_files_without_review": int(policy.max_target_files_without_review or 0),
        "require_human_review_if_no_target_paths": policy.require_human_review_if_no_target_paths,
    }


def _policy_override_is_blank(policy: AiPolicyConfig) -> bool:
    data = _policy_model_to_dict(policy)
    for key, value in data.items():
        if key == "max_target_files_without_review":
            if int(value or 0) != 0:
                return False
            continue
        if value not in ("", [], None):
            return False
    return True


def _merge_policy(base: dict[str, Any], override: AiPolicyConfig | dict[str, Any] | None) -> dict[str, Any]:
    out = dict(base)
    if override is None:
        return out
    raw = _policy_model_to_dict(override) if isinstance(override, AiPolicyConfig) else dict(override)
    for key, value in raw.items():
        if key == "max_target_files_without_review":
            if int(value or 0) > 0:
                out[key] = int(value)
            continue
        if key == "require_human_review_if_no_target_paths":
            if value is not None:
                out[key] = bool(value)
            continue
        if isinstance(value, list):
            if value:
                out[key] = list(value)
            continue
        if isinstance(value, str):
            if value.strip():
                out[key] = value.strip()
            continue
        if value is not None:
            out[key] = value
    return out


def load_runtime_ai_settings() -> UiSettings:
    return load_ui_settings()


def get_project_ai_settings(project_id: str | None, settings: UiSettings | None = None) -> ProjectAiSettings | None:
    if not project_id:
        return None
    settings = settings or load_runtime_ai_settings()
    return (settings.ai.project_overrides or {}).get(project_id)


def load_effective_ai_change_policy(project_id: str | None = None, settings: UiSettings | None = None) -> dict[str, Any]:
    base = load_ai_change_policy()
    settings = settings or load_runtime_ai_settings()

    global_policy = settings.ai.default_policy
    if not _policy_override_is_blank(global_policy):
        base = _merge_policy(base, global_policy)

    project_cfg = get_project_ai_settings(project_id, settings=settings)
    if project_cfg and not project_cfg.use_default_policy:
        base = _merge_policy(base, project_cfg.policy)
    return base


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def evaluate_change_policy(
    policy: dict[str, Any],
    *,
    work_item: dict[str, Any] | None = None,
    target_paths: list[str] | None = None,
    change_summary: str | None = None,
) -> PolicyEvaluation:
    work_item = work_item or {}
    target_paths = [str(x).strip() for x in (target_paths or []) if str(x).strip()]
    fields = dict(work_item.get("fields") or {})

    title = str(work_item.get("title") or fields.get("System.Title") or "")
    desc = str(fields.get("System.Description") or "")
    state = str(work_item.get("state") or fields.get("System.State") or "")
    work_item_type = str(work_item.get("work_item_type") or fields.get("System.WorkItemType") or "")
    tags = str(fields.get("System.Tags") or "")
    board_column = str(work_item.get("board_column") or fields.get("System.BoardColumn") or "")
    combined_text = "\n".join([title, desc, state, work_item_type, tags, board_column, str(change_summary or "")]).lower()

    deny_keywords = [str(x) for x in (policy.get("deny_keywords") or []) if str(x).strip()]
    review_keywords = [str(x) for x in (policy.get("review_keywords") or []) if str(x).strip()]
    forbidden_paths = [str(x).strip() for x in (policy.get("forbidden_paths") or []) if str(x).strip()]
    review_paths = [str(x).strip() for x in (policy.get("review_paths") or []) if str(x).strip()]

    matched_deny_keywords = [x for x in deny_keywords if x.lower() in combined_text]
    matched_review_keywords = [x for x in review_keywords if x.lower() in combined_text]

    forbidden_paths_hit: list[str] = []
    review_paths_hit: list[str] = []
    for path in target_paths:
        p = path.replace("\\", "/").lstrip("./")
        for blocked in forbidden_paths:
            b = blocked.replace("\\", "/").lstrip("./")
            if p == b or p.startswith(b + "/"):
                forbidden_paths_hit.append(blocked)
        for watched in review_paths:
            w = watched.replace("\\", "/").lstrip("./")
            if p == w or p.startswith(w + "/"):
                review_paths_hit.append(watched)

    allowed_types = {_normalize_text(x) for x in (policy.get("allowed_work_item_types") or []) if str(x).strip()}
    review_types = {_normalize_text(x) for x in (policy.get("review_work_item_types") or []) if str(x).strip()}
    deny_types = {_normalize_text(x) for x in (policy.get("deny_work_item_types") or []) if str(x).strip()}
    normalized_type = _normalize_text(work_item_type)

    reasons: list[str] = []
    decision = str(policy.get("default_decision") or "review").strip().lower()

    if normalized_type and normalized_type in deny_types:
        decision = "deny"
        reasons.append(f"工单类型被策略禁止：{work_item_type}")

    if matched_deny_keywords:
        decision = "deny"
        reasons.append("命中高风险关键词：" + "、".join(_unique_keep_order(matched_deny_keywords)))

    if forbidden_paths_hit:
        decision = "deny"
        reasons.append("目标文件命中禁止改动路径：" + "、".join(_unique_keep_order(forbidden_paths_hit)))

    if decision != "deny":
        if normalized_type and normalized_type in review_types:
            decision = "review"
            reasons.append(f"工单类型要求人工复核：{work_item_type}")
        elif normalized_type and allowed_types and normalized_type not in allowed_types:
            decision = "review"
            reasons.append(f"工单类型不在自动放行列表：{work_item_type}")

        if matched_review_keywords:
            decision = "review"
            reasons.append("命中需人工复核关键词：" + "、".join(_unique_keep_order(matched_review_keywords)))

        if review_paths_hit:
            decision = "review"
            reasons.append("目标文件命中复核路径：" + "、".join(_unique_keep_order(review_paths_hit)))

        max_files = int(policy.get("max_target_files_without_review") or 0)
        if max_files > 0 and len(target_paths) > max_files:
            decision = "review"
            reasons.append(f"目标文件数超过阈值：{len(target_paths)} > {max_files}")

        if bool(policy.get("require_human_review_if_no_target_paths")) and not target_paths:
            decision = "review"
            reasons.append("未提供目标文件，策略要求先人工确认影响范围")

    if not reasons:
        reasons.append("未命中禁止或复核规则，可按低风险流程执行")

    if decision == "allow":
        action = "允许 AI 在当前仓库内继续分析并提交候选补丁，但仍建议保留最终人工 review。"
    elif decision == "review":
        action = "允许 AI 继续分析，但改代码前需要人工确认范围；合并前必须人工 review。"
    else:
        action = "禁止 AI 自动改代码；仅允许读取工单、分析问题并输出建议。"

    return PolicyEvaluation(
        decision=decision,
        reasons=_unique_keep_order(reasons),
        matched_deny_keywords=_unique_keep_order(matched_deny_keywords),
        matched_review_keywords=_unique_keep_order(matched_review_keywords),
        forbidden_paths_hit=_unique_keep_order(forbidden_paths_hit),
        review_paths_hit=_unique_keep_order(review_paths_hit),
        target_paths=target_paths,
        recommended_action=action,
    )
