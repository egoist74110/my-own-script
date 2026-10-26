"""Lark MCP log rotation (5 MiB x 2, 0600), marker parsing, token status, and port probes."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import os
import re
import socket
from pathlib import Path

from toolbox_backend.adapters.config_store import stamp
from toolbox_backend.api.mcp_schemas import LarkPatchStatus, LarkTokenStatus
from toolbox_backend.mcp.runner import redact_mcp
from toolbox_backend.mcp.runtime import ensure_data_subdir

MAX_LOG_BYTES = 5 * 1024 * 1024
MAX_TAIL_BYTES = 65536
PATCH_RE = re.compile(
    r"\[toolbox-lark-patch\]\s*(auth_store|oidc|mcp_tool)=(applied|skipped|failed)"
)
KEYTAR_DISABLED_MARKER = "Builtin User Access Token Store will be disabled"


class LarkLogManager:
    """Manages <data-dir>/mcp/logs/lark-mcp.log (5 MiB x 2, 0600) and in-memory tail."""

    def __init__(self, data_dir: Path, max_bytes: int = MAX_LOG_BYTES) -> None:
        self.data_dir = data_dir
        self.max_bytes = max_bytes
        self._tail = bytearray()

    @property
    def log_path(self) -> Path:
        logs_dir = ensure_data_subdir(self.data_dir, "mcp", "logs")
        return logs_dir / "lark-mcp.log"

    @property
    def tail_text(self) -> str:
        return self._tail.decode("utf-8", errors="replace")

    def clear_tail(self) -> None:
        self._tail.clear()

    def write_line(self, raw_line: str) -> str:
        text = redact_mcp(raw_line)
        if not text.endswith("\n"):
            text += "\n"
        encoded = text.encode("utf-8", errors="replace")
        self._tail.extend(encoded)
        if len(self._tail) > MAX_TAIL_BYTES:
            del self._tail[:-MAX_TAIL_BYTES]

        path = self.log_path
        try:
            if path.exists() and path.stat().st_size + len(encoded) > self.max_bytes:
                rotated = path.with_name("lark-mcp.log.1")
                with contextlib.suppress(OSError):
                    if rotated.exists():
                        rotated.unlink()
                    path.replace(rotated)
                    rotated.chmod(0o600)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "ab") as f:
                os.fchmod(f.fileno(), 0o600)
                f.write(encoded)
                f.flush()
        except OSError:
            pass
        return text


def parse_line_markers(
    line: str,
    patches: LarkPatchStatus,
    keytar_available: bool,
) -> tuple[LarkPatchStatus, bool, bool]:
    """Return (updated_patches, updated_keytar_available, changed)."""
    changed = False
    for match in PATCH_RE.finditer(line):
        name, status = match.group(1), match.group(2)
        if getattr(patches, name) != status:
            setattr(patches, name, status)
            changed = True
    all_app = (
        patches.auth_store == "applied"
        and patches.oidc == "applied"
        and patches.mcp_tool == "applied"
    )
    if patches.all_applied != all_app:
        patches.all_applied = all_app
        changed = True
    if KEYTAR_DISABLED_MARKER in line and keytar_available:
        keytar_available = False
        changed = True
    return patches, keytar_available, changed


def infer_lark_token_status(
    data_dir: Path,
    logged_in_at: str | None,
    lark_logs_dir: Path | None = None,
) -> LarkTokenStatus:
    """Infer token status from logged_in_at and log refresh events without storage/Keychain."""
    if not logged_in_at:
        return LarkTokenStatus(state="unknown", logged_in_at=None)

    candidate_files: list[Path] = []
    managed_log = data_dir / "mcp/logs/lark-mcp.log"
    if managed_log.is_file():
        candidate_files.append(managed_log)
    if lark_logs_dir is not None and lark_logs_dir.is_dir():
        candidate_files.extend(sorted(lark_logs_dir.glob("*.log")))

    last_event: str | None = None
    for fpath in candidate_files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in content.splitlines():
            if (
                "Successfully refreshed token" in line
                or "Successfully exchanged authorization code" in line
            ):
                last_event = "ok"
            elif "Token refresh failed" in line:
                last_event = "refresh_failing"

    if last_event == "refresh_failing":
        return LarkTokenStatus(
            state="refresh_failing",
            logged_in_at=logged_in_at,
            last_event_at=stamp(),
            message="令牌刷新失败，请重新登录飞书 MCP",
        )
    return LarkTokenStatus(
        state="ok",
        logged_in_at=logged_in_at,
        last_event_at=stamp() if last_event == "ok" else logged_in_at,
    )


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.15)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                return True
    return False


async def probe_lark_http(port: int, timeout_s: float = 0.5) -> bool:
    """Send GET /mcp to 127.0.0.1:<port>; any HTTP status line counts as listening."""
    writer = None
    try:
        async with asyncio.timeout(timeout_s):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            req = (
                f"GET /mcp HTTP/1.1\r\n"
                f"Host: localhost:{port}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("ascii")
            writer.write(req)
            await writer.drain()
            line = await reader.readline()
            return line.startswith(b"HTTP/1.")
    except OSError, TimeoutError:
        return False
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError, TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), timeout=0.2)
