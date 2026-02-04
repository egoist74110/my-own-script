from __future__ import annotations

import keyring

from runner_app.config import APP_ID
from ui_app.azuredevops_client import AzureDevOpsClient
from ui_app.settings_store import RepoEntry


def get_pat(repo: RepoEntry) -> str | None:
    return keyring.get_password(APP_ID, f"azuredevops_pat:{repo.id}")


def normalize_base_url(url: str) -> str:
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url.rstrip("/")


def try_pick_default_collection(repo: RepoEntry) -> str | None:
    """Try to auto-pick a default collection by listing collections.

    Returns collection name or None if not available.
    """
    pat = get_pat(repo)
    if not pat or not repo.base_url:
        return None

    c = AzureDevOpsClient(base_url=repo.base_url, pat=pat, api_version="7.0")
    cols = c.list_collections()
    if not cols:
        return None
    return cols[0].name


def refresh_projects(repo: RepoEntry) -> list[str]:
    """Fetch projects for repo.default_collection and return list of names."""
    pat = get_pat(repo)
    if not pat:
        raise RuntimeError("PAT not found in keychain for this repo")
    if not repo.base_url:
        raise RuntimeError("Server URL not set")
    if not repo.default_collection:
        raise RuntimeError("default_collection not set")

    c = AzureDevOpsClient(base_url=repo.base_url, pat=pat, api_version="7.0")
    projects = c.list_projects(repo.default_collection)
    return [p.name for p in projects]
