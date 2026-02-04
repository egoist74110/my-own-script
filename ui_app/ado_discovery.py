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


def _headers(pat: str) -> dict[str, str]:
    return {"Authorization": _auth_header_from_pat(pat), "Accept": "application/json"}


def list_pipelines(base_url: str, collection: str, pat: str, api_version: str = "7.0") -> list[BuildTarget]:
    url = f"{base_url.rstrip('/')}/{collection}/_apis/pipelines"
    with httpx.Client(timeout=10.0, headers=_headers(pat)) as c:
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


def list_build_definitions(base_url: str, collection: str, pat: str, api_version: str = "7.0") -> list[BuildTarget]:
    url = f"{base_url.rstrip('/')}/{collection}/_apis/build/definitions"
    with httpx.Client(timeout=10.0, headers=_headers(pat)) as c:
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


def discover_build_targets(base_url: str, collection: str, pat: str) -> list[BuildTarget]:
    # Try pipelines first; fall back to build definitions
    try:
        targets = list_pipelines(base_url, collection, pat)
        if targets:
            return targets
    except httpx.HTTPError:
        pass

    return list_build_definitions(base_url, collection, pat)
