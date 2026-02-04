from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

from ui_app.azuredevops_client import _auth_header_from_pat


Kind = Literal["pipeline", "builddef"]


@dataclass(frozen=True)
class BuildTarget:
    kind: Kind
    id: str
    name: str


@dataclass(frozen=True)
class GitRepo:
    id: str
    name: str


@dataclass(frozen=True)
class GitBranch:
    name: str  # refs/heads/x

    @property
    def short(self) -> str:
        return self.name.removeprefix("refs/heads/")


def _headers(pat: str) -> dict[str, str]:
    return {"Authorization": _auth_header_from_pat(pat), "Accept": "application/json"}


def _client(pat: str) -> httpx.Client:
    # Keep timeouts tight so UI doesn't hang
    timeout = httpx.Timeout(10.0, connect=5.0)
    return httpx.Client(timeout=timeout, headers=_headers(pat))


def list_pipelines(
    base_url: str,
    collection: str,
    pat: str,
    api_version: str = "7.0",
    *,
    project: str | None = None,
) -> list[BuildTarget]:
    if project:
        url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/pipelines"
    else:
        url = f"{base_url.rstrip('/')}/{collection}/_apis/pipelines"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version})
        r.raise_for_status()
        data: Any = r.json()
    out: list[BuildTarget] = []
    for x in data.get("value") or []:
        pid = x.get("id")
        name = x.get("name")
        if pid is not None and name:
            out.append(BuildTarget(kind="pipeline", id=str(pid), name=str(name)))
    return out


def list_build_definitions(
    base_url: str,
    collection: str,
    pat: str,
    api_version: str = "7.0",
    *,
    project: str | None = None,
) -> list[BuildTarget]:
    if project:
        url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/build/definitions"
    else:
        url = f"{base_url.rstrip('/')}/{collection}/_apis/build/definitions"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version})
        r.raise_for_status()
        data: Any = r.json()
    out: list[BuildTarget] = []
    for x in data.get("value") or []:
        pid = x.get("id")
        name = x.get("name")
        if pid is not None and name:
            out.append(BuildTarget(kind="builddef", id=str(pid), name=str(name)))
    return out


def discover_build_targets(base_url: str, collection: str, pat: str, *, project: str | None = None) -> list[BuildTarget]:
    # Try pipelines first; fall back to build definitions
    try:
        targets = list_pipelines(base_url, collection, pat, project=project)
        if targets:
            return targets
    except httpx.HTTPError:
        pass

    try:
        return list_build_definitions(base_url, collection, pat, project=project)
    except httpx.HTTPError:
        return []
