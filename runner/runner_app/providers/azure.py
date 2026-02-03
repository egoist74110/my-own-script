from __future__ import annotations

import uuid

from runner_app.config import AppSpec
from runner_app.models import JobStatus
from runner_app.providers.base import Provider


class AzureProvider(Provider):
    def trigger_publish(self, app_config: AppSpec, env: str, ref: str) -> str:
        return f"run_{uuid.uuid4().hex[:12]}"

    def trigger_build(self, app_config: AppSpec, ref: str) -> str:
        return f"run_{uuid.uuid4().hex[:12]}"

    def get_status(self, app_config: AppSpec, provider_run_id: str) -> JobStatus:
        return JobStatus.running

    def get_run_url(self, app_config: AppSpec, provider_run_id: str) -> str:
        org = app_config.org or "unknown_org"
        project = app_config.project or "unknown_project"
        pipeline_id = app_config.pipeline_id or 0
        return (
            f"https://dev.azure.com/{org}/{project}/_build/results?buildId={provider_run_id}"
            f"&view=results&pipelineId={pipeline_id}"
        )
