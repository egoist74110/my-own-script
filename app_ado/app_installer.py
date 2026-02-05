from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True)
class DownloadProgress:
    downloaded: int
    total: int | None


def default_update_cache_dir() -> Path:
    return Path.home() / "Library" / "Caches" / "代码工具箱" / "updates"


def download_file(url: str, dest: Path, *, on_progress=None, timeout: float = 30.0) -> Path:
    """Download url to dest (atomic). on_progress(DownloadProgress)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    if tmp.exists():
        tmp.unlink()

    headers = {"User-Agent": "code-toolsbox"}
    downloaded = 0
    total = None

    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as c:
        with c.stream("GET", url) as r:
            r.raise_for_status()
            total_s = r.headers.get("Content-Length")
            total = int(total_s) if total_s and total_s.isdigit() else None
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress:
                        on_progress(DownloadProgress(downloaded=downloaded, total=total))

    tmp.replace(dest)
    return dest


def _run(cmd: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def mount_dmg(dmg_path: Path) -> Path:
    """Mount DMG and return mount point."""
    mp = Path("/Volumes") / f"代码工具箱-Update-{int(time.time())}"
    mp_str = str(mp)
    mp.mkdir(parents=True, exist_ok=True)

    cp = _run([
        "/usr/bin/hdiutil",
        "attach",
        str(dmg_path),
        "-nobrowse",
        "-noverify",
        "-mountpoint",
        mp_str,
    ], timeout=120)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr or cp.stdout or "hdiutil attach failed")
    return mp


def unmount_dmg(mount_point: Path) -> None:
    cp = _run(["/usr/bin/hdiutil", "detach", str(mount_point), "-quiet"], timeout=60)
    # Best effort
    if cp.returncode != 0:
        _run(["/usr/bin/hdiutil", "detach", str(mount_point), "-force", "-quiet"], timeout=60)


def find_app_in_volume(mount_point: Path, *, app_name: str = "代码工具箱.app") -> Path:
    p = mount_point / app_name
    if p.exists():
        return p
    # fallback: search shallow
    for x in mount_point.glob("*.app"):
        return x
    raise RuntimeError(f"在 DMG 中未找到 .app：{mount_point}")


def _needs_admin(dest_app: Path) -> bool:
    # If dest exists, need write access to its parent and the dest itself.
    parent = dest_app.parent
    return not (os.access(str(parent), os.W_OK) and (not dest_app.exists() or os.access(str(dest_app), os.W_OK)))


def _osascript_admin(shell: str) -> None:
    cp = _run([
        "/usr/bin/osascript",
        "-e",
        f'do shell script {shell!r} with administrator privileges',
    ], timeout=600)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr or cp.stdout or "osascript admin failed")


def install_app_from_volume(
    src_app: Path,
    *,
    dest_app: Path = Path("/Applications") / "代码工具箱.app",
    app_display_name: str = "代码工具箱",
    relaunch: bool = True,
) -> None:
    """Quit app, replace /Applications app, and optionally relaunch."""

    # Ask app to quit (best effort)
    _run(["/usr/bin/osascript", "-e", f'tell application "{app_display_name}" to quit'], timeout=30)

    # Build a safe copy script. Use ditto for .app bundles.
    src = str(src_app)
    dst = str(dest_app)
    script_lines = [
        # wait a bit for quit
        "sleep 1",
        # remove old
        f"rm -rf {shlex_quote(dst)}",
        f"/usr/bin/ditto {shlex_quote(src)} {shlex_quote(dst)}",
    ]
    if relaunch:
        script_lines.append(f"/usr/bin/open {shlex_quote(dst)}")

    shell = "; ".join(script_lines)

    if _needs_admin(dest_app):
        _osascript_admin(shell)
    else:
        cp = _run(["/bin/bash", "-lc", shell], timeout=600)
        if cp.returncode != 0:
            raise RuntimeError(cp.stderr or cp.stdout or "install failed")


def shlex_quote(s: str) -> str:
    # minimal shlex.quote to avoid importing extra
    return "'" + s.replace("'", "'\\''") + "'"
