"""Shared protocol helpers: bounded line framing, noise limiting and text clipping."""

import re
import time
from collections import deque
from dataclasses import dataclass

MAX_LINE = 4 * 1024 * 1024
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$")


@dataclass(frozen=True)
class Norm:
    """One normalized fact. kind is an ai_events.kind or a control word for the session."""

    kind: str
    payload: dict


def clip(value, limit: int) -> str:
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def safe_id(value) -> str | None:
    """External ids become argv elements: refuse anything that could look like an option."""
    return value if isinstance(value, str) and ID_PATTERN.fullmatch(value) else None


def tool_summary(tool: str, data) -> str:
    """One-line human summary of a tool call (port of the old bridge's _tool_summary)."""
    data = data if isinstance(data, dict) else {}
    if tool in ("Bash", "shell"):
        return clip(data.get("command"), 200)
    if tool in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        return clip(data.get("file_path") or data.get("notebook_path"), 200)
    if tool == "Glob":
        return clip(data.get("pattern"), 120)
    if tool == "Grep":
        return clip(data.get("pattern") or data.get("query"), 120)
    if tool == "TodoWrite":
        todos = data.get("todos")
        return f"{len(todos) if isinstance(todos, list) else 0} 项待办"
    if tool in ("WebFetch", "WebSearch"):
        return clip(data.get("url") or data.get("query"), 160)
    if tool == "Task":
        return clip(data.get("description"), 160)
    for key in ("command", "description", "prompt", "path", "url", "query"):
        if data.get(key):
            return clip(data[key], 160)
    return ""


class LineSplitter:
    """Split a byte stream into lines without ever buffering more than limit bytes.

    An overlong line is discarded until its newline and reported once as an int (its size).
    """

    def __init__(self, limit: int = MAX_LINE):
        self.limit = limit
        self.buffer = bytearray()
        self.skipping = 0  # bytes discarded for the current overlong line; 0 = not skipping

    def feed(self, chunk: bytes):
        results = []
        while chunk:
            newline = chunk.find(b"\n")
            piece = chunk if newline < 0 else chunk[:newline]
            if self.skipping:
                self.skipping += len(piece)
            else:
                self.buffer.extend(piece)
                if len(self.buffer) > self.limit:
                    self.skipping = len(self.buffer)
                    self.buffer.clear()
            if newline < 0:
                break
            if self.skipping:
                results.append(self.skipping)
                self.skipping = 0
            else:
                results.append(bytes(self.buffer))
                self.buffer.clear()
            chunk = chunk[newline + 1 :]
        return results

    def flush(self):
        """Final unterminated line at EOF."""
        if self.skipping:
            size, self.skipping = self.skipping, 0
            return [size]
        if self.buffer:
            data = bytes(self.buffer)
            self.buffer.clear()
            return [data]
        return []


class Noise:
    """At most `rate` noisy events per one-second window; the excess is counted and merged."""

    def __init__(self, rate: int = 20, clock=time.monotonic):
        self.rate, self.clock = rate, clock
        self.window = None
        self.used = 0
        self.suppressed = 0

    def allow(self):
        """Returns (allowed, merged): merged is the suppressed count of the previous window."""
        now = self.clock()
        merged = 0
        if self.window is None or now - self.window >= 1:
            merged, self.suppressed = self.suppressed, 0
            self.window, self.used = now, 0
        if self.used < self.rate:
            self.used += 1
            return True, merged
        self.suppressed += 1
        return False, merged

    def drain(self) -> int:
        merged, self.suppressed = self.suppressed, 0
        return merged


class Ring:
    """Most recent bytes only (stderr diagnostics)."""

    def __init__(self, limit: int = 64 * 1024):
        self.limit = limit
        self.parts = deque()
        self.size = 0

    def add(self, data: bytes):
        self.parts.append(data)
        self.size += len(data)
        while self.size > self.limit and self.parts:
            self.size -= len(self.parts.popleft())

    def text(self) -> str:
        return b"".join(self.parts)[-self.limit :].decode(errors="replace")
