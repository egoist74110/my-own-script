from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class Notifier(ABC):
    @abstractmethod
    def send(
        self,
        title: str,
        content: str,
        level: str = "info",
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        raise NotImplementedError
