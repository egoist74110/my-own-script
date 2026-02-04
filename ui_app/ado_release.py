from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ui_app.ado_discovery import _client


@dataclass(frozen=True)
class ReleaseDef:
    id: str
    name: str


@dataclass(frozen=True)
class ReleaseStage:
    id: str
    name: str


def list_release_definitions(
    base_url: str,
    collection: str,
    project: str,
    pat: str,
    api_version: str = "7.0",
) -> list[ReleaseDef]:
    # Classic Release Management endpoint
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/release/definitions"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version})
        r.raise_for_status()
        data: Any = r.json()

    out: list[ReleaseDef] = []
    for x in data.get("value") or []:
        rid = x.get("id")
        name = x.get("name")
        if rid is not None and name:
            out.append(ReleaseDef(id=str(rid), name=str(name)))
    out.sort(key=lambda d: d.name.lower())
    return out


def list_release_stages(
    base_url: str,
    collection: str,
    project: str,
    pat: str,
    definition_id: str,
    api_version: str = "7.0",
) -> list[ReleaseStage]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/release/definitions/{definition_id}"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version})
        r.raise_for_status()
        data: Any = r.json()

    out: list[ReleaseStage] = []
    for env in data.get("environments") or []:
        eid = env.get("id")
        name = env.get("name")
        if eid is not None and name:
            out.append(ReleaseStage(id=str(eid), name=str(name)))
    # keep order as defined in pipeline (usually meaningful)
    return out
