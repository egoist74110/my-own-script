from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class AzureDevOpsAccount:
    account_id: str
    account_name: str  # org name


@dataclass(frozen=True)
class AzureDevOpsProject:
    id: str
    name: str


def _auth_header_from_pat(pat: str) -> str:
    # Azure DevOps PAT uses Basic auth with empty username.
    token = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


class AzureDevOpsClient:
    def __init__(self, *, pat: str, timeout_seconds: float = 10.0) -> None:
        self._pat = pat
        self._timeout = timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": _auth_header_from_pat(self._pat),
            "Accept": "application/json",
        }

    def list_accounts(self) -> list[AzureDevOpsAccount]:
        url = "https://app.vssps.visualstudio.com/_apis/accounts"
        params = {"api-version": "7.1-preview.1"}
        with httpx.Client(timeout=self._timeout, headers=self._headers()) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data: Any = r.json()

        values = data.get("value") or []
        accounts: list[AzureDevOpsAccount] = []
        for a in values:
            name = a.get("accountName")
            aid = a.get("accountId")
            if name and aid:
                accounts.append(AzureDevOpsAccount(account_id=aid, account_name=name))
        accounts.sort(key=lambda x: x.account_name.lower())
        return accounts

    def list_projects(self, org: str) -> list[AzureDevOpsProject]:
        url = f"https://dev.azure.com/{org}/_apis/projects"
        params = {"api-version": "7.1-preview.4"}
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
