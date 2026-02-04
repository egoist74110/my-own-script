from __future__ import annotations

import uuid

import keyring

from runner_app.config import APP_ID
from ui_app.settings_store import LibraryEntry


def new_library_id() -> str:
    return f"lib:{uuid.uuid4()}"


def keychain_key(library_id: str) -> str:
    return f"azuredevops_pat:{library_id}"


def get_pat(library_id: str) -> str | None:
    return keyring.get_password(APP_ID, keychain_key(library_id))


def set_pat(library_id: str, pat: str) -> None:
    keyring.set_password(APP_ID, keychain_key(library_id), pat)


def move_pat(old_library_id: str, new_library_id: str) -> None:
    """Move stored PAT from old id to new id (best-effort)."""
    v = get_pat(old_library_id)
    if not v:
        return
    set_pat(new_library_id, v)
    delete_pat(old_library_id)


def delete_pat(library_id: str) -> None:
    try:
        keyring.delete_password(APP_ID, keychain_key(library_id))
    except Exception:
        pass


def normalize_base_url(url: str) -> str:
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url.rstrip("/")
