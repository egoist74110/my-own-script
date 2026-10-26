"""Private, symlink-rejecting service logs, capped rotation and redacted tails."""

import os
import stat
from pathlib import Path

from toolbox_backend.mcp.runner import redact_mcp, secure_directory


class ServiceLog:
    def __init__(self, data_dir: Path, name: str, max_bytes=5 * 1024 * 1024):
        self.root, self.name, self.max_bytes = data_dir, name, max_bytes
        self.tail = b""

    def _path(self):
        if not self.root.exists():
            self.root.mkdir(mode=0o700, parents=True)
        directory = secure_directory(self.root, "services", "logs")
        path = directory / (self.name + ".log")
        for candidate in (path, path.with_suffix(".log.1")):
            if candidate.is_symlink():
                raise ValueError("unsafe log file")
            if candidate.exists():
                info = candidate.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                    raise ValueError("unsafe log file")
        return path

    def write(self, line):
        encoded = (redact_mcp(line).rstrip("\n") + "\n").encode(errors="replace")
        # A single oversized line must not defeat either disk or response bounds.
        encoded = encoded[: min(self.max_bytes, 65536)]
        path = self._path()
        if path.exists() and path.stat().st_size + len(encoded) > self.max_bytes:
            path.replace(path.with_suffix(".log.1"))
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "ab") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded)
        self.tail = (self.tail + encoded)[-65536:]

    def read_tail(self, limit=65536):
        path = self._path()
        if not path.exists():
            return ""
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            stream.seek(max(0, os.fstat(stream.fileno()).st_size - min(limit, 65536)))
            return (
                redact_mcp(stream.read(65536).decode(errors="replace"))
                .encode()[-limit:]
                .decode(errors="ignore")
            )
