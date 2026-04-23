from __future__ import annotations

import html
import json
import re
import shlex
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app_ado.ado_work_item_http import WorkItem, WorkItemComment, WorkItemUpdate, download_authenticated_file, get_work_item, get_work_item_comments, get_work_item_updates
from app_ado.ai_policy import PolicyEvaluation
from app_ado.models import AiCliProfile, LibraryEntry, LocalRepoEntry, ProjectEntry, UiSettings


@dataclass(frozen=True)
class WorkItemContext:
    work_item: WorkItem
    notes: list[str]
    notes_source: str
    image_paths: list[str]


def selected_ai_profile(settings: UiSettings) -> AiCliProfile | None:
    pid = settings.ai.tool.selected_profile_id
    for profile in settings.ai.tool.profiles or []:
        if profile.id == pid:
            return profile
    return None


def load_work_item_context(lib: LibraryEntry, proj: ProjectEntry, pat: str, work_item_id: int) -> WorkItemContext:
    item = get_work_item(
        lib.base_url,
        work_item_id,
        collection=proj.collection,
        project=proj.project,
        pat=pat,
        expand_relations=True,
    )
    try:
        comments = get_work_item_comments(lib.base_url, proj.collection, proj.project, work_item_id, pat=pat, top=10)
        notes = _notes_from_comments(comments)
        source = "comments"
    except Exception:
        updates = get_work_item_updates(lib.base_url, proj.collection, proj.project, work_item_id, pat=pat, top=10)
        notes = _notes_from_updates(updates)
        source = "updates"
    image_paths = _prepare_local_images(item=item, pat=pat)
    return WorkItemContext(work_item=item, notes=notes, notes_source=source, image_paths=image_paths)


def selected_local_repo(settings: UiSettings) -> LocalRepoEntry | None:
    rid = settings.work_items_local_repo_id
    for repo in settings.local_repos or []:
        if repo.id == rid:
            return repo
    return None


def tool_workspace_root() -> Path:
    return Path(__file__).resolve().parent.parent


def matched_workspace_repo(settings: UiSettings) -> LocalRepoEntry | None:
    root = tool_workspace_root().resolve()
    for repo in settings.local_repos or []:
        try:
            if Path(repo.path).expanduser().resolve() == root:
                return repo
        except Exception:
            continue
    return None


def build_prompt(
    *,
    mode: str,
    settings: UiSettings,
    project: ProjectEntry,
    context: WorkItemContext,
    policy: PolicyEvaluation,
) -> str:
    mode_label = "分析" if mode == "analyze" else "修复"
    prompt_parts: list[str] = []
    workspace_root = tool_workspace_root()
    workspace_repo = matched_workspace_repo(settings)

    default_prompt = (settings.ai.tool.prompt_template or "").strip()
    if default_prompt:
        prompt_parts.append(default_prompt)

    prompt_parts.append(f"当前任务：{mode_label} ADO 工单 #{context.work_item.id}")
    prompt_parts.append(
        "\n".join(
            [
                "执行约束：",
                f"- 策略结论：{policy.decision}",
                f"- 策略说明：{'；'.join(policy.reasons)}",
                f"- 建议动作：{policy.recommended_action}",
                f"- 当前运行目录：{workspace_root}",
                "- 不要编造未确认的信息。",
                "- 先基于当前仓库和工单上下文做判断。",
            ]
        )
    )

    repo_lines = ["仓库确认规则："]
    if workspace_repo is not None:
        repo_lines.append(f"- 当前运行目录命中已配置仓库：{workspace_repo.name} ({workspace_repo.path})")
        repo_lines.append("- 可以直接基于当前运行目录开始分析或修改。")
    else:
        repo_lines.append("- 当前运行目录未命中任何已配置仓库。")
    if settings.local_repos:
        repo_lines.append("- 已配置本地仓库：")
        for repo in settings.local_repos:
            repo_lines.append(f"  {repo.name}: {repo.path}")
    if workspace_repo is None:
        repo_lines.append("- 因为当前运行目录不在已配置仓库列表中，不要直接改代码。")
        repo_lines.append("- 先让用户确认应该使用哪个本地仓库，再继续。")
    repo_lines.append("- 如果你无法确认应该操作哪个仓库，只允许分析，不要提交修改。")
    prompt_parts.append("\n".join(repo_lines))

    if mode == "fix":
        if policy.decision == "deny":
            prompt_parts.append("本次只允许分析问题、定位影响范围、给出修改建议，不允许直接改代码。")
        elif not settings.ai.allow_direct_code_change:
            prompt_parts.append("先给出修改计划和目标文件，得到确认后再改代码。")
        elif policy.decision == "review":
            prompt_parts.append("允许继续推进，但改代码前先确认影响文件和验证方式。")
        else:
            prompt_parts.append("可以在当前仓库内继续修复，并在完成后说明修改点与验证结果。")
    else:
        prompt_parts.append("请优先总结需求、疑点、影响范围、建议修改点。")

    fields = context.work_item.fields or {}
    prompt_parts.append(
        "\n".join(
            [
                "工单信息：",
                f"- 项目：{project.project}",
                f"- ID：{context.work_item.id}",
                f"- 标题：{context.work_item.title or '-'}",
                f"- 类型：{context.work_item.work_item_type or '-'}",
                f"- 状态：{context.work_item.state or '-'}",
                f"- 版块：{context.work_item.board_column or '-'}",
                f"- 指派：{context.work_item.assigned_to or '-'}",
                f"- 标签：{fields.get('System.Tags') or '-'}",
                "描述：",
                _clean_text(fields.get("System.Description") or "") or "-",
            ]
        )
    )

    if context.notes:
        prompt_parts.append(
            "\n".join(
                [f"最近上下文（来源：{context.notes_source}）:"] + [f"- {x}" for x in context.notes]
            )
        )

    if context.image_paths:
        prompt_parts.append(
            "\n".join(
                ["本地截图/附件："] + [f"- {x}" for x in context.image_paths]
            )
        )

    prompt_parts.append(
        "\n".join(
            [
                "输出要求：",
                "- 先给出结论。",
                "- 再列出根因或判断依据。",
                "- 如果需要改代码，说明会改哪些文件。",
                "- 如果信息不足，明确指出缺什么。",
            ]
        )
    )
    return "\n\n".join(x for x in prompt_parts if x.strip()).strip()


def build_mcp_prompt(*, settings: UiSettings, project: ProjectEntry, work_item_id: int, mode: str) -> str:
    workspace_root = tool_workspace_root()
    workspace_repo = matched_workspace_repo(settings)
    mode_label = "分析" if mode == "analyze" else "修复"

    lines: list[str] = [
        f"请通过已接入的 ADO MCP {mode_label} 工单 #{work_item_id}。",
        "",
        "执行顺序：",
        f"1. 调用 `ado_get_work_item` 读取工单 #{work_item_id} 详情。",
        f"2. 调用 `ado_get_work_item_comments` 读取工单 #{work_item_id} 的评论或 updates。",
        f"3. 调用 `ado_evaluate_change_policy` 评估这条工单是否允许 AI 继续改代码。",
        "4. 基于工单内容、评论、图片和策略结论给出结论。",
    ]

    if mode == "fix":
        lines.append("5. 如果策略不允许直接修改，只输出分析和建议，不要改代码。")
        lines.append("6. 如果策略允许，再根据仓库规则决定是否继续修改。")
    else:
        lines.append("5. 输出需求总结、疑点、影响范围和建议修改点。")

    lines.extend(
        [
            "",
            "仓库规则：",
            f"- 当前运行目录：{workspace_root}",
        ]
    )
    if workspace_repo is not None:
        lines.append(f"- 当前运行目录命中已配置仓库：{workspace_repo.name} ({workspace_repo.path})")
        lines.append("- 可以直接基于当前运行目录继续。")
    else:
        lines.append("- 当前运行目录未命中任何已配置仓库。")
        if settings.local_repos:
            lines.append("- 已配置本地仓库：")
            for repo in settings.local_repos:
                lines.append(f"  {repo.name}: {repo.path}")
        lines.append("- 在用户确认仓库前，不要直接改代码。")

    lines.extend(
        [
            "",
            "输出要求：",
            "- 先给结论。",
            "- 再给依据。",
            "- 如果需要改代码，先说明会改哪些文件。",
            "- 不要编造未确认的信息。",
        ]
    )
    return "\n".join(lines).strip()


def open_ai_in_terminal(command: str, *, repo_path: str) -> None:
    shell = f"cd {shlex.quote(str(Path(repo_path).expanduser().resolve()))} && {command}"
    script = f'tell application "Terminal" to do script {json.dumps(shell, ensure_ascii=False)}'
    subprocess.run(["/usr/bin/osascript", "-e", 'tell application "Terminal" to activate', "-e", script], check=True)


def _clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<br\\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > 1800:
        return text[:1800].rstrip() + "..."
    return text


def _notes_from_comments(comments: list[WorkItemComment]) -> list[str]:
    out: list[str] = []
    for item in comments[-8:]:
        body = _clean_text(item.text)
        if not body:
            continue
        author = item.created_by or "-"
        when = item.created_date or "-"
        out.append(f"{when} {author}: {body}")
    return out[-8:]


def _notes_from_updates(updates: list[WorkItemUpdate]) -> list[str]:
    out: list[str] = []
    for item in updates[-8:]:
        changed_fields = list((item.fields or {}).keys())[:6]
        summary = "、".join(changed_fields) if changed_fields else "字段变更"
        who = item.revised_by or "-"
        when = item.revised_date or "-"
        out.append(f"{when} {who}: {summary}")
    return out[-8:]


def media_cache_dir() -> Path:
    return Path.home() / ".config" / "my-own-script" / "work_item_media" / "current"


def _prepare_local_images(*, item: WorkItem, pat: str) -> list[str]:
    cache_dir = media_cache_dir()
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    image_links = _collect_image_links(item)
    local_paths: list[str] = []
    for idx, url in enumerate(image_links, start=1):
        try:
            hint = _filename_hint(url, idx)
            dest = cache_dir / hint
            saved = download_authenticated_file(url, pat=pat, dest_path=dest)
            local_paths.append(str(saved))
        except Exception:
            continue
    return local_paths


def _collect_image_links(item: WorkItem) -> list[str]:
    found: list[str] = []
    desc = str((item.fields or {}).get("System.Description") or "")
    for match in re.finditer(r'<img[^>]+src=["\\\']([^"\\\']+)["\\\']', desc, flags=re.IGNORECASE):
        url = str(match.group(1) or "").strip()
        if url.startswith("http://") or url.startswith("https://"):
            found.append(url)

    for rel in item.relations or []:
        rel_name = str(rel.get("rel") or "")
        url = str(rel.get("url") or "").strip()
        attributes = dict(rel.get("attributes") or {})
        name = str(attributes.get("name") or "")
        if rel_name.lower() == "attachedfile" and url and _looks_like_image(name or url):
            found.append(url)

    out: list[str] = []
    seen: set[str] = set()
    for url in found:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _looks_like_image(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"))


def _filename_hint(url: str, idx: int) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name or f"image_{idx}"
    if "." not in name:
        name = f"{name}_{idx}"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return safe or f"image_{idx}"
