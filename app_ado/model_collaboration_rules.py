from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

START_MARKER = "<!-- my-own-script:model-collaboration:start -->"
END_MARKER = "<!-- my-own-script:model-collaboration:end -->"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PROJECT_ROOT / "config" / "model_collaboration_templates"

GLOBAL_ROOTS = {
    "codex": Path("/Users/wesker/.codex"),
    "claude": Path("/Users/wesker/.claude"),
    "gemini": Path("/Users/wesker/.gemini"),
}

PRIMARY_RULE_FILES = {
    "codex": "AGENTS.md",
    "claude": "CLAUDE.md",
    "gemini": "GEMINI.md",
}

OPTIONAL_BUNDLE_FILES = {
    "codex": {"config.toml.template"},
    "claude": set(),
    "gemini": {"settings.json"},
}


@dataclass
class RuleApplyResult:
    title: str
    summary: str
    details: str
    ok: bool = True


def _model_template_root(model_id: str) -> Path:
    root = TEMPLATE_DIR / model_id
    if not root.exists():
        raise KeyError(f"未知模型：{model_id}")
    return root


def _bundle_files(model_id: str) -> list[str]:
    root = _model_template_root(model_id)
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


def _primary_rule_file(model_id: str) -> str:
    name = PRIMARY_RULE_FILES.get(model_id)
    if name is None:
        raise KeyError(f"未知模型：{model_id}")
    return name


def _optional_bundle_files(model_id: str) -> set[str]:
    return set(OPTIONAL_BUNDLE_FILES.get(model_id, set()))


def _is_primary_rule(model_id: str, relative_name: str) -> bool:
    return relative_name == _primary_rule_file(model_id)


def global_rule_path(model_id: str) -> Path:
    return GLOBAL_ROOTS[model_id] / _primary_rule_file(model_id)


def repo_rule_path(model_id: str, repo_root: Path) -> Path:
    return repo_root / _primary_rule_file(model_id)


def template_rule_path(model_id: str) -> Path:
    return TEMPLATE_DIR / model_id / _primary_rule_file(model_id)


def _template_bundle_paths(model_id: str) -> dict[str, Path]:
    root = _model_template_root(model_id)
    return {name: root / name for name in _bundle_files(model_id)}


def _global_bundle_paths(model_id: str) -> dict[str, Path]:
    root = GLOBAL_ROOTS.get(model_id)
    if root is None:
        raise KeyError(f"未知模型：{model_id}")
    return {name: root / name for name in _bundle_files(model_id)}


def _repo_bundle_paths(model_id: str, repo_root: Path) -> dict[str, Path]:
    return {name: repo_root / name for name in _bundle_files(model_id)}


def _fragments_from_sources(sources: dict[str, Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for relative_name, path in sources.items():
        if not path.exists():
            raise FileNotFoundError(f"规则源文件不存在：{path}")
        text = path.read_text("utf-8")
        out[relative_name] = "\n".join(
            [
                START_MARKER,
                f"<!-- source: {path} -->",
                text.rstrip(),
                END_MARKER,
                "",
            ]
        )
    return out


def _payloads_from_sources(model_id: str, sources: dict[str, Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for relative_name, path in sources.items():
        if not path.exists():
            raise FileNotFoundError(f"规则源文件不存在：{path}")
        text = path.read_text("utf-8")
        if _is_primary_rule(model_id, relative_name):
            out[relative_name] = "\n".join(
                [
                    START_MARKER,
                    f"<!-- source: {path} -->",
                    text.rstrip(),
                    END_MARKER,
                    "",
                ]
            )
        else:
            out[relative_name] = text
    return out


def source_rule_fragment(model_id: str) -> str:
    return _fragments_from_sources({_primary_rule_file(model_id): template_rule_path(model_id)})[_primary_rule_file(model_id)]


def _source_bundle_payloads(model_id: str) -> dict[str, str]:
    return _payloads_from_sources(model_id, _template_bundle_paths(model_id))


def _replace_managed_block(text: str, fragment: str) -> str:
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start >= 0 and end >= 0 and end >= start:
        end += len(END_MARKER)
        prefix = text[:start].rstrip()
        suffix = text[end:].lstrip("\n")
        out = prefix + ("\n\n" if prefix else "") + fragment.rstrip() + "\n"
        if suffix:
            out += "\n" + suffix
        return out
    if text and not text.endswith("\n"):
        text += "\n"
    if text.strip():
        return text.rstrip() + "\n\n" + fragment
    return fragment


def _remove_managed_block(text: str) -> tuple[str, bool]:
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start < 0 or end < 0 or end < start:
        return text, False
    end += len(END_MARKER)
    prefix = text[:start].rstrip()
    suffix = text[end:].lstrip("\n")
    out = prefix
    if prefix and suffix:
        out += "\n\n"
    out += suffix
    if out and not out.endswith("\n"):
        out += "\n"
    return out, True


def _write_payloads(targets: dict[str, Path], payloads: dict[str, str], model_id: str) -> RuleApplyResult:
    details: list[str] = []
    for name, path in targets.items():
        existing = path.read_text("utf-8") if path.exists() else ""
        payload = payloads.get(name)
        if payload is None:
            details.append(f"{name}: 找不到可复用的源规则，跳过 {path}")
            continue
        if _is_primary_rule(model_id, name):
            updated = _replace_managed_block(existing, payload)
            action = "已写入"
        elif path.exists() and existing != payload:
            details.append(f"{name}: 已存在且内容不同，跳过 {path}")
            continue
        else:
            updated = payload
            action = "已复制"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated, "utf-8")
        details.append(f"{name}: {action} {path}")
    return RuleApplyResult("保存规则", f"{model_id} 规则已写入", "\n".join(details))


def _remove_payloads(targets: dict[str, Path], payloads: dict[str, str], model_id: str) -> RuleApplyResult:
    details: list[str] = []
    removed_any = False
    for name, path in targets.items():
        if not path.exists():
            details.append(f"{name}: 文件不存在，跳过 {path}")
            continue
        existing = path.read_text("utf-8")
        if not _is_primary_rule(model_id, name):
            if existing == payloads.get(name):
                path.unlink()
                removed_any = True
                details.append(f"{name}: 已删除模板文件 {path}")
            else:
                details.append(f"{name}: 内容不同，跳过 {path}")
            continue
        updated, removed = _remove_managed_block(existing)
        if removed:
            path.write_text(updated, "utf-8")
            removed_any = True
            details.append(f"{name}: 已删除规则片段 {path}")
        else:
            details.append(f"{name}: 未找到规则片段 {path}")
    summary = f"{model_id} 规则已删除" if removed_any else f"{model_id} 未找到可删除的规则片段"
    return RuleApplyResult("删除规则", summary, "\n".join(details), ok=removed_any)


def inspect_rule_target(model_id: str, target: Path) -> RuleApplyResult:
    target_root = target.parent
    template_paths = _template_bundle_paths(model_id)
    target_paths = {name: target_root / name for name in template_paths}
    details: list[str] = []
    deployed_count = 0
    required_total = 0
    optional_files = _optional_bundle_files(model_id)
    for name, template_path in template_paths.items():
        is_optional = name in optional_files
        if not is_optional:
            required_total += 1
        target_path = target_paths[name]
        if not target_path.exists():
            label = "附加文件缺失" if is_optional else "缺失"
            details.append(f"{name}: {label} {target_path}")
            continue
        target_text = target_path.read_text("utf-8")
        template_text = template_path.read_text("utf-8")
        has_managed_block = START_MARKER in target_text and END_MARKER in target_text
        matches_template = target_text == template_text
        if has_managed_block or matches_template:
            if not is_optional:
                deployed_count += 1
            label = "已部署"
            details.append(f"{name}: {label} {target_path}")
        else:
            label = "附加文件内容不匹配" if is_optional else "存在但内容不匹配"
            details.append(f"{name}: {label} {target_path}")
    if deployed_count == required_total:
        summary = "已部署"
    elif deployed_count > 0:
        summary = f"部分部署（{deployed_count}/{required_total}）"
    else:
        summary = "未部署"
    return RuleApplyResult("规则状态", summary, "\n".join(details), ok=True)


def inspect_template_target(model_id: str) -> RuleApplyResult:
    missing = [str(path) for path in _template_bundle_paths(model_id).values() if not path.exists()]
    if missing:
        return RuleApplyResult("模板状态", "模板缺失", "\n".join(missing), ok=False)
    return RuleApplyResult("模板状态", "模板已就绪", model_id, ok=True)


def apply_rules_to_global() -> RuleApplyResult:
    return apply_rule_to_global("codex")


def apply_rules_to_repo(repo_root: Path) -> RuleApplyResult:
    return apply_rule_to_repo("codex", repo_root)


def apply_rule_to_global(model_id: str) -> RuleApplyResult:
    return _write_payloads(_global_bundle_paths(model_id), _source_bundle_payloads(model_id), model_id)


def apply_rule_to_repo(model_id: str, repo_root: Path) -> RuleApplyResult:
    return _write_payloads(_repo_bundle_paths(model_id, repo_root), _source_bundle_payloads(model_id), model_id)


def remove_rules_from_global() -> RuleApplyResult:
    return remove_rule_from_global("codex")


def remove_rules_from_repo(repo_root: Path) -> RuleApplyResult:
    return remove_rule_from_repo("codex", repo_root)


def remove_rule_from_global(model_id: str) -> RuleApplyResult:
    return _remove_payloads(_global_bundle_paths(model_id), _source_bundle_payloads(model_id), model_id)


def remove_rule_from_repo(model_id: str, repo_root: Path) -> RuleApplyResult:
    return _remove_payloads(_repo_bundle_paths(model_id, repo_root), _source_bundle_payloads(model_id), model_id)
