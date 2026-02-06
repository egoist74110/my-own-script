from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_ado.models import TaskSettings, UiSettings
from app_ado.task_migrate import migrate_task_settings

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


def migrate_acl_task_ids(s: UiSettings, ts: TaskSettings) -> tuple[UiSettings, bool]:
    """Map legacy ACL task_ids (flow ids) to dynamic task UUIDs."""
    legacy_to_uuid: dict[str, str] = {}
    for t in (getattr(ts, "tasks", None) or []):
        legacy = str(getattr(t, "legacy_flow_id", "") or "").strip()
        if legacy:
            legacy_to_uuid[legacy] = str(t.id)

    changed = False
    new_groups: list[dict] = []
    for g in (s.telegram_acl_groups or []):
        tids = list(g.get("task_ids") or [])
        mapped: list[str] = []
        for tid in tids:
            tid_s = str(tid)
            if tid_s in legacy_to_uuid:
                mapped.append(legacy_to_uuid[tid_s])
                changed = True
            else:
                mapped.append(tid_s)
        gg = dict(g)
        gg["task_ids"] = mapped
        new_groups.append(gg)

    if changed:
        s.telegram_acl_groups = new_groups
    return s, changed


def load_ui_settings() -> UiSettings:
    p = ui_settings_path()
    if not p.exists():
        return UiSettings()
    raw = _load_yaml_like(_load_text(p)) or {}
    s = UiSettings.model_validate(raw)

    # Migrate ACL task_ids: legacy flow ids -> dynamic task UUIDs
    try:
        ts = load_task_settings()
        s2, changed = migrate_acl_task_ids(s, ts)
        if changed:
            save_ui_settings(s2)
        return s2
    except Exception:
        return s


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

    s, changed = migrate_task_settings(raw)
    if changed:
        # Persist migration so subsequent runs are stable.
        save_task_settings(s)
    return s


def save_task_settings(s: TaskSettings) -> Path:
    cd = config_dir()
    cd.mkdir(parents=True, exist_ok=True)
    p = tasks_path()
    p.write_text(_dump_yaml_like(s.model_dump()), "utf-8")
    return p
