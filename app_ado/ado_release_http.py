from __future__ import annotations

"""ADO classic Release endpoints (trigger + monitor).

Azure DevOps Server often needs `api-version=6.0` for release APIs.
We keep api-version configurable and callers can retry with 6.0.

This module tries to be "transparent": errors bubble up to UI which will show
modal dialogs.
"""

import base64
import time
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


@dataclass(frozen=True)
class ReleaseRun:
    id: str
    name: str | None
    url: str | None


@dataclass(frozen=True)
class ReleaseEnv:
    id: str
    name: str
    status: str
    definition_environment_id: str | None = None


def _auth_header(pat: str) -> str:
    token = base64.b64encode(f":{pat}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


def _client(pat: str, *, timeout_sec: float = 15.0) -> httpx.Client:
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
    api_version: str = "6.0",
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


def get_release_definition(
    base_url: str,
    collection: str,
    project: str,
    release_def_id: str,
    *,
    pat: str,
    api_version: str = "6.0",
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/release/definitions/{release_def_id}"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version})
        r.raise_for_status()
        return r.json()


def get_release_stages(
    base_url: str,
    collection: str,
    project: str,
    release_def_id: str,
    *,
    pat: str,
    api_version: str = "6.0",
) -> list[ReleaseStage]:
    data = get_release_definition(base_url, collection, project, release_def_id, pat=pat, api_version=api_version)
    envs = data.get("environments") or []
    out: list[ReleaseStage] = []
    for e in envs:
        eid = e.get("id")
        name = e.get("name")
        if eid is not None and name:
            out.append(ReleaseStage(id=str(eid), name=str(name)))
    return out


def create_release_from_build(
    base_url: str,
    collection: str,
    project: str,
    release_def_id: str,
    *,
    build_id: str,
    pat: str,
    api_version: str = "6.0",
    description: str | None = None,
) -> ReleaseRun:
    """Create a release using the release definition's artifact template.

    We fetch the release definition to reuse its artifact "definitionReference" and alias.
    Then we fill instanceReference with the given build_id.

    NOTE: Different ADO Server setups may require additional fields. If this fails,
    the UI will show the response details and we will tune the payload.
    """
    definition = get_release_definition(base_url, collection, project, release_def_id, pat=pat, api_version=api_version)
    artifacts = definition.get("artifacts") or []
    if not artifacts:
        raise RuntimeError("Release definition has no artifacts; cannot create release")

    # Use the first artifact template by default
    a0 = artifacts[0]
    alias = a0.get("alias")
    definition_ref = a0.get("definitionReference") or {}
    artifact_type = a0.get("type")

    body: dict[str, Any] = {
        "definitionId": int(release_def_id),
        "description": description or f"Triggered by my-own-script (build {build_id})",
        "artifacts": [
            {
                "alias": alias,
                "type": artifact_type,
                "definitionReference": definition_ref,
                "instanceReference": {
                    "id": str(build_id),
                    "name": str(build_id),
                },
            }
        ],
    }

    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/release/releases"
    with _client(pat) as c:
        r = c.post(url, params={"api-version": api_version}, json=body)
        r.raise_for_status()
        data: Any = r.json()

    rid = data.get("id")
    name = data.get("name")
    web = (data.get("_links") or {}).get("web") or {}
    href = web.get("href")
    return ReleaseRun(id=str(rid), name=str(name) if name else None, url=str(href) if href else None)


def get_release(
    base_url: str,
    collection: str,
    project: str,
    release_id: str,
    *,
    pat: str,
    api_version: str = "6.0",
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/release/releases/{release_id}"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version})
        r.raise_for_status()
        return r.json()


def extract_envs(release_json: dict[str, Any]) -> list[ReleaseEnv]:
    out: list[ReleaseEnv] = []
    envs = release_json.get("environments") or []
    for e in envs:
        eid = e.get("id")
        name = e.get("name")
        status = e.get("status")
        def_eid = e.get("definitionEnvironmentId")
        if eid is None or not name:
            continue
        out.append(
            ReleaseEnv(
                id=str(eid),
                name=str(name),
                status=str(status or ""),
                definition_environment_id=str(def_eid) if def_eid is not None else None,
            )
        )
    return out


def start_release_environment(
    base_url: str,
    collection: str,
    project: str,
    release_id: str,
    env_id: str,
    *,
    pat: str,
) -> dict[str, Any]:
    """Start deployment of a release environment.

    On some ADO Server setups, environments won't auto-start and require an explicit
    transition to InProgress.

    We use api-version=6.0-preview.6 as it supports status transition.
    """
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/release/releases/{release_id}/environments/{env_id}"
    with _client(pat) as c:
        r = c.patch(
            url,
            params={"api-version": "6.0-preview.6"},
            json={"status": "inProgress", "comment": "Triggered by my-own-script"},
        )
        # Some servers may return 400 with a status-transition message even though it proceeds;
        # let callers decide based on subsequent GET.
        if r.status_code >= 400:
            raise httpx.HTTPStatusError(r.text, request=r.request, response=r)
        return r.json()
