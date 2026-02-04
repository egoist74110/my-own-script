from __future__ import annotations

import time

from ui_app.task_base import Task


class SyncMergeBuildReleaseTask(Task):
    name = "SyncMergeBuildRelease"

    def __init__(self, *, config_summary: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.summary = config_summary

    def run(self) -> None:
        # Stub executor: we only demonstrate log channels + phases.
        self.log("info", f"config: {self.summary}")
        phases = [
            ("sync", 0.6),
            ("merge", 0.6),
            ("build", 1.0),
            ("release", 1.0),
        ]
        for name, sec in phases:
            self.log("info", f"phase start: {name}")
            self.script_log("info", f"[script] would run step '{name}'")
            time.sleep(sec)
            self.script_log("info", f"[script] step '{name}' ok")
            self.log("info", f"phase ok: {name}")
