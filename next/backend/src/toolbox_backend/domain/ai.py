"""AI configuration normalization; pure, offline and lossless for legacy values."""

import copy
import re
import shlex
import unicodedata
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, JsonValue

BUILTINS = {
    "codex": ("Codex", "codex", "npm install -g @openai/codex@latest", "codex"),
    "gemini": ("Antigravity CLI", "agy", "agy update", "agy"),
    "claude_code": ("Claude Code", "claude", "claude update", "claude"),
}
RETAINED = {
    "targets",
    "default_target_id",
    "default_policy",
    "project_overrides",
    "require_policy_check_before_code_change",
    "allow_direct_code_change",
}


def profile_argv(command: str) -> list[str]:
    if not isinstance(command, str) or not 1 <= len(command) <= 512:
        raise ValueError("invalid command")
    argv = shlex.split(command)
    if not argv or any(unicodedata.category(c).startswith("C") for c in argv[0]):
        raise ValueError("invalid executable")
    return argv


def validate_model(value: str | None) -> str | None:
    if value is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/() +\-]{0,79}", value):
        raise ValueError("invalid model")
    return value


class Extensible(BaseModel):
    model_config = ConfigDict(extra="allow")


class AIProfile(Extensible):
    # Legacy malformed entries remain JSON values. Runtime and mutation validation are strict.
    id: JsonValue = ""
    name: JsonValue = ""
    command: JsonValue = ""
    upgrade_command: JsonValue = ""
    builtin: bool = False
    cli: JsonValue = "other"


def validate_profile(profile: AIProfile) -> None:
    if (
        not isinstance(profile.id, str)
        or not re.fullmatch(r"[A-Za-z0-9:_.\-]{1,128}", profile.id)
        or not isinstance(profile.name, str)
        or not 1 <= len(profile.name) <= 64
        or profile.cli not in ("claude", "codex", "agy", "other")
        or not isinstance(profile.upgrade_command, str)
        or len(profile.upgrade_command) > 512
    ):
        raise ValueError("invalid profile")
    profile_argv(profile.command)
    if profile.upgrade_command:
        profile_argv(profile.upgrade_command)


def _legacy_permission(value):
    # The real CLI has no "default" mode (protocol check 2026-10-23); legacy values mean manual.
    return "manual" if value == "default" else value


ClaudePermission = Annotated[
    Literal["acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan"],
    BeforeValidator(_legacy_permission),
]
CLAUDE_PERMISSIONS = ("acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan")
CODEX_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
AGY_EFFORTS = ("low", "medium", "high", "xhigh", "max")
AgyMode = Literal["sandbox", "plan", "auto"]


class ClaudeDefaults(Extensible):
    permission: ClaudePermission = "auto"
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    model: str | None = None


class CodexDefaults(Extensible):
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
    effort: Literal[*CODEX_EFFORTS] = "medium"
    model: str | None = None


class AgyDefaults(Extensible):
    mode: AgyMode = "sandbox"
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    model: str | None = None


class AIDefaults(Extensible):
    claude: ClaudeDefaults = Field(default_factory=ClaudeDefaults)
    codex: CodexDefaults = Field(default_factory=CodexDefaults)
    agy: AgyDefaults = Field(default_factory=AgyDefaults)


class ClaudeAnalysis(Extensible):
    permission: ClaudePermission = "plan"


class CodexAnalysis(Extensible):
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "read-only"


class AgyAnalysis(Extensible):
    mode: AgyMode = "plan"


class AIAnalysis(Extensible):
    claude: ClaudeAnalysis = Field(default_factory=ClaudeAnalysis)
    codex: CodexAnalysis = Field(default_factory=CodexAnalysis)
    agy: AgyAnalysis = Field(default_factory=AgyAnalysis)


class ModelPresets(Extensible):
    claude: list[str] = Field(default_factory=list)
    codex: list[str] = Field(default_factory=list)
    agy: list[str] = Field(default_factory=list)


PREFIX_PATTERN = r"[A-Za-z0-9_.:\-]{1,64}"


class McpToolPrefix(Extensible):
    """Registered MCP tool-name prefixes for the work-item analysis prompt (S5-B increment).

    Claude always uses mcp__ado-work-items__; Codex/agy default to the old registrations.
    """

    codex: Annotated[str, Field(pattern=f"^{PREFIX_PATTERN}$")] = "mcp__adoWorkItems__"
    agy: Annotated[str, Field(pattern=f"^{PREFIX_PATTERN}$")] = "mcp__ado-work-items__"


class AIBot(Extensible):
    enabled: bool = False
    enabled_at: str | None = None
    bot_id: str | None = None
    username: str | None = None


class AIBots(Extensible):
    claude_code: AIBot = Field(default_factory=AIBot)
    codex: AIBot = Field(default_factory=AIBot)
    gemini: AIBot = Field(default_factory=AIBot)


def builtin_profiles() -> list[AIProfile]:
    return [
        AIProfile(id=k, name=v[0], command=v[1], upgrade_command=v[2], builtin=True, cli=v[3])
        for k, v in BUILTINS.items()
    ]


class AIConfig(Extensible):
    profiles: list[AIProfile | JsonValue] = Field(default_factory=builtin_profiles)
    selected_profile_id: str = "codex"
    model_presets: ModelPresets = Field(default_factory=ModelPresets)
    defaults: AIDefaults = Field(default_factory=AIDefaults)
    analysis: AIAnalysis = Field(default_factory=AIAnalysis)
    mcp_tool_prefix: McpToolPrefix = Field(default_factory=McpToolPrefix)
    bots: AIBots = Field(default_factory=AIBots)


def normalize_ai(raw: dict) -> tuple[AIConfig, dict]:
    raw = copy.deepcopy(raw)
    remaining = {k: v for k, v in raw.items() if k in RETAINED}
    migrated = {k: v for k, v in raw.items() if k not in RETAINED}
    tool = migrated.pop("tool", {})
    if isinstance(tool, dict):
        for key, value in tool.items():
            migrated.setdefault(key, value)
    else:
        migrated["legacy_tool"] = tool
    profiles = migrated.get("profiles", [])
    if not isinstance(profiles, list):
        migrated["legacy_profiles"] = profiles
        profiles = []
    profiles = copy.deepcopy(profiles)
    for item in profiles:
        if isinstance(item, dict):
            pid = item.get("id")
            if isinstance(pid, str) and pid in BUILTINS:
                item["builtin"] = True
                item.setdefault("cli", BUILTINS[pid][3])
            else:
                item.setdefault("cli", "other")
    for profile in builtin_profiles():
        if not any(isinstance(p, dict) and p.get("id") == profile.id for p in profiles):
            profiles.append(profile.model_dump())
    migrated["profiles"] = profiles
    bots = migrated.get("bots", {})
    if isinstance(bots, list):
        migrated["legacy_bots"] = bots
        bots = {
            b["ai_id"]: {k: v for k, v in b.items() if k != "ai_id"}
            for b in bots
            if isinstance(b, dict) and isinstance(b.get("ai_id"), str)
        }
    if not isinstance(bots, dict):
        migrated["legacy_bots"] = bots
        bots = {}
    for bid in set(BUILTINS) | set(bots):
        bot = bots.get(bid, {})
        if not isinstance(bot, dict):
            bot = {"legacy_value": bot}
        bot.update(enabled=False, enabled_at=None, bot_id=None)
        bots[bid] = bot
    migrated["bots"] = bots
    return AIConfig.model_validate(migrated), remaining


def config_v2_to_v3(raw: dict) -> dict:
    result = copy.deepcopy(raw)
    ai, remaining = normalize_ai(result.get("imported", {}).get("ai", {}))
    result["ai"] = ai.model_dump(mode="json")
    result.setdefault("imported", {})["ai"] = remaining
    result["schema_version"] = 3
    return result


def profile_warnings(config: AIConfig) -> list[str]:
    warnings, seen = [], set()
    for profile in config.profiles:
        try:
            if not isinstance(profile, AIProfile):
                raise ValueError
            validate_profile(profile)
            if profile.id in seen:
                raise ValueError
            seen.add(profile.id)
        except ValueError, TypeError:
            warnings.append("旧 AI 配置无效或标识重复，不可运行")
    return warnings
