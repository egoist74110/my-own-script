from __future__ import annotations

import keyring

from app_ado.store import APP_ID


def pat_key(library_id: str) -> str:
    return f"azuredevops_pat:{library_id}"


def get_pat(library_id: str) -> str | None:
    return keyring.get_password(APP_ID, pat_key(library_id))


def set_pat(library_id: str, pat: str) -> None:
    keyring.set_password(APP_ID, pat_key(library_id), pat)
