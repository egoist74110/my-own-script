from runner_app.notifiers.base import Notifier
from runner_app.notifiers.openclaw import OpenClawNotifier


def get_notifier(name: str) -> Notifier:
    key = name.lower().strip()
    if key in ("openclaw", "default"):
        return OpenClawNotifier()
    raise ValueError(f"Unknown notifier: {name}")
