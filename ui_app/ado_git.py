from __future__ import annotations

from typing import Any

import httpx

from ui_app.ado_discovery import GitBranch, GitRepo, _client


def list_repos(base_url: str, collection: str, project: str, pat: str, api_version: str = "7.0") -> list[GitRepo]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/git/repositories"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version})
        r.raise_for_status()
        data: Any = r.json()

    repos: list[GitRepo] = []
    for x in data.get("value") or []:
        rid = x.get("id")
        name = x.get("name")
        if rid and name:
            repos.append(GitRepo(id=str(rid), name=str(name)))
    repos.sort(key=lambda x: x.name.lower())
    return repos


def list_branches(
    base_url: str,
    collection: str,
    project: str,
    repo_id: str,
    pat: str,
    api_version: str = "7.0",
) -> list[GitBranch]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/git/repositories/{repo_id}/refs"
    params = {"api-version": api_version, "filter": "heads/"}
    with _client(pat) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        data: Any = r.json()

    branches: list[GitBranch] = []
    for x in data.get("value") or []:
        name = x.get("name")
        if name and str(name).startswith("refs/heads/"):
            branches.append(GitBranch(name=str(name)))
    branches.sort(key=lambda b: b.short.lower())
    return branches
