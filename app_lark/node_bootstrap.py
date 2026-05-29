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

import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

from app_ado.store import config_dir


# 想升级 Node 就只改这一行；下次启动会拉新版本。
NODE_VERSION = "v20.18.1"

# MIN 不能写死，要跟 npm 上的 `@larksuiteoapi/lark-mcp` engines 走。
# 网络拿不到时回退到这个基线（与 NODE_VERSION 大版本对齐，保证 bootstrap 一定满足）。
_BASELINE_MIN_NODE: tuple[int, int, int] = (20, 0, 0)
_MIN_NODE_CACHE_TTL_SEC = 24 * 3600
_NPM_REGISTRY_URL = "https://registry.npmjs.org/@larksuiteoapi/lark-mcp/latest"


def _min_node_cache_path() -> Path:
    return config_dir() / "lark_mcp_min_node.json"


def _parse_engines_node_spec(spec: str) -> Optional[tuple[int, int, int]]:
    """把 npm engines 字段（``">=20.0.0"`` / ``"^20.18.0"`` / ``"20"`` 这类）提成 (M, m, p)。"""
    if not spec:
        return None
    m = re.search(r"(?:>=?|\^|~)?\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", spec)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0))


def _fetch_min_node_from_registry(timeout_sec: float = 5.0) -> Optional[tuple[str, tuple[int, int, int]]]:
    """命中 npm registry 拿 engines.node。失败返回 None（调用方自己回退）。"""
    try:
        req = urllib.request.Request(
            _NPM_REGISTRY_URL,
            headers={"User-Agent": "my-own-script/min-node-check"},
        )
        with urllib.request.urlopen(req, timeout=timeout_sec) as r:
            data = json.loads(r.read())
    except Exception:
        return None
    spec = str(((data.get("engines") or {}).get("node") or "")).strip()
    parsed = _parse_engines_node_spec(spec)
    if parsed is None:
        return None
    return (spec, parsed)


def get_min_node_version() -> tuple[int, int, int]:
    """返回 MCP 当前要求的最小 Node 版本，按 (cache < 24h) → (registry) → (基线) 顺序回退。"""
    cache_path = _min_node_cache_path()
    try:
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if time.time() - float(cached.get("ts") or 0) < _MIN_NODE_CACHE_TTL_SEC:
                ver = cached.get("version")
                if isinstance(ver, list) and len(ver) == 3:
                    return (int(ver[0]), int(ver[1]), int(ver[2]))
    except Exception:
        pass

    fresh = _fetch_min_node_from_registry()
    if fresh is not None:
        spec, ver = fresh
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({"ts": time.time(), "spec": spec, "version": list(ver)}),
                encoding="utf-8",
            )
        except Exception:
            pass
        return ver

    # registry 拿不到 → 用上一次有效缓存（即便过期）；再不行用基线
    try:
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            ver = cached.get("version")
            if isinstance(ver, list) and len(ver) == 3:
                return (int(ver[0]), int(ver[1]), int(ver[2]))
    except Exception:
        pass
    return _BASELINE_MIN_NODE


def min_node_version_str() -> str:
    return "v" + ".".join(str(x) for x in get_min_node_version())

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

def _bootstrap_npxes() -> list[Path]:
    """枚举所有已 bootstrap 的 npx，按 semver 倒序（新版优先）。"""
    out: list[Path] = []
    root = bootstrap_root()
    if not root.is_dir():
        return out
    try:
        installs = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("node-")]
    except Exception:
        return out
    installs.sort(key=_semver_sort_key, reverse=True)
    for sub in installs:
        if not _stamp_path(sub).exists():
            continue
        npx = _npx_path_in(sub)
        if npx.exists():
            out.append(npx)
    return out


def _find_system_npx() -> Optional[Path]:
    """只在 augmented PATH 里找系统 npx；显式跳过 bootstrap 目录里的同名 npx。"""
    bootstrap_bin_dirs = {str(npx.parent) for npx in _bootstrap_npxes()}
    augmented = augmented_search_path()
    parts = [p for p in augmented.split(os.pathsep) if p and p not in bootstrap_bin_dirs]
    sys_npx = shutil.which("npx", path=os.pathsep.join(parts))
    return Path(sys_npx) if sys_npx else None


def find_npx() -> Optional[Path]:
    """按 bootstrap → 系统 顺序找一个可执行的 ``npx``。不做版本校验，只关心存在性。"""
    for npx in _bootstrap_npxes():
        return npx
    return _find_system_npx()


def _node_path_beside(npx: Path) -> Path:
    """同一份 install 里的 ``node`` 可执行路径。Windows 是 ``node.exe``，否则是 ``node``。"""
    is_win = platform.system().lower() in ("windows", "win32")
    return npx.parent / ("node.exe" if is_win else "node")


def check_node_version(
    npx: Path,
    *,
    min_version: Optional[tuple[int, int, int]] = None,
) -> tuple[bool, str]:
    """跑 ``node --version`` 验证版本是否 ≥ ``min_version``。

    ``min_version`` 留空表示动态从 :func:`get_min_node_version` 拿 —— 默认就用 npm
    registry 上 ``@larksuiteoapi/lark-mcp`` 的 engines.node。
    返回 ``(够新吗, 版本字符串)``。版本字符串形如 ``v22.15.0``；拿不到时回 ``"?"``。
    """
    node = _node_path_beside(npx)
    if not node.exists():
        return (False, "?")
    try:
        out = subprocess.check_output(
            [str(node), "--version"], timeout=5, text=True,
        ).strip()
    except Exception:
        return (False, "?")
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", out)
    if not m:
        return (False, out or "?")
    cur = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    floor = min_version if min_version is not None else get_min_node_version()
    return (cur >= floor, out)


def find_usable_npx() -> tuple[Optional[Path], str, str]:
    """按 "内置 → 系统" 顺序找 ``npx``，并校验 Node 版本。

    返回 ``(npx, status, version)``，``status`` 四态：

    - ``"ok"``：找到达标的 npx；
    - ``"bootstrap_too_old"``：bootstrap 有但 node 版本低于当前 MCP 要求 —— 调用方应
      静默 ``force=True`` 重新 bootstrap；
    - ``"system_too_old"``：bootstrap 没装，系统 npx 找到但 node 版本不够 —— 提示用户
      装内置 Node；
    - ``"missing"``：完全找不到 npx —— 提示用户装内置 Node。
    """
    min_ver = get_min_node_version()

    boot_list = _bootstrap_npxes()
    if boot_list:
        npx = boot_list[0]
        ok, ver = check_node_version(npx, min_version=min_ver)
        if ok:
            return (npx, "ok", ver)
        return (npx, "bootstrap_too_old", ver)

    sys_npx = _find_system_npx()
    if sys_npx is None:
        return (None, "missing", "")
    ok, ver = check_node_version(sys_npx, min_version=min_ver)
    if ok:
        return (sys_npx, "ok", ver)
    return (sys_npx, "system_too_old", ver)


def augment_path_env() -> None:
    """把扩展过的搜索路径写回 ``os.environ['PATH']``。

    重要：子进程（如 ``npx``，shebang 是 ``#!/usr/bin/env node``）需要在 PATH 里
    也能找到 ``node``，单纯把路径传给 ``shutil.which(..., path=...)`` 不够。
    `mcp_lark_server.py` execvp 之前 / `subprocess.Popen` 之前都得调一次。
    """
    os.environ["PATH"] = augmented_search_path()


def augmented_search_path() -> str:
    """当前 PATH ∪ bootstrap 的 Node bin ∪ 常见系统 Node 安装位置。

    解决 macOS GUI 应用 PATH 被 launchd 砍成只剩 ``/usr/bin:/bin:...`` 的问题。
    只把存在的目录加进去，避免污染 PATH。
    """
    parts: list[str] = []

    # 1. bootstrap 出来的 Node（如果有）—— 优先级最高，保证 npx 跟 node 取自同一份
    root = bootstrap_root()
    if root.is_dir():
        try:
            installs = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("node-")]
            installs.sort(key=_semver_sort_key, reverse=True)  # 新版本在前
            for sub in installs:
                if not _stamp_path(sub).exists():
                    continue
                parts.append(str(_npx_path_in(sub).parent))
        except Exception:
            pass

    # 2. 当前进程已有的 PATH
    cur = os.environ.get("PATH", "")
    if cur:
        parts.extend(cur.split(os.pathsep))

    # 3. 系统常见 Node 安装位置
    home = Path.home()
    sys_os = platform.system().lower()
    candidates: list[Path] = []

    if sys_os in ("darwin", "linux"):
        candidates += [
            Path("/usr/local/bin"),
            Path("/opt/homebrew/bin"),
            Path("/opt/local/bin"),                          # MacPorts
            home / ".local" / "bin",
            home / "bin",
            home / ".volta" / "bin",                         # Volta
            home / ".fnm" / "aliases" / "default" / "bin",   # fnm 默认别名
            home / "n" / "bin",                              # n
        ]
        nvm_root = home / ".nvm" / "versions" / "node"
        if nvm_root.is_dir():
            try:
                versions = [p for p in nvm_root.iterdir() if p.is_dir()]
                versions.sort(key=_semver_sort_key, reverse=True)
                candidates += [v / "bin" for v in versions]
            except Exception:
                pass
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
        if p and p.strip() and p not in seen:
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
