from __future__ import annotations

import json
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from runner_app.config import AppSpec, TasksConfig, get_app_spec
from runner_app.models import Job, JobStatus
from runner_app.notifiers import get_notifier
from runner_app.providers import get_provider
from runner_app.storage import Storage


REF_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")


def _job_prefix(provider: str) -> str:
    p = provider.lower()
    if p == "github":
        return "gh"
    if p == "azure":
        return "az"
    return "job"


def _json_print(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def _make_log_path(job_id: str) -> Path:
    from runner_app.config import data_dir

    logs_dir = data_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    safe = job_id.replace(":", "_")
    return logs_dir / f"{safe}.log"


def _append_log(path: Path, line: str) -> None:
    ts = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {line}\n")


def require_token(provider: str) -> None:
    # Token priority:
    # 1) env
    # 2) keyring
    # else: error
    import os

    import keyring

    from runner_app.config import APP_ID

    p = provider.lower()
    if p == "github":
        if os.getenv("GITHUB_TOKEN"):
            return
        if keyring.get_password(APP_ID, "github_token") or keyring.get_password("runner", "github_token"):
            return
        raise RuntimeError("Missing GitHub token. Set GITHUB_TOKEN or run: my-own-script setup")

    if p == "azure":
        if os.getenv("AZURE_DEVOPS_TOKEN"):
            return
        if keyring.get_password(APP_ID, "azure_token") or keyring.get_password("runner", "azure_token"):
            return
        raise RuntimeError("Missing Azure DevOps token. Set AZURE_DEVOPS_TOKEN or run: my-own-script setup")


def publish(
    *,
    tasks: TasksConfig,
    app: str,
    env: Optional[str],
    ref: Optional[str],
    storage: Storage,
    poll_seconds: float = 0.8,
    max_polls: int = 5,
) -> tuple[Job, Job]:
    spec: AppSpec = get_app_spec(tasks, app)

    if env is None:
        env = spec.env_default
    if ref is None:
        ref = spec.ref_default

    if not env:
        raise ValueError("env is required (no env_default set)")
    if not ref:
        raise ValueError("ref is required (no ref_default set)")

    if spec.allowed_envs and env not in spec.allowed_envs:
        raise ValueError(f"env '{env}' not allowed. allowed_envs={spec.allowed_envs}")

    if not REF_RE.match(ref):
        raise ValueError("ref must match regex: ^[A-Za-z0-9._/\\-]+$")

    require_token(spec.provider)

    provider = get_provider(spec.provider)
    provider_run_id = provider.trigger_publish(spec, env, ref)
    run_url = provider.get_run_url(spec, provider_run_id)

    job_id = f"{_job_prefix(spec.provider)}:{uuid.uuid4()}"
    log_path = _make_log_path(job_id)
    _append_log(log_path, f"trigger publish app={app} env={env} ref={ref} provider_run_id={provider_run_id}")

    job = storage.create_job(
        job_id=job_id,
        app=app,
        action="publish",
        env=env,
        ref=ref,
        status=JobStatus.queued,
        provider=spec.provider,
        provider_run_id=provider_run_id,
        run_url=run_url,
        log_path=str(log_path),
    )

    _json_print(
        {
            "job_id": job.job_id,
            "app": job.app,
            "action": job.action,
            "env": job.env,
            "ref": job.ref,
            "status": job.status.value,
        }
    )

    # simulate progression
    job = storage.update_status(job_id, JobStatus.running)
    _append_log(log_path, "status -> running")

    # stub polling
    for i in range(max_polls):
        time.sleep(poll_seconds)
        _append_log(log_path, f"poll {i + 1}/{max_polls}")

    final_status = JobStatus.success
    job_final = storage.update_status(job_id, final_status)
    _append_log(log_path, f"status -> {final_status.value}")

    notifier = get_notifier("openclaw")
    notifier.send(
        title=f"my-own-script publish {app} {env} {ref}",
        content=f"job_id={job_id} status={final_status.value}",
        level="info" if final_status == JobStatus.success else "error",
        meta={"job_id": job_id, "run_url": run_url},
    )

    _json_print({"job_id": job_id, "status": final_status.value, "run_url": run_url})
    return job, job_final


def build(
    *,
    tasks: TasksConfig,
    app: str,
    ref: Optional[str],
    storage: Storage,
    poll_seconds: float = 0.8,
    max_polls: int = 4,
) -> tuple[Job, Job]:
    spec: AppSpec = get_app_spec(tasks, app)
    if ref is None:
        ref = spec.ref_default
    if not ref:
        raise ValueError("ref is required (no ref_default set)")
    if not REF_RE.match(ref):
        raise ValueError("ref must match regex: ^[A-Za-z0-9._/\\-]+$")

    require_token(spec.provider)

    provider = get_provider(spec.provider)
    provider_run_id = provider.trigger_build(spec, ref)
    run_url = provider.get_run_url(spec, provider_run_id)

    job_id = f"{_job_prefix(spec.provider)}:{uuid.uuid4()}"
    log_path = _make_log_path(job_id)
    _append_log(log_path, f"trigger build app={app} ref={ref} provider_run_id={provider_run_id}")

    job = storage.create_job(
        job_id=job_id,
        app=app,
        action="build",
        env=None,
        ref=ref,
        status=JobStatus.queued,
        provider=spec.provider,
        provider_run_id=provider_run_id,
        run_url=run_url,
        log_path=str(log_path),
    )

    _json_print(
        {
            "job_id": job.job_id,
            "app": job.app,
            "action": job.action,
            "env": job.env,
            "ref": job.ref,
            "status": job.status.value,
        }
    )

    job = storage.update_status(job_id, JobStatus.running)
    _append_log(log_path, "status -> running")

    for i in range(max_polls):
        time.sleep(poll_seconds)
        _append_log(log_path, f"poll {i + 1}/{max_polls}")

    final_status = JobStatus.success
    job_final = storage.update_status(job_id, final_status)
    _append_log(log_path, f"status -> {final_status.value}")

    notifier = get_notifier("openclaw")
    notifier.send(
        title=f"my-own-script build {app} {ref}",
        content=f"job_id={job_id} status={final_status.value}",
        level="info" if final_status == JobStatus.success else "error",
        meta={"job_id": job_id, "run_url": run_url},
    )

    _json_print({"job_id": job_id, "status": final_status.value, "run_url": run_url})
    return job, job_final
