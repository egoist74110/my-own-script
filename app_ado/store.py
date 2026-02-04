from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_ado.models import TaskSettings, UiSettings

APP_ID = "my-own-script"


def config_dir() -> Path:
    return Path.home() / ".config" / APP_ID


def _load_text(p: Path) -> str:
    return p.read_text("utf-8")


def _dump_yaml_like(obj: Any) -> str:
    """Prefer YAML if available; fall back to JSON.

    We keep this small to avoid hard-depending on PyYAML in early bootstrap.
    """
    try:
        import yaml  # type: ignore

        return yaml.safe_dump(obj, sort_keys=False, allow_unicode=True)
    except Exception:
        return json.dumps(obj, ensure_ascii=False, indent=2)


def _load_yaml_like(text: str) -> Any:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except Exception:
        return json.loads(text)


def ui_settings_path() -> Path:
    return config_dir() / "ui_settings.yaml"


def tasks_path() -> Path:
    return config_dir() / "tasks.yaml"


def load_ui_settings() -> UiSettings:
    p = ui_settings_path()
    if not p.exists():
        return UiSettings()
    raw = _load_yaml_like(_load_text(p)) or {}
    return UiSettings.model_validate(raw)


def save_ui_settings(s: UiSettings) -> Path:
    cd = config_dir()
    cd.mkdir(parents=True, exist_ok=True)
    p = ui_settings_path()
    p.write_text(_dump_yaml_like(s.model_dump()), "utf-8")
    return p


def load_task_settings() -> TaskSettings:
    p = tasks_path()
    if not p.exists():
        return TaskSettings()
    raw = _load_yaml_like(_load_text(p)) or {}
    return TaskSettings.model_validate(raw)


def save_task_settings(s: TaskSettings) -> Path:
    cd = config_dir()
    cd.mkdir(parents=True, exist_ok=True)
    p = tasks_path()
    p.write_text(_dump_yaml_like(s.model_dump()), "utf-8")
    return p
