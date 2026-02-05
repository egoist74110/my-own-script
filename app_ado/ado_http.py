from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx


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


@dataclass(frozen=True)
class BuildPipeline:
    id: str
    name: str
    kind: str  # pipeline | build_definition


@dataclass(frozen=True)
class ReleaseDefinition:
    id: str
    name: str


@dataclass(frozen=True)
class ReleaseStage:
    id: str
    name: str


def _auth_header(pat: str) -> str:
    token = base64.b64encode(f":{pat}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


def _client(pat: str, *, timeout_sec: float = 10.0) -> httpx.Client:
    timeout = httpx.Timeout(timeout_sec, connect=5.0)
    return httpx.Client(
        timeout=timeout,
        headers={"Authorization": _auth_header(pat), "Accept": "application/json"},
        follow_redirects=False,
    )


def list_repos(base_url: str, collection: str, project: str, *, pat: str, api_version: str = "7.0") -> list[GitRepo]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/git/repositories"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version})
        r.raise_for_status()
        data: Any = r.json()
    out: list[GitRepo] = []
    for x in data.get("value") or []:
        rid = x.get("id")
        name = x.get("name")
        if rid and name:
            out.append(GitRepo(id=str(rid), name=str(name)))
    out.sort(key=lambda r: r.name.lower())
    return out


def list_branches(
    base_url: str,
    collection: str,
    project: str,
    repo_id: str,
    *,
    pat: str,
    api_version: str = "7.0",
) -> list[GitBranch]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/git/repositories/{repo_id}/refs"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version, "filter": "heads/"})
        r.raise_for_status()
        data: Any = r.json()
    out: list[GitBranch] = []
    for x in data.get("value") or []:
        name = x.get("name")
        if name and str(name).startswith("refs/heads/"):
            out.append(GitBranch(name=str(name)))
    out.sort(key=lambda b: b.short.lower())
    return out


def list_build_pipelines(
    base_url: str,
    collection: str,
    project: str,
    *,
    pat: str,
    api_version: str = "7.0",
) -> list[BuildPipeline]:
    """List build pipelines.

    Prefer the modern pipelines endpoint. Some servers may not support it; callers can
    handle exceptions and use build definitions fallback if needed.
    """
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/pipelines"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version})
        r.raise_for_status()
        data: Any = r.json()

    out: list[BuildPipeline] = []
    for x in data.get("value") or []:
        pid = x.get("id")
        name = x.get("name")
        if pid is not None and name:
            out.append(BuildPipeline(id=str(pid), name=str(name), kind="pipeline"))
    out.sort(key=lambda p: p.name.lower())
    return out


def list_build_definitions(
    base_url: str,
    collection: str,
    project: str,
    *,
    pat: str,
    api_version: str = "7.0",
) -> list[BuildPipeline]:
    """Fallback: list classic build definitions."""
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/build/definitions"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version})
        r.raise_for_status()
        data: Any = r.json()

    out: list[BuildPipeline] = []
    for x in data.get("value") or []:
        bid = x.get("id")
        name = x.get("name")
        if bid is not None and name:
            out.append(BuildPipeline(id=str(bid), name=str(name), kind="build_definition"))
    out.sort(key=lambda p: p.name.lower())
    return out
