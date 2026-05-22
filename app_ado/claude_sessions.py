"""扫描本地 Claude Code 会话记录，供 TG 端「选项目 / 续聊已有会话」用。

Claude Code 把每个会话的完整记录写成 JSONL：
    ~/.claude/projects/<encoded-cwd>/<session-id>.jsonl
其中 <encoded-cwd> 是把工作目录绝对路径里所有「非字母数字」字符换成 '-'
（实证：/Users/wesker/my-own-script → -Users-wesker-my-own-script；
        /Users/wesker/CG_Vue_Event  → -Users-wesker-CG-Vue-Event，下划线也变 '-'）。
文件名去掉 .jsonl 就是可用于 `claude --resume <id>` 的 session id。

只读盘、不依赖任何 SDK。编码是有损的（无法从目录名反推原路径），所以：
  - 列「最近项目」时，真实 cwd 从 jsonl 内的 "cwd" 字段读回；
  - 给定 cwd 找目录时，先按编码猜，猜不中就扫所有目录、读 jsonl 里的真实 cwd 匹配。
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def projects_root() -> Path:
    return Path.home() / ".claude" / "projects"


def encode_cwd(cwd: str) -> str:
    """把工作目录绝对路径编码成 Claude Code 的 projects 子目录名。"""
    ab = os.path.abspath(os.path.expanduser(cwd or "."))
    return re.sub(r"[^a-zA-Z0-9]", "-", ab)


def _read_cwd_from_jsonl(path: Path, *, max_lines: int = 40) -> str:
    """从 jsonl 头部找出真实工作目录（记录里的 "cwd" 字段）。"""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines:
                    break
                line = line.strip()
                if not line or '"cwd"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                cwd = o.get("cwd")
                if isinstance(cwd, str) and cwd.startswith("/"):
                    return cwd
    except Exception:
        pass
    return ""


def _find_project_dir(cwd: str) -> Path:
    """给定工作目录，定位它的 projects 子目录。先按编码猜，再兜底扫描匹配。"""
    ab = os.path.abspath(os.path.expanduser(cwd or "."))
    guess = projects_root() / encode_cwd(ab)
    if guess.is_dir():
        return guess
    root = projects_root()
    if root.is_dir():
        for sub in root.iterdir():
            if not sub.is_dir():
                continue
            jsonls = list(sub.glob("*.jsonl"))
            if not jsonls:
                continue
            real = _read_cwd_from_jsonl(max(jsonls, key=lambda p: p.stat().st_mtime))
            if real and os.path.abspath(real) == ab:
                return sub
    return guess  # 可能不存在


def project_dir(cwd: str) -> Path:
    return _find_project_dir(cwd)


@dataclass
class SessionMeta:
    session_id: str         # = 文件名去掉 .jsonl，可直接 --resume
    title: str              # 首条用户消息文本（截断）
    mtime: float            # 最近修改时间（last activity）
    path: str
    cwd: str

    @property
    def when(self) -> str:
        return time.strftime("%m-%d %H:%M", time.localtime(self.mtime))


@dataclass
class ProjectMeta:
    path: str               # 真实工作目录绝对路径
    name: str               # 展示名（路径 basename）
    mtime: float            # 该目录下最近一次会话活动时间
    session_count: int = 0

    @property
    def when(self) -> str:
        return time.strftime("%m-%d %H:%M", time.localtime(self.mtime))


def _extract_title(path: Path, *, max_lines: int = 80, max_len: int = 48) -> str:
    """从 jsonl 头部找第一条「有正文的用户消息」当标题。"""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("type") != "user":
                    continue
                msg = o.get("message") or {}
                content = msg.get("content")
                text = ""
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "text":
                            text = b.get("text") or ""
                            break
                text = (text or "").strip()
                # 跳过命令/元消息/TUI 残渣
                if not text or text[0] in "<>/│┌└├─╭╰":
                    continue
                text = text.replace("\n", " ")
                return text if len(text) <= max_len else text[: max_len - 1] + "…"
    except Exception:
        pass
    return "(无标题)"


def list_sessions(cwd: str, *, limit: int = 12, query: str = "") -> list[SessionMeta]:
    """列出某 cwd 下的会话，按最近修改时间倒序；query 非空时按标题子串过滤。"""
    d = _find_project_dir(cwd)
    if not d.is_dir():
        return []
    files = [p for p in d.glob("*.jsonl") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    q = (query or "").strip().lower()
    out: list[SessionMeta] = []
    for p in files:
        title = _extract_title(p)
        if q and q not in title.lower():
            continue
        out.append(SessionMeta(
            session_id=p.stem,
            title=title,
            mtime=p.stat().st_mtime,
            path=str(p),
            cwd=cwd,
        ))
        if len(out) >= limit:
            break
    return out


def get_session(cwd: str, session_id: str) -> Optional[SessionMeta]:
    p = _find_project_dir(cwd) / f"{session_id}.jsonl"
    if not p.is_file():
        return None
    return SessionMeta(
        session_id=session_id,
        title=_extract_title(p),
        mtime=p.stat().st_mtime,
        path=str(p),
        cwd=cwd,
    )


def list_recent_projects(*, limit: int = 15) -> list[ProjectMeta]:
    """扫 ~/.claude/projects/ 下所有有会话记录的目录，读回真实 cwd，按最近活动倒序。"""
    root = projects_root()
    if not root.is_dir():
        return []
    out: list[ProjectMeta] = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        jsonls = [p for p in d.glob("*.jsonl") if p.is_file()]
        if not jsonls:
            continue
        latest = max(jsonls, key=lambda p: p.stat().st_mtime)
        cwd = _read_cwd_from_jsonl(latest)
        if not cwd:
            continue
        # 跳过已不存在的目录 + 临时目录（测试残渣 / 系统 tmp）
        if not os.path.isdir(cwd):
            continue
        if cwd.startswith(("/private/var/folders", "/var/folders", "/tmp")):
            continue
        out.append(ProjectMeta(
            path=os.path.abspath(cwd),
            name=os.path.basename(cwd.rstrip("/")) or cwd,
            mtime=latest.stat().st_mtime,
            session_count=len(jsonls),
        ))
    out.sort(key=lambda m: m.mtime, reverse=True)
    return out[:limit]


if __name__ == "__main__":
    import sys
    cwd = sys.argv[1] if len(sys.argv) > 1 else "/Users/wesker/my-own-script"
    print(f"cwd={cwd}  encoded={encode_cwd(cwd)}")
    print(f"dir={_find_project_dir(cwd)} exists={_find_project_dir(cwd).is_dir()}")
    print("-- sessions --")
    for m in list_sessions(cwd, limit=15):
        print(f"  {m.when}  {m.session_id[:8]}  {m.title}")
    print("-- recent projects --")
    for p in list_recent_projects(limit=15):
        print(f"  {p.when}  ({p.session_count:>2}) {p.name}  [{p.path}]")
