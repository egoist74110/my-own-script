from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class HttpxResult:
    status: int
    headers: dict[str, str]
    body: str


def _auth_header(pat: str) -> str:
    token = base64.b64encode(f":{pat}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


def get_projects(base_url: str, collection: str, *, pat: str, api_version: str = "7.0", timeout_sec: float = 10.0) -> HttpxResult:
    url = f"{base_url.rstrip('/')}/{collection}/_apis/projects"
    headers = {"Authorization": _auth_header(pat), "Accept": "application/json"}
    timeout = httpx.Timeout(timeout_sec, connect=5.0)
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=False) as c:
        r = c.get(url, params={"api-version": api_version})
        body = r.text or ""
        return HttpxResult(status=r.status_code, headers={k.lower(): v for k, v in r.headers.items()}, body=body)
