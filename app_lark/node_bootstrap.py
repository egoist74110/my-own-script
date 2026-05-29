"""下载 / 管理本地内置 Node.js 运行时（专供 Lark MCP wrapper 调 ``npx`` 用）。

为什么要这个：Lark 官方的 MCP server 是个 npm 包 (``@larksuiteoapi/lark-mcp``)，
必须有 Node.js。让最终用户自己 ``brew install node`` 不现实，所以方案 B：
首次启动 Lark MCP 时把官方便携版 Node 解压到 ``~/.config/my-own-script/node/``，
后续直接复用。不污染系统、不需要 sudo、不带任何全局副作用。

对外只暴露三个函数：
- :func:`find_npx` —— 按 "用户工程下的 venv / 系统 PATH / bootstrap 目录" 顺序找 ``npx`` 可执行；
- :func:`is_bootstrapped` —— 是否已经在本地缓存里准备好了一份 Node；
- :func:`bootstrap_node` —— 下载 + 解压 + 写 ``.installed`` 标记，带进度回调。
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import tarfile
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

from app_ado.store import config_dir


# 想升级 Node 就只改这一行；下次启动会拉新版本。
NODE_VERSION = "v20.18.1"

_DOWNLOAD_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# 平台 / 路径
# ---------------------------------------------------------------------------

def _platform_triple() -> tuple[str, str, str]:
    """返回 (os_tag, arch_tag, archive_ext)。"""
    sys_os = platform.system().lower()
    machine = platform.machine().lower()
    if sys_os == "darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
        return ("darwin", arch, "tar.gz")
    if sys_os == "linux":
        arch = "arm64" if machine in ("aarch64", "arm64") else "x64"
        return ("linux", arch, "tar.xz")
    if sys_os in ("windows", "win32"):
        return ("win", "x64", "zip")
    raise RuntimeError(f"暂不支持的平台：{sys_os}/{machine}")


def _archive_name(version: str = NODE_VERSION) -> tuple[str, str]:
    """返回 (解压后顶层目录名, 归档文件名)。"""
    os_tag, arch_tag, ext = _platform_triple()
    base = f"node-{version}-{os_tag}-{arch_tag}"
    return base, f"{base}.{ext}"


def _download_url(version: str = NODE_VERSION) -> str:
    _base, fname = _archive_name(version)
    return f"https://nodejs.org/dist/{version}/{fname}"


def bootstrap_root() -> Path:
    return config_dir() / "node"


def _install_dir(version: str = NODE_VERSION) -> Path:
    base, _ = _archive_name(version)
    return bootstrap_root() / base


def _npx_path_in(install_dir: Path) -> Path:
    """便携包里 ``npx`` 的位置：POSIX 在 ``bin/``，Windows 在根目录的 ``npx.cmd``。"""
    if platform.system().lower() in ("windows", "win32"):
        return install_dir / "npx.cmd"
    return install_dir / "bin" / "npx"


def _stamp_path(install_dir: Path) -> Path:
    return install_dir / ".installed"


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def find_npx() -> Optional[Path]:
    """按顺序找一个能跑的 ``npx``：

    1. 当前进程 PATH + 一组常见 Node 安装目录里的系统 ``npx`` —— 解决 macOS .app
       被 launchd 启动时 PATH 被砍光、看不到 brew / nvm / fnm 装的 Node 的问题；
    2. 已 bootstrap 的本地 Node；
    3. 兜底扫旧版本 bootstrap 目录（升级了 ``NODE_VERSION`` 但旧的还在）。

    都没找到返回 ``None``，调用方应提示用户去下载。
    """
    augmented_path = _augmented_search_path()
    sys_npx = shutil.which("npx", path=augmented_path)
    if sys_npx:
        return Path(sys_npx)

    install_dir = _install_dir()
    if _stamp_path(install_dir).exists():
        npx = _npx_path_in(install_dir)
        if npx.exists():
            return npx

    root = bootstrap_root()
    if root.is_dir():
        for sub in sorted(root.iterdir(), reverse=True):
            if not sub.is_dir() or not sub.name.startswith("node-"):
                continue
            if not _stamp_path(sub).exists():
                continue
            npx = _npx_path_in(sub)
            if npx.exists():
                return npx
    return None


def _augmented_search_path() -> str:
    """当前 PATH ∪ 常见 Node 安装位置（brew / nvm / fnm / volta / n / MacPorts / Windows）。

    解决 macOS GUI 应用 PATH 被 launchd 砍成只剩 ``/usr/bin:/bin:...`` 的问题。
    只把存在的目录加进去，避免污染 PATH。
    """
    parts: list[str] = []
    cur = os.environ.get("PATH", "")
    if cur:
        parts.extend(cur.split(os.pathsep))

    home = Path.home()
    sys_os = platform.system().lower()

    candidates: list[Path] = []

    if sys_os in ("darwin", "linux"):
        candidates += [
            Path("/usr/local/bin"),
            Path("/opt/homebrew/bin"),
            Path("/opt/local/bin"),                    # MacPorts
            home / ".local" / "bin",
            home / "bin",
            home / ".volta" / "bin",                   # Volta
            home / ".fnm" / "aliases" / "default" / "bin",  # fnm 默认别名
            home / "n" / "bin",                        # n
        ]
        # nvm：~/.nvm/versions/node/<version>/bin —— 把所有版本都加上，按 semver 倒序
        nvm_root = home / ".nvm" / "versions" / "node"
        if nvm_root.is_dir():
            try:
                versions = [p for p in nvm_root.iterdir() if p.is_dir()]
                versions.sort(key=_semver_sort_key, reverse=True)
                candidates += [v / "bin" for v in versions]
            except Exception:
                pass
        # fnm：~/.local/share/fnm/node-versions/<v>/installation/bin
        fnm_root = home / ".local" / "share" / "fnm" / "node-versions"
        if fnm_root.is_dir():
            try:
                versions = [p for p in fnm_root.iterdir() if p.is_dir()]
                versions.sort(key=_semver_sort_key, reverse=True)
                candidates += [v / "installation" / "bin" for v in versions]
            except Exception:
                pass

    if sys_os in ("windows", "win32"):
        candidates += [
            Path(r"C:\Program Files\nodejs"),
            Path(r"C:\Program Files (x86)\nodejs"),
            home / "AppData" / "Roaming" / "npm",
            home / "AppData" / "Local" / "Programs" / "node",
            home / ".volta" / "bin",
            home / "AppData" / "Roaming" / "fnm" / "aliases" / "default",
        ]

    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p and p not in seen and p.strip():
            seen.add(p)
            out.append(p)
    for p in candidates:
        try:
            s = str(p)
        except Exception:
            continue
        if s in seen:
            continue
        try:
            if not p.is_dir():
                continue
        except Exception:
            continue
        seen.add(s)
        out.append(s)
    return os.pathsep.join(out)


_SEMVER_RE = re.compile(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def _semver_sort_key(p: Path) -> tuple[int, int, int, str]:
    """从 ``v20.18.1`` / ``20.18.1`` 提 (major, minor, patch, name) 排。"""
    m = _SEMVER_RE.match(p.name)
    if not m:
        return (0, 0, 0, p.name)
    g = [int(x) if x is not None else 0 for x in m.groups()]
    return (g[0], g[1], g[2], p.name)


def is_bootstrapped(version: str = NODE_VERSION) -> bool:
    """目标版本是否已经下载并解压完成。"""
    install = _install_dir(version)
    if not _stamp_path(install).exists():
        return False
    return _npx_path_in(install).exists()


def bootstrap_state() -> dict:
    """供 UI 显示一行状态：版本 / 路径 / 是否就绪。"""
    install = _install_dir()
    base, _fname = _archive_name()
    return {
        "version": NODE_VERSION,
        "install_dir": str(install),
        "archive_name": base,
        "ready": is_bootstrapped(),
        "system_npx": shutil.which("npx") or "",
    }


ProgressCb = Callable[[int, int, str], None]  # (done_bytes, total_bytes, phase)


def bootstrap_node(
    *,
    version: str = NODE_VERSION,
    progress: Optional[ProgressCb] = None,
    cancel_flag: Optional[threading.Event] = None,
    force: bool = False,
) -> tuple[bool, str]:
    """下载并解压便携版 Node。

    幂等：已就绪且 ``force=False`` 时直接返回成功。下载 / 解压期间会定期调
    ``progress(done, total, phase)``，phase 取值 ``"downloading"`` / ``"extracting"``。
    传 ``cancel_flag`` 可中途取消（被取消时返回 ``(False, "用户取消")``）。
    """
    if is_bootstrapped(version) and not force:
        return True, "已就绪"

    with _DOWNLOAD_LOCK:
        # 并发再 check 一次（拿到锁时可能别的线程已经装完）
        if is_bootstrapped(version) and not force:
            return True, "已就绪"

        try:
            url = _download_url(version)
        except Exception as e:
            return False, str(e)

        root = bootstrap_root()
        root.mkdir(parents=True, exist_ok=True)
        _base, fname = _archive_name(version)
        archive_path = root / fname
        install_dir = _install_dir(version)

        # 残留清理（避免半成品再次解压时撞）
        if install_dir.exists() and force:
            shutil.rmtree(install_dir, ignore_errors=True)

        # ---- 下载 ----
        try:
            ok, msg = _download_with_progress(
                url, archive_path, progress=progress, cancel_flag=cancel_flag,
            )
        except Exception as e:
            return False, f"下载异常：{e}"
        if not ok:
            try:
                archive_path.unlink(missing_ok=True)
            except Exception:
                pass
            return False, msg

        # ---- 解压 ----
        try:
            if progress is not None:
                progress(0, 0, "extracting")
            _extract_archive(archive_path, root, expected_top=install_dir.name)
        except Exception as e:
            return False, f"解压失败：{e}"
        finally:
            try:
                archive_path.unlink(missing_ok=True)
            except Exception:
                pass

        # ---- 校验 + 落 stamp ----
        npx = _npx_path_in(install_dir)
        if not npx.exists():
            return False, f"解压后未找到 npx：{npx}"
        try:
            _stamp_path(install_dir).write_text(version, encoding="utf-8")
        except Exception:
            pass

        if progress is not None:
            progress(1, 1, "done")
        return True, f"Node {version} 已就绪（{install_dir}）"


# ---------------------------------------------------------------------------
# 内部：下载 / 解压
# ---------------------------------------------------------------------------

def _download_with_progress(
    url: str,
    dest: Path,
    *,
    progress: Optional[ProgressCb],
    cancel_flag: Optional[threading.Event],
    chunk: int = 64 * 1024,
) -> tuple[bool, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "my-own-script-bootstrap/1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as f:
            while True:
                if cancel_flag is not None and cancel_flag.is_set():
                    try:
                        tmp.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return False, "用户取消"
                buf = resp.read(chunk)
                if not buf:
                    break
                f.write(buf)
                done += len(buf)
                if progress is not None:
                    progress(done, total, "downloading")
        os.replace(tmp, dest)
    return True, "ok"


def _extract_archive(archive: Path, dest_root: Path, *, expected_top: str) -> None:
    name = archive.name.lower()
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(dest_root)
    elif name.endswith(".tar.xz"):
        with tarfile.open(archive, "r:xz") as tf:
            tf.extractall(dest_root)
    elif name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest_root)
    else:
        raise RuntimeError(f"未知归档格式：{archive.name}")

    expected = dest_root / expected_top
    if not expected.exists():
        # 有些 mirror 解压顶层目录名不一致；尝试找最近修改的 node-* 目录
        candidates = [p for p in dest_root.iterdir() if p.is_dir() and p.name.startswith("node-")]
        if candidates:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            candidates[0].rename(expected)
        else:
            raise RuntimeError(f"解压后未找到目标目录：{expected}")
