from __future__ import annotations

import json
from typing import Any, Optional

from runner_app.notifiers.base import Notifier


class OpenClawNotifier(Notifier):
    def send(
        self,
        title: str,
        content: str,
        level: str = "info",
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        payload = {"title": title, "content": content, "level": level, "meta": meta or {}}
        # stub: later replace with subprocess.run(["openclaw", "notify", ...])
        print("[openclaw] would notify telegram: " + json.dumps(payload, ensure_ascii=False))
