from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class AzureDevOpsCollection:
    id: str
    name: str


@dataclass(frozen=True)
class AzureDevOpsProject:
    id: str
    name: str


def _auth_header_from_pat(pat: str) -> str:
    # Azure DevOps PAT uses Basic auth with empty username.
    token = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


class AzureDevOpsClient:
    """Client for Azure DevOps Server (custom base URL).

    This repo targets private ADO Server environments where api-version may be limited (e.g. 7.0).
    """

    def __init__(
        self,
        *,
        base_url: str,
        pat: str,
        collection: str | None = None,
        api_version: str = "7.0",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = _normalize_base_url(base_url)
        self._pat = pat
        self._collection = collection
        self._api_version = api_version
        self._timeout = timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": _auth_header_from_pat(self._pat),
            "Accept": "application/json",
        }

    def list_collections(self) -> list[AzureDevOpsCollection]:
        # For Azure DevOps Server, collections can be listed via _apis/projectCollections
        url = f"{self._base_url}/_apis/projectCollections"
        params = {"api-version": self._api_version}
        with httpx.Client(timeout=self._timeout, headers=self._headers()) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data: Any = r.json()

        values = data.get("value") or []
        cols: list[AzureDevOpsCollection] = []
        for c in values:
            cid = c.get("id")
            name = c.get("name")
            if cid and name:
                cols.append(AzureDevOpsCollection(id=cid, name=name))
        cols.sort(key=lambda x: x.name.lower())
        return cols

    def list_projects(self, collection: str | None = None) -> list[AzureDevOpsProject]:
        coll = collection or self._collection
        if not coll:
            raise ValueError("collection is required")

        url = f"{self._base_url}/{coll}/_apis/projects"
        params = {"api-version": self._api_version}
        with httpx.Client(timeout=self._timeout, headers=self._headers()) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data: Any = r.json()

        values = data.get("value") or []
        projects: list[AzureDevOpsProject] = []
        for p in values:
            pid = p.get("id")
            name = p.get("name")
            if pid and name:
                projects.append(AzureDevOpsProject(id=pid, name=name))
        projects.sort(key=lambda x: x.name.lower())
        return projects
