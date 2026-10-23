"""Read-only listing of Claude's own session files for one registered repository.

Only $HOME/.claude/projects/<encoded-cwd>/*.jsonl is touched: at most 50 files, at most 80 head
lines each, no symlinks, nothing outside that directory. Content never leaves this module except
a clipped title.
"""

import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path

MAX_FILES = 50
MAX_SCAN = 2000  # directory entries inspected before giving up on a huge folder
MAX_LINES = 80
MAX_LINE_BYTES = 64 * 1024
TITLE_LIMIT = 48
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")


def encode_cwd(cwd: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", cwd)


def _plain_dir(path: Path) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)  # lstat: a symlink is not a directory
    except OSError:
        return False


def _title(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return ""
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            return ""
        for _ in range(MAX_LINES):
            line = stream.readline(MAX_LINE_BYTES)
            if not line:
                break
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(obj, dict) or obj.get("type") != "user":
                continue
            message = obj.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text") or ""
                        break
            text = " ".join(str(text).split())
            if not text or text[0] in "<>/│┌└├─╭╰":
                continue
            return text if len(text) <= TITLE_LIMIT else text[: TITLE_LIMIT - 1] + "…"
    return ""


def list_sessions(repo_realpath: str, query: str = "", *, home: str | None = None):
    base = Path(home or os.path.expanduser("~"))
    root = base / ".claude" / "projects"
    target = root / encode_cwd(repo_realpath)
    for directory in (base / ".claude", root, target):
        if not _plain_dir(directory):
            return []
    real_root = root.resolve()
    if target.resolve().parent != real_root:
        return []
    found = []
    try:
        with os.scandir(target) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_SCAN:
                    break
                name = entry.name
                if not name.endswith(".jsonl") or not ID.fullmatch(name[:-6]):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISREG(info.st_mode):
                    found.append((info.st_mtime, name[:-6]))
    except OSError:
        return []
    found.sort(reverse=True)
    needle = query.strip().lower()
    items = []
    for mtime, session_id in found[:MAX_FILES]:
        title = _title(target / (session_id + ".jsonl")) or "(无标题)"
        if needle and needle not in title.lower():
            continue
        items.append(
            {
                "session_id": session_id,
                "title": title,
                "updated_at": datetime.fromtimestamp(mtime, UTC).isoformat(),
            }
        )
    return items
