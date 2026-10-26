"""Bounded, private attachment cache. Cross-instance eviction is serialized with flock."""

import fcntl
import hashlib
import os
import re
import stat
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from toolbox_backend.mcp.runner import secure_directory


class AttachmentCache:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)

    def store(self, library_id, wi, url, fetch, *, max_bytes, total_bytes, force=False):
        root = secure_directory(self.data_dir, "mcp", "ado-attachments")
        fd = os.open(root / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            parsed = urlsplit(url)
            filename = parse_qs(parsed.query).get("fileName", ["attachment.bin"])[0]
            filename = (
                re.sub(r"[^\w.-]", "_", unquote(filename))[:100].strip(".") or "attachment.bin"
            )
            aid = hashlib.sha256(url.encode()).hexdigest()[:32]
            directory = secure_directory(
                root, hashlib.sha256(library_id.encode()).hexdigest()[:24], str(wi or "unknown")
            )
            path = directory / (aid + "_" + filename)
            if path.is_symlink():
                raise ValueError("unsafe cache file")
            self._evict(root, total_bytes)
            if path.exists() and not force:
                check = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    info = os.fstat(check)
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or info.st_uid != os.getuid()
                        or info.st_mode & 0o077
                        or info.st_size > max_bytes
                    ):
                        raise ValueError("invalid cache file")
                finally:
                    os.close(check)
                os.utime(path, None, follow_symlinks=False)
                return path, True, info.st_size
            data = fetch()
            if len(data) > min(max_bytes, total_bytes):
                raise ValueError("attachment too large")
            temporary = directory / (".tmp-" + uuid.uuid4().hex)
            out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(out, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            self._evict(root, total_bytes, keep=path)
            return path, False, len(data)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @staticmethod
    def _evict(root, total_bytes, keep=None):
        entries = []
        now = time.time()
        # Never descend through directory links.
        for parent, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(parent) / d).is_symlink()]
            for name in files:
                path = Path(parent) / name
                if name == ".lock" or path.is_symlink():
                    continue
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode):
                    continue
                if now - info.st_mtime > 14 * 86400 and path != keep:
                    path.unlink()
                else:
                    entries.append((info.st_mtime, info.st_size, path))
        total = sum(size for _, size, _ in entries)
        for _, size, path in sorted(entries):
            if total <= total_bytes:
                break
            if path != keep:
                path.unlink()
                total -= size
