from __future__ import annotations

import uuid

from runner_app.config import AppSpec
from runner_app.models import JobStatus
from runner_app.providers.base import Provider


class GitHubProvider(Provider):
    def trigger_publish(self, app_config: AppSpec, env: str, ref: str) -> str:
        # stub: return a fake run id
        return f"run_{uuid.uuid4().hex[:12]}"

    def trigger_build(self, app_config: AppSpec, ref: str) -> str:
        return f"run_{uuid.uuid4().hex[:12]}"

    def get_status(self, app_config: AppSpec, provider_run_id: str) -> JobStatus:
        # stub: runner orchestrator simulates transitions; provider status is not authoritative yet
        return JobStatus.running

    def get_run_url(self, app_config: AppSpec, provider_run_id: str) -> str:
        repo = app_config.repo or "unknown/unknown"
        return f"https://github.com/{repo}/actions/runs/{provider_run_id}"
