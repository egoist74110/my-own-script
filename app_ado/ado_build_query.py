from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class BuildBrief:
    id: str
    result: str | None
    status: str | None
    url: str | None


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


def get_latest_successful_build(
    base_url: str,
    collection: str,
    project: str,
    definition_id: str,
    *,
    branch: str,
    pat: str,
    api_version: str = "7.0",
) -> BuildBrief:
    """Get latest succeeded build for a build definition.

    Works for both classic build definitions and YAML pipelines on most ADO Server setups,
    because pipeline runs are also represented in build records.
    """
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/build/builds"
    params = {
        "api-version": api_version,
        "definitions": str(definition_id),
        "branchName": f"refs/heads/{branch}",
        "$top": 1,
        "queryOrder": "finishTimeDescending",
        "statusFilter": "completed",
        "resultFilter": "succeeded",
    }
    with _client(pat) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        data: Any = r.json()

    items = data.get("value") or []
    if not items:
        raise RuntimeError(f"未找到成功构建：definition={definition_id} branch={branch}")

    b0 = items[0]
    bid = b0.get("id")
    href = b0.get("_links", {}).get("web", {}).get("href")
    return BuildBrief(
        id=str(bid),
        result=b0.get("result"),
        status=b0.get("status"),
        url=str(href) if href else None,
    )
