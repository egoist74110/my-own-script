from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from runner_app.config import AppSpec
from runner_app.models import JobStatus


class Provider(ABC):
    @abstractmethod
    def trigger_publish(self, app_config: AppSpec, env: str, ref: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def trigger_build(self, app_config: AppSpec, ref: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_status(self, app_config: AppSpec, provider_run_id: str) -> JobStatus:
        raise NotImplementedError

    @abstractmethod
    def get_run_url(self, app_config: AppSpec, provider_run_id: str) -> Optional[str]:
        raise NotImplementedError
