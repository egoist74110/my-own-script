from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Optional


@dataclass(frozen=True)
class TaskLogEvent:
    ts: str
    level: str
    message: str


class Task:
    """Base class for UI tasks.

    Goals:
    - consistent log stream (for UI + file)
    - simple lifecycle (queued -> running -> done/failed)

    This is deliberately minimal; later we can add cancellation/progress.
    """

    name: str = "Task"

    def __init__(
        self,
        *,
        logger: logging.Logger,
        emit: Optional[Callable[[TaskLogEvent], None]] = None,
    ) -> None:
        self._logger = logger
        self._emit = emit
        self._status: str = "queued"
        self._started_at: Optional[float] = None
        self._ended_at: Optional[float] = None

    @property
    def status(self) -> str:
        return self._status

    def _now_iso(self) -> str:
        return datetime.now(UTC).isoformat()

    def log(self, level: str, message: str) -> None:
        level_l = level.lower().strip()
        if level_l in ("debug", "info", "warning", "error"):
            getattr(self._logger, level_l)(message)
        else:
            self._logger.info(message)
        if self._emit:
            self._emit(TaskLogEvent(ts=self._now_iso(), level=level_l, message=message))

    def run(self) -> None:
        """Override in subclasses."""
        raise NotImplementedError

    def execute(self) -> None:
        """Run with lifecycle + logging."""
        self._status = "running"
        self._started_at = time.time()
        self.log("info", f"{self.name} started")
        try:
            self.run()
            self._status = "success"
            self.log("info", f"{self.name} success")
        except Exception as e:
            self._status = "failed"
            self.log("error", f"{self.name} failed: {e}")
            raise
        finally:
            self._ended_at = time.time()
            if self._started_at is not None:
                ms = int((self._ended_at - self._started_at) * 1000)
                self.log("debug", f"{self.name} duration_ms={ms}")


class DemoSleepTask(Task):
    name = "DemoSleepTask"

    def __init__(self, seconds: float, **kwargs) -> None:
        super().__init__(**kwargs)
        self.seconds = seconds

    def run(self) -> None:
        for i in range(1, 6):
            self.log("info", f"working... step {i}/5")
            time.sleep(self.seconds / 5)
