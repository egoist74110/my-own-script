from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class PullRequestInfo:
    id: int
    url: str


def _headers(pat: str) -> dict:
    import base64

    token = base64.b64encode((":" + pat).encode("utf-8")).decode("utf-8")
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def create_pull_request(
    base_url: str,
    collection: str,
    project: str,
    repo_id: str,
    *,
    source_branch: str,
    target_branch: str,
    pat: str,
    title: str,
) -> PullRequestInfo:
    """Create a PR from source -> target.

    Note: requires Code permission to create PR.
    """
    url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/git/repositories/{repo_id}/pullrequests?api-version=7.0"
    body = {
        "sourceRefName": f"refs/heads/{source_branch}",
        "targetRefName": f"refs/heads/{target_branch}",
        "title": title,
    }
    with httpx.Client(timeout=20.0, follow_redirects=False) as c:
        r = c.post(url, headers=_headers(pat), json=body)
        r.raise_for_status()
        j = r.json()
    prid = int(j.get("pullRequestId"))
    pr_url = j.get("url") or url
    return PullRequestInfo(id=prid, url=pr_url)


def complete_pull_request(
    base_url: str,
    collection: str,
    project: str,
    repo_id: str,
    *,
    pr_id: int,
    pat: str,
    merge_message: str,
) -> None:
    """Complete PR (merge).

    Uses PATCH with status=completed. Requires permissions.
    """
    pr_url = f"{base_url.rstrip('/')}/{collection}/{project}/_apis/git/repositories/{repo_id}/pullrequests/{pr_id}?api-version=7.0"

    # Need last source commit id. Get PR.
    with httpx.Client(timeout=20.0, follow_redirects=False) as c:
        r0 = c.get(pr_url, headers=_headers(pat))
        r0.raise_for_status()
        pr = r0.json()

        last = pr.get("lastMergeSourceCommit") or {}
        last_id = last.get("commitId")
        if not last_id:
            raise RuntimeError("PR missing lastMergeSourceCommit.commitId")

        body = {
            "status": "completed",
            "completionOptions": {
                "mergeCommitMessage": merge_message,
                "deleteSourceBranch": False,
                "squashMerge": False,
                "transitionWorkItems": False,
            },
            "lastMergeSourceCommit": {"commitId": last_id},
        }

        r = c.patch(pr_url, headers=_headers(pat), json=body)
        r.raise_for_status()


def merge_via_pr(
    base_url: str,
    collection: str,
    project: str,
    repo_id: str,
    *,
    source_branch: str,
    target_branch: str,
    pat: str,
    title: str | None = None,
    message: str | None = None,
) -> PullRequestInfo:
    title = title or f"auto-merge: {source_branch} -> {target_branch}"
    message = message or f"auto-merge: {source_branch} -> {target_branch}"

    pr = create_pull_request(
        base_url,
        collection,
        project,
        repo_id,
        source_branch=source_branch,
        target_branch=target_branch,
        pat=pat,
        title=title,
    )

    # small delay to allow PR compute
    time.sleep(0.5)
    complete_pull_request(
        base_url,
        collection,
        project,
        repo_id,
        pr_id=pr.id,
        pat=pat,
        merge_message=message,
    )

    return pr
