from __future__ import annotations

from runner_app.config import AppSpec, TasksConfig, get_app_spec


class Registry:
    def __init__(self, tasks: TasksConfig):
        self.tasks = tasks

    def app(self, app: str) -> AppSpec:
        return get_app_spec(self.tasks, app)
