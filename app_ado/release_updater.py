from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    html_url: str
    asset_name: str | None
    asset_url: str | None


def _repo() -> tuple[str, str]:
    # Default to this repo; can override via env for forks.
    owner = os.environ.get("TOOLBOX_GH_OWNER", "egoist74110")
    repo = os.environ.get("TOOLBOX_GH_REPO", "my-own-script")
    return owner, repo


def get_latest_release() -> ReleaseInfo:
    owner, repo = _repo()
    # Note: /releases/latest ignores prereleases. We want the newest published release
    # (including prerelease) for internal distribution.
    url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=10"  # newest first
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "code-toolsbox",
    }
    with httpx.Client(timeout=10.0, headers=headers, follow_redirects=True) as c:
        r = c.get(url)
        if r.status_code == 404:
            raise RuntimeError(f"未找到仓库或无权限：{owner}/{repo}")
        r.raise_for_status()
        items = r.json() or []

    # Pick the newest non-draft release. (Allow prerelease.)
    rel = next((x for x in items if not x.get("draft")), None)
    if not rel:
        raise RuntimeError("未找到 GitHub Release（请先在 GitHub Releases 发布一个版本并上传 .dmg；注意不能是 Draft）")

    tag = (rel.get("tag_name") or "").strip()
    version = tag.lstrip("v") if tag else ""
    html_url = rel.get("html_url") or f"https://github.com/{owner}/{repo}/releases"

    asset_name = None
    asset_url = None
    for a in rel.get("assets") or []:
        name = (a.get("name") or "")
        if name.lower().endswith(".dmg"):
            asset_name = name
            asset_url = a.get("browser_download_url")
            break

    if not asset_url:
        raise RuntimeError("已找到 Release，但未发现 .dmg 资源（请在 Release Assets 上传 .dmg）")

    return ReleaseInfo(version=version or "(unknown)", html_url=html_url, asset_name=asset_name, asset_url=asset_url)


def open_url(url: str) -> None:
    # macOS
    subprocess.run(["open", url], check=False)
