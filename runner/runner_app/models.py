from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    success = "success"
    failed = "failed"
    canceled = "canceled"


@dataclass(frozen=True)
class Job:
    job_id: str
    app: str
    action: str  # publish|build
    env: Optional[str]
    ref: Optional[str]
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    provider: str
    provider_run_id: str
    run_url: Optional[str]
    log_path: Optional[str]

    def to_public_json(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "app": self.app,
            "action": self.action,
            "env": self.env,
            "ref": self.ref,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "provider": self.provider,
            "provider_run_id": self.provider_run_id,
            "run_url": self.run_url,
            "log_path": self.log_path,
        }
