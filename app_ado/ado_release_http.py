from __future__ import annotations

"""ADO classic Release endpoints.

On Azure DevOps Server, release endpoints sometimes require api-version 6.0.
We keep api-version configurable and default to 7.0, with callers free to retry.
"""

import base64
from dataclasses import dataclass
from typing import Any

import httpx


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


def list_release_definitions(
    base_url: str,
    collection: str,
    project: str,
    *,
    pat: str,
    api_version: str = "7.0",
) -> list[ReleaseDefinition]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/release/definitions"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version})
        r.raise_for_status()
        data: Any = r.json()
    out: list[ReleaseDefinition] = []
    for x in data.get("value") or []:
        rid = x.get("id")
        name = x.get("name")
        if rid is not None and name:
            out.append(ReleaseDefinition(id=str(rid), name=str(name)))
    out.sort(key=lambda d: d.name.lower())
    return out


def get_release_stages(
    base_url: str,
    collection: str,
    project: str,
    release_def_id: str,
    *,
    pat: str,
    api_version: str = "7.0",
) -> list[ReleaseStage]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/release/definitions/{release_def_id}"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version})
        r.raise_for_status()
        data: Any = r.json()

    envs = data.get("environments") or []
    out: list[ReleaseStage] = []
    for e in envs:
        eid = e.get("id")
        name = e.get("name")
        if eid is not None and name:
            out.append(ReleaseStage(id=str(eid), name=str(name)))
    return out
