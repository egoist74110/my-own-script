from __future__ import annotations

import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app_ado.models import AiCliProfile

ASK_HIGH_MODEL_SCRIPT = Path("/Users/wesker/.gemini/bin/ask-high-model.sh")
ASK_FLASH_READ_SCRIPT = Path("/Users/wesker/.gemini/bin/ask-flash-read.sh")


@dataclass
class CollaborationRunResult:
    ok: bool
    title: str
    summary: str
    details: str


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _find_profile(profiles: list[AiCliProfile], profile_id: str) -> AiCliProfile | None:
    return next((x for x in profiles if x.id == profile_id), None)


def _ensure_script_exists(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"脚本不存在：{path}")


def _run_command(parts: list[str], *, cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(parts, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


def _format_completed_process(title: str, cp: subprocess.CompletedProcess[str]) -> CollaborationRunResult:
    ok = cp.returncode == 0
    summary = "执行成功" if ok else f"执行失败（退出码 {cp.returncode}）"
    details = (
        f"命令:\n{' '.join(shlex.quote(x) for x in cp.args)}\n\n"
        f"退出码: {cp.returncode}\n\n"
        f"stdout:\n{cp.stdout[:12000] or '(空)'}\n\n"
        f"stderr:\n{cp.stderr[:12000] or '(空)'}"
    )
    return CollaborationRunResult(ok=ok, title=title, summary=summary, details=details)


def map_upgrade_profile_to_model(profile_id: str) -> str | None:
    mapping = {
        "claude_code": "claude",
        "codex": "codex",
        "gemini": "gemini-pro",
    }
    return mapping.get(profile_id)


def run_high_model_upgrade_test(profiles: list[AiCliProfile], profile_id: str, cwd: Path) -> CollaborationRunResult:
    _ensure_script_exists(ASK_HIGH_MODEL_SCRIPT)
    profile = _find_profile(profiles, profile_id)
    if profile is None:
        return CollaborationRunResult(False, "低级模型协作测试", "执行前检查失败", f"找不到 AI 工具：{profile_id}")

    model = map_upgrade_profile_to_model(profile_id)
    if not model:
        return CollaborationRunResult(
            False,
            "低级模型协作测试",
            "当前配置暂不支持直接测试",
            f"当前求助对象是“{profile.name}”，但本地脚本目前只支持内置映射：Claude Code / Codex / Gemini CLI。",
        )

    prompt = (
        "这是一次低级模型协作测试。\n\n"
        "任务目标：验证“卡住后向高级模型求助”的本地流程是否可用。\n"
        "work_done：已经连续两次遇到同类失败，无法决定下一步。\n"
        "current_state：当前处于测试模式，不需要修改任何项目文件。\n"
        "problem：请直接回答这条升级链是否已成功触达你，并给出一句简短建议。\n"
        "context_summary：这是桌面应用中的模型协作测试入口。\n"
        "need_from_high_model：返回一句确认文本，说明你已收到压缩摘要。\n"
    )

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as fh:
        fh.write(prompt)
        prompt_file = fh.name

    try:
        cp = _run_command(
            [
                "bash",
                str(ASK_HIGH_MODEL_SCRIPT),
                "--model",
                model,
                "--prompt-file",
                prompt_file,
                "--cwd",
                str(cwd),
                "--timeout",
                "90",
            ],
            cwd=cwd,
            timeout=120,
        )
        return _format_completed_process("低级模型协作测试", cp)
    finally:
        try:
            Path(prompt_file).unlink(missing_ok=True)
        except Exception:
            pass


def run_high_model_collection_test(profiles: list[AiCliProfile], profile_id: str, max_words: int, cwd: Path) -> CollaborationRunResult:
    _ensure_script_exists(ASK_FLASH_READ_SCRIPT)
    profile = _find_profile(profiles, profile_id)
    if profile is None:
        return CollaborationRunResult(False, "高级模型协作测试", "执行前检查失败", f"找不到 AI 工具：{profile_id}")

    command_text = (profile.command or "").strip().lower()
    if "gemini" not in command_text:
        return CollaborationRunResult(
            False,
            "高级模型协作测试",
            "当前配置暂不支持直接测试",
            f"当前上下文收集工具是“{profile.name}”，但 `ask-flash-read.sh` 当前依赖 Gemini CLI，建议先选择 Gemini CLI profile。",
        )

    request = (
        f"引用 {cwd / 'app_ado/models.py'} 中 AiSettings 和 ModelCollaborationSettings 的原文；"
        f"列出 {cwd / 'app_ado/ui/ai_config_tab.py'} 里与“模型协作”直接相关的方法名；"
        "不要总结、不要建议，只做收集。"
    )
    cp = _run_command(
        [
            "bash",
            str(ASK_FLASH_READ_SCRIPT),
            "--request",
            request,
            "--cwd",
            str(cwd),
            "--max-words",
            str(max_words),
            "--timeout",
            "90",
        ],
        cwd=cwd,
        timeout=120,
    )
    return _format_completed_process("高级模型协作测试", cp)
