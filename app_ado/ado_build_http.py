from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx


BuildKind = Literal["pipeline", "build_definition"]


@dataclass(frozen=True)
class PipelineRun:
    pipeline_id: str
    run_id: str
    state: str
    result: str | None
    url: str | None = None


@dataclass(frozen=True)
class BuildRun:
    definition_id: str
    build_id: str
    status: str
    result: str | None
    url: str | None = None


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


def trigger_pipeline_run(
    base_url: str,
    collection: str,
    project: str,
    pipeline_id: str,
    *,
    branch: str,
    pat: str,
    api_version: str = "7.0",
) -> PipelineRun:
    """Trigger a YAML pipeline run."""
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/pipelines/{pipeline_id}/runs"
    body: dict[str, Any] = {
        "resources": {
            "repositories": {
                "self": {
                    "refName": f"refs/heads/{branch}",
                }
            }
        }
    }
    with _client(pat) as c:
        r = c.post(url, params={"api-version": api_version}, json=body)
        r.raise_for_status()
        data: Any = r.json()

    rid = data.get("id")
    state = data.get("state") or ""
    result = data.get("result")
    web = (data.get("_links") or {}).get("web") or {}
    href = web.get("href")
    return PipelineRun(
        pipeline_id=str(pipeline_id),
        run_id=str(rid),
        state=str(state),
        result=str(result) if result is not None else None,
        url=str(href) if href else None,
    )


def get_pipeline_run(
    base_url: str,
    collection: str,
    project: str,
    pipeline_id: str,
    run_id: str,
    *,
    pat: str,
    api_version: str = "7.0",
) -> PipelineRun:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/pipelines/{pipeline_id}/runs/{run_id}"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version})
        r.raise_for_status()
        data: Any = r.json()

    state = data.get("state") or ""
    result = data.get("result")
    web = (data.get("_links") or {}).get("web") or {}
    href = web.get("href")
    return PipelineRun(
        pipeline_id=str(pipeline_id),
        run_id=str(run_id),
        state=str(state),
        result=str(result) if result is not None else None,
        url=str(href) if href else None,
    )


def trigger_build_definition(
    base_url: str,
    collection: str,
    project: str,
    definition_id: str,
    *,
    branch: str,
    pat: str,
    api_version: str = "7.0",
) -> BuildRun:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/build/builds"
    body: dict[str, Any] = {
        "definition": {"id": int(definition_id)},
        "sourceBranch": f"refs/heads/{branch}",
    }
    with _client(pat) as c:
        r = c.post(url, params={"api-version": api_version}, json=body)
        r.raise_for_status()
        data: Any = r.json()

    bid = data.get("id")
    status = data.get("status") or ""
    result = data.get("result")
    href = data.get("url")
    return BuildRun(
        definition_id=str(definition_id),
        build_id=str(bid),
        status=str(status),
        result=str(result) if result is not None else None,
        url=str(href) if href else None,
    )


def get_build(
    base_url: str,
    collection: str,
    project: str,
    build_id: str,
    *,
    pat: str,
    api_version: str = "7.0",
) -> BuildRun:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/build/builds/{build_id}"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version})
        r.raise_for_status()
        data: Any = r.json()

    status = data.get("status") or ""
    result = data.get("result")
    href = data.get("url")
    did = (data.get("definition") or {}).get("id")
    return BuildRun(
        definition_id=str(did) if did is not None else "",
        build_id=str(build_id),
        status=str(status),
        result=str(result) if result is not None else None,
        url=str(href) if href else None,
    )


def wait_pipeline(
    base_url: str,
    collection: str,
    project: str,
    pipeline_id: str,
    run_id: str,
    *,
    pat: str,
    timeout_min: int = 30,
    poll_sec: float = 8.0,
) -> PipelineRun:
    deadline = time.time() + timeout_min * 60
    last: PipelineRun | None = None
    while time.time() < deadline:
        cur = get_pipeline_run(base_url, collection, project, pipeline_id, run_id, pat=pat)
        last = cur
        if cur.state.lower() == "completed":
            return cur
        time.sleep(poll_sec)
    raise TimeoutError(f"pipeline run timeout after {timeout_min}min (pipeline={pipeline_id} run={run_id}) last={last}")


def wait_build(
    base_url: str,
    collection: str,
    project: str,
    build_id: str,
    *,
    pat: str,
    timeout_min: int = 30,
    poll_sec: float = 8.0,
) -> BuildRun:
    deadline = time.time() + timeout_min * 60
    last: BuildRun | None = None
    while time.time() < deadline:
        cur = get_build(base_url, collection, project, build_id, pat=pat)
        last = cur
        if cur.status.lower() == "completed":
            return cur
        time.sleep(poll_sec)
    raise TimeoutError(f"build timeout after {timeout_min}min (build={build_id}) last={last}")
