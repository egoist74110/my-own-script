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
    branch: str | None = None


@dataclass(frozen=True)
class BuildRun:
    definition_id: str
    build_id: str
    status: str
    result: str | None
    url: str | None = None
    branch: str | None = None


# ADO pipeline RunState enum: inProgress | canceling | completed | unknown.
# Only inProgress is actively running. NB: "canceling" is a run on its way out
# (it will finish as completed/result=canceled) — treating it as "running" makes
# the deploy attach to a dying run and then abort with result=canceled.
_PIPELINE_RUNNING_STATES = {"inprogress"}
# ADO build status enum: none | inProgress | completed | cancelling | postponed | notStarted.
_BUILD_RUNNING_STATES = {"inprogress", "notstarted", "postponed"}


def is_pipeline_running(state: str | None) -> bool:
    return (state or "").strip().lower() in _PIPELINE_RUNNING_STATES


def is_build_running(status: str | None) -> bool:
    return (status or "").strip().lower() in _BUILD_RUNNING_STATES


def _refname_to_branch(refname: str | None) -> str | None:
    if not refname:
        return None
    s = str(refname)
    return s[len("refs/heads/"):] if s.startswith("refs/heads/") else s


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
    refname = (((data.get("resources") or {}).get("repositories") or {}).get("self") or {}).get("refName")
    return PipelineRun(
        pipeline_id=str(pipeline_id),
        run_id=str(run_id),
        state=str(state),
        result=str(result) if result is not None else None,
        url=str(href) if href else None,
        branch=_refname_to_branch(refname),
    )


# distributedtask/queues is a preview API. ADO Server builds accept different
# preview minors (older on-prem servers reject newer ones with 400). Try a few,
# newest→oldest, and use whichever the server accepts.
_QUEUE_API_VERSIONS = ("7.1-preview.1", "6.0-preview.1", "5.1-preview.1", "5.0-preview.1")


def list_agent_queues(
    base_url: str,
    collection: str,
    project: str,
    *,
    pat: str,
    api_version: str | None = None,
) -> list[tuple[str, str]]:
    """List project agent queues (代理程式集区). Returns [(id, name), ...].

    api_version=None → auto-probe the candidate preview versions and use the
    first the server accepts (400/404 means "wrong version", try the next).
    """
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/distributedtask/queues"
    versions = (api_version,) if api_version else _QUEUE_API_VERSIONS

    last_err: Exception | None = None
    data: Any = None
    with _client(pat) as c:
        for ver in versions:
            # actionFilter=Use → queues the identity may *use* to queue builds
            # (needs only build/use perm, not agent-pool Manage).
            r = c.get(url, params={"api-version": ver, "actionFilter": "Use"})
            if r.status_code in (400, 404):
                last_err = httpx.HTTPStatusError(
                    f"api-version {ver} rejected ({r.status_code})", request=r.request, response=r
                )
                continue
            r.raise_for_status()
            data = r.json()
            break

    if data is None:
        raise last_err or RuntimeError("no compatible distributedtask/queues api-version")

    out: list[tuple[str, str]] = []
    for q in data.get("value") or []:
        qid = q.get("id")
        name = q.get("name") or ""
        if qid is not None and name:
            out.append((str(qid), str(name)))
    return out


def trigger_build_definition(
    base_url: str,
    collection: str,
    project: str,
    definition_id: str,
    *,
    branch: str,
    pat: str,
    queue_id: str | int | None = None,
    api_version: str = "7.0",
) -> BuildRun:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/build/builds"
    body: dict[str, Any] = {
        "definition": {"id": int(definition_id)},
        "sourceBranch": f"refs/heads/{branch}",
    }
    if queue_id:
        # Override the agent pool/queue for this run (Default when unset).
        body["queue"] = {"id": int(queue_id)}
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


def find_matching_run(
    base_url: str,
    collection: str,
    project: str,
    kind: BuildKind,
    definition_id: str,
    *,
    branch: str,
    pat: str,
) -> PipelineRun | BuildRun | None:
    """Find an *actively running* run matching this definition and branch.

    Returns the newest in-progress run on ``branch``, or ``None`` if nothing is
    running. Used to avoid redundant triggers when ADO auto-trigger is active —
    completed/canceled/canceling runs are deliberately ignored (a canceling run
    is on its way out, not a live conflict).
    """
    if kind == "pipeline":
        # The runs list carries state but not branch; only resolve branch (via a
        # per-run detail call) for runs that are actually running — cheap because
        # in practice at most one or two runs are in-progress at a time.
        for r in list_pipeline_runs(base_url, collection, project, definition_id, pat=pat):
            if not is_pipeline_running(r.state):
                continue
            run = r
            if run.branch is None:
                try:
                    run = get_pipeline_run(base_url, collection, project, definition_id, r.run_id, pat=pat)
                except Exception:
                    run = r
                if not is_pipeline_running(run.state):
                    continue
            if run.branch is not None and run.branch != branch:
                continue
            return run
    else:
        # list_build_runs already filters by branch server-side.
        for b in list_build_runs(base_url, collection, project, definition_id, branch=branch, pat=pat, top=5):
            if is_build_running(b.status):
                return b
    return None


def list_pipeline_runs(
    base_url: str,
    collection: str,
    project: str,
    pipeline_id: str,
    *,
    pat: str,
    api_version: str = "7.0",
    top: int = 5,
) -> list[PipelineRun]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/pipelines/{pipeline_id}/runs"
    with _client(pat) as c:
        r = c.get(url, params={"api-version": api_version, "$top": top})
        r.raise_for_status()
        data: Any = r.json()

    out: list[PipelineRun] = []
    for x in data.get("value") or []:
        rid = x.get("id")
        state = x.get("state") or ""
        result = x.get("result")
        web = (x.get("_links") or {}).get("web") or {}
        href = web.get("href")
        out.append(
            PipelineRun(
                pipeline_id=str(pipeline_id),
                run_id=str(rid),
                state=str(state),
                result=str(result) if result is not None else None,
                url=str(href) if href else None,
            )
        )
    return out


def list_build_runs(
    base_url: str,
    collection: str,
    project: str,
    definition_id: str,
    *,
    branch: str,
    pat: str,
    api_version: str = "7.0",
    top: int = 5,
) -> list[BuildRun]:
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/build/builds"
    params = {
        "api-version": api_version,
        "definitions": str(definition_id),
        "branchName": f"refs/heads/{branch}",
        "$top": top,
        "queryOrder": "queueTimeDescending",
    }
    with _client(pat) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        data: Any = r.json()

    out: list[BuildRun] = []
    for b0 in data.get("value") or []:
        bid = b0.get("id")
        status = b0.get("status") or ""
        result = b0.get("result")
        href = b0.get("_links", {}).get("web", {}).get("href")
        out.append(
            BuildRun(
                definition_id=str(definition_id),
                build_id=str(bid),
                status=str(status),
                result=str(result) if result is not None else None,
                url=str(href) if href else None,
            )
        )
    return out


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


def cancel_pipeline_run(
    base_url: str,
    collection: str,
    project: str,
    pipeline_id: str,
    run_id: str,
    *,
    pat: str,
    api_version: str = "7.0",
) -> None:
    """Best-effort cancel a pipeline run.

    Azure DevOps Server versions differ. Some don't implement the
    /pipelines/{id}/runs/{runId}/cancel endpoint and return 404.

    Fallback: treat run_id as build_id and cancel via Build API.
    """
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/pipelines/{pipeline_id}/runs/{run_id}/cancel"
    with _client(pat) as c:
        try:
            r = c.post(url, params={"api-version": api_version})
            r.raise_for_status()
            return
        except httpx.HTTPStatusError as e:
            # If endpoint not supported, fallback to build cancel.
            if e.response is not None and e.response.status_code == 404:
                cancel_build(base_url, collection, project, run_id, pat=pat, api_version=api_version)
                return
            raise


def cancel_build(
    base_url: str,
    collection: str,
    project: str,
    build_id: str,
    *,
    pat: str,
    api_version: str = "7.0",
) -> None:
    """Best-effort cancel a classic build."""
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/build/builds/{build_id}"
    body = {"status": "cancelling"}
    with _client(pat) as c:
        r = c.patch(url, params={"api-version": api_version}, json=body)
        r.raise_for_status()


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
