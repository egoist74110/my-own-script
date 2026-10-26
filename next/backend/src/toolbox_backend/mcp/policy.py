"""Pure policy evaluation ported from app_ado.ai_policy; explicit baseline import only."""

import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.logging_setup import contains_secret
from toolbox_backend.mcp.runner import secure_directory


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
    combined_text = "\n".join(
        [title, desc, state, work_item_type, tags, board_column, str(change_summary or "")]
    ).lower()

    deny_keywords = [str(x) for x in (policy.get("deny_keywords") or []) if str(x).strip()]
    review_keywords = [str(x) for x in (policy.get("review_keywords") or []) if str(x).strip()]
    forbidden_paths = [
        str(x).strip() for x in (policy.get("forbidden_paths") or []) if str(x).strip()
    ]
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

    allowed_types = {
        _normalize_text(x) for x in (policy.get("allowed_work_item_types") or []) if str(x).strip()
    }
    review_types = {
        _normalize_text(x) for x in (policy.get("review_work_item_types") or []) if str(x).strip()
    }
    deny_types = {
        _normalize_text(x) for x in (policy.get("deny_work_item_types") or []) if str(x).strip()
    }
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
        reasons.append(
            "目标文件命中禁止改动路径：" + "、".join(_unique_keep_order(forbidden_paths_hit))
        )

    if decision != "deny":
        if normalized_type and normalized_type in review_types:
            decision = "review"
            reasons.append(f"工单类型要求人工复核：{work_item_type}")
        elif normalized_type and allowed_types and normalized_type not in allowed_types:
            decision = "review"
            reasons.append(f"工单类型不在自动放行列表：{work_item_type}")

        if matched_review_keywords:
            decision = "review"
            reasons.append(
                "命中需人工复核关键词：" + "、".join(_unique_keep_order(matched_review_keywords))
            )

        if review_paths_hit:
            decision = "review"
            reasons.append(
                "目标文件命中复核路径：" + "、".join(_unique_keep_order(review_paths_hit))
            )

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


def merge_policy(base, override):
    out = dict(base)
    for key, value in (override or {}).items():
        if key == "max_target_files_without_review":
            if int(value or 0) > 0:
                out[key] = int(value)
        elif key == "require_human_review_if_no_target_paths":
            if value is not None:
                out[key] = bool(value)
        elif isinstance(value, list):
            if value:
                out[key] = list(value)
        elif isinstance(value, str):
            if value.strip():
                out[key] = value.strip()
        elif value is not None:
            out[key] = value
    return out


def load_policy(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("invalid policy file")
        raw = stream.read((1 << 20) + 1)
    if len(raw) > 1 << 20 or contains_secret(raw.decode("utf-8")):
        raise ValueError("invalid policy")
    policy = yaml.safe_load(raw)
    if not isinstance(policy, dict) or policy.get("default_decision", "review") not in {
        "allow",
        "review",
        "deny",
    }:
        raise ValueError("invalid policy")
    return policy


def import_policy(source: Path, data_dir: Path):
    try:
        policy = load_policy(source)
        parent = secure_directory(data_dir, "mcp")
        target = parent / "ai_change_policy.yaml"
        # O_EXCL is the one-time import boundary; never overwrites an accepted baseline.
        raw = yaml.safe_dump(policy, allow_unicode=True).encode()
        temporary = parent / (".policy-" + uuid.uuid4().hex)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, target, follow_symlinks=False)
        finally:
            temporary.unlink(missing_ok=True)
    except FileExistsError:
        raise SettingsError("validation_error", "策略基线已导入", 409) from None
    except OSError, ValueError, yaml.YAMLError:
        raise SettingsError("validation_error", "策略基线无效或不可读", 422) from None
