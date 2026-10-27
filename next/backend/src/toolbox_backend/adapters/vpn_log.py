"""Private rotating VPN log with strict symlink and size handling."""

import os
import stat
from pathlib import Path

from toolbox_backend.logging_setup import redact_exception
from toolbox_backend.mcp.runner import secure_directory


class VpnLog:
    def __init__(self, data_dir: Path, max_bytes: int = 5 * 1024 * 1024):
        self.data_dir, self.max_bytes = Path(data_dir), max_bytes

    def write(self, line: str) -> None:
        directory = secure_directory(self.data_dir, "vpn", "logs")
        path = directory / "vpn.log"
        rotated = directory / "vpn.log.1"
        for candidate in (path, rotated):
            if candidate.is_symlink():
                raise ValueError("unsafe VPN log")
            if candidate.exists():
                info = candidate.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                    raise ValueError("unsafe VPN log")
        encoded = (redact_exception(line).replace("\n", " ")[:65535] + "\n").encode()
        if path.exists() and path.stat().st_size + len(encoded) > self.max_bytes:
            if rotated.exists():
                rotated.unlink()
            path.replace(rotated)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "ab") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded)
