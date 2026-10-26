"""Node.js >=20.20.0 detection and locked runtime/npm package installation."""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from toolbox_backend.adapters.ai_process import SupervisedProcess
from toolbox_backend.domain.mcp import (
    MANAGED_NODE_VERSION,
    NodeRuntime,
    Runtime,
    package_versions,
)
from toolbox_backend.mcp.runner import redact_mcp, secure_directory

MIN_NODE_TUPLE = (20, 20, 0)
MAX_JOB_OUTPUT_BYTES = 256 * 1024
INSTALL_TIMEOUT_S = 600.0
RESOURCES_MCP_DIR = Path(__file__).resolve().parents[3] / "resources/mcp"

RuntimeFetcher = Callable[[str], Awaitable[bytes]]
_NODE_PROBE_CACHE: dict[tuple[str, int, int, int], str | None] = {}


@functools.cache
def locked_packages() -> dict[str, str]:
    """Lazily read locked npm package versions from resources/mcp/package.json on first use."""
    return dict(package_versions())


def parse_node_version(raw: str) -> tuple[int, int, int] | None:
    text = (raw or "").strip()
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def runtime_archive_stem() -> str:
    sys_name = platform.system().lower()
    machine = platform.machine().lower()
    os_part = "darwin" if sys_name == "darwin" else "linux"
    arch_part = "arm64" if machine in ("arm64", "aarch64") else "x64"
    ver = (
        MANAGED_NODE_VERSION
        if MANAGED_NODE_VERSION.startswith("v")
        else f"v{MANAGED_NODE_VERSION}"
    )
    return f"node-{ver}-{os_part}-{arch_part}"


def probe_node_executable(node_path: Path) -> str | None:
    try:
        if not node_path.is_file() or not os.access(node_path, os.X_OK):
            return None
        st = node_path.stat()
        cache_key = (str(node_path), st.st_ino, st.st_mtime_ns, st.st_size)
        if cache_key in _NODE_PROBE_CACHE:
            return _NODE_PROBE_CACHE[cache_key]
        res = subprocess.run(
            [str(node_path), "--version"],
            capture_output=True,
            text=True,
            timeout=3,
            env={"PATH": "/usr/bin:/bin"},
        )
    except OSError, subprocess.SubprocessError:
        return None
    if res.returncode != 0:
        _NODE_PROBE_CACHE[cache_key] = None
        return None
    raw = (res.stdout or res.stderr or "").strip().splitlines()
    if not raw:
        _NODE_PROBE_CACHE[cache_key] = None
        return None
    ver_str = raw[0].strip()
    parsed = parse_node_version(ver_str)
    if parsed is None or parsed < MIN_NODE_TUPLE:
        _NODE_PROBE_CACHE[cache_key] = None
        return None
    normalized = ver_str if ver_str.startswith("v") else f"v{ver_str}"
    _NODE_PROBE_CACHE[cache_key] = normalized
    return normalized


def _managed_node_candidates(data_dir: Path) -> list[Path]:
    runtime_root = data_dir / "mcp/runtime"
    if not runtime_root.is_dir():
        return []
    preferred = runtime_root / runtime_archive_stem() / "bin/node"
    candidates: list[Path] = []
    if preferred.is_file():
        candidates.append(preferred)
    for child in sorted(runtime_root.glob("node-v*/bin/node"), reverse=True):
        if child not in candidates:
            candidates.append(child)
    return candidates


def _legacy_bootstrap_candidates(legacy_config_dir: Path | None) -> list[Path]:
    if legacy_config_dir is None or not legacy_config_dir.is_dir():
        return []
    node_root = legacy_config_dir / "node"
    if not node_root.is_dir():
        return []
    return sorted(node_root.glob("node-*/bin/node"), reverse=True)


def _system_node_candidates(
    path_extras: Sequence[str | Path] | None,
    legacy_config_dir: Path | None,
) -> list[Path]:
    candidates: list[Path] = []
    if path_extras is not None:
        for entry in path_extras:
            p = Path(entry)
            cand = p if p.is_file() else p / "node"
            candidates.append(cand)
        candidates.extend(_legacy_bootstrap_candidates(legacy_config_dir))
        return candidates

    if "PYTEST_CURRENT_TEST" in os.environ or "TOOLBOX_TEST_GUARD_LOG" in os.environ:
        candidates.extend(_legacy_bootstrap_candidates(legacy_config_dir))
        return candidates

    env_path = os.environ.get("PATH", "")
    for directory in env_path.split(os.pathsep):
        if directory:
            candidates.append(Path(directory) / "node")
    for directory in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        candidates.append(Path(directory) / "node")
    candidates.extend(_legacy_bootstrap_candidates(legacy_config_dir))
    return candidates


def detect_node_runtime(
    data_dir: Path,
    configured: NodeRuntime,
    *,
    path_extras: Sequence[str | Path] | None = None,
    legacy_config_dir: Path | None = None,
) -> tuple[NodeRuntime, list[str]]:
    """Detect usable Node >= 20.20.0 in order: confirmed path -> managed -> detected/legacy."""
    warnings: list[str] = []

    # 1. User-confirmed path in config.mcp.runtime.node.path
    if configured.path:
        cand = Path(configured.path)
        ver = probe_node_executable(cand)
        if ver:
            source = (
                configured.source
                if configured.source in ("managed", "detected")
                else "detected"
            )
            return NodeRuntime(source=source, path=str(cand), version=ver), warnings
        warnings.append("已配置的 Node 路径不可用或版本低于 20.20.0")

    # 2. Managed runtime directory (<data-dir>/mcp/runtime/)
    for cand in _managed_node_candidates(data_dir):
        ver = probe_node_executable(cand)
        if ver:
            return NodeRuntime(source="managed", path=str(cand), version=ver), warnings

    # 3. System / brew / fnm / legacy bootstrap read-only
    for cand in _system_node_candidates(path_extras, legacy_config_dir):
        ver = probe_node_executable(cand)
        if ver:
            return NodeRuntime(source="detected", path=str(cand), version=ver), warnings

    return NodeRuntime(source="none"), warnings


def inspect_packages(data_dir: Path) -> tuple[bool, bool, bool]:
    """Return (lark_ready, figma_ready, keytar_ready) under <data-dir>/mcp/packages/node_modules."""
    locked = locked_packages()
    nm = data_dir / "mcp/packages/node_modules"
    lark_dir = nm / "@larksuiteoapi/lark-mcp"
    figma_dir = nm / "figma-developer-mcp"

    lark_ready = False
    try:
        pkg = json.loads((lark_dir / "package.json").read_text(encoding="utf-8"))
        lark_ready = (
            pkg.get("version") == locked["@larksuiteoapi/lark-mcp"]
            and (lark_dir / "dist/cli.js").is_file()
        )
    except OSError, ValueError, TypeError:
        lark_ready = False

    figma_ready = False
    try:
        pkg = json.loads((figma_dir / "package.json").read_text(encoding="utf-8"))
        figma_ready = (
            pkg.get("version") == locked["figma-developer-mcp"]
            and (figma_dir / "dist/bin.js").is_file()
        )
    except OSError, ValueError, TypeError:
        figma_ready = False

    keytar_ready = (nm / "keytar").is_dir() or (lark_dir / "node_modules/keytar").is_dir()
    return lark_ready, figma_ready, keytar_ready


def lark_cli_js_path(data_dir: Path) -> Path:
    return data_dir / "mcp/packages/node_modules/@larksuiteoapi/lark-mcp/dist/cli.js"


def figma_bin_js_path(data_dir: Path) -> Path:
    return data_dir / "mcp/packages/node_modules/figma-developer-mcp/dist/bin.js"


async def default_runtime_fetcher(url: str) -> bytes:
    def _download() -> bytes:
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
            return resp.read()

    return await asyncio.to_thread(_download)


def parse_shasums256(shasums_text: str, filename: str) -> str | None:
    for raw_line in shasums_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            digest = parts[0].strip().lower()
            target = parts[1].lstrip("*").strip()
            if target == filename and re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    return None


def install_node_from_tarball(
    data_dir: Path,
    archive_stem: str,
    archive_name: str,
    shasums_bytes: bytes,
    tar_bytes: bytes,
) -> Path:
    """Verify SHA256 and extract Node tarball with tarfile filter='data'."""
    shasums_text = shasums_bytes.decode("utf-8", errors="replace")
    expected_sha = parse_shasums256(shasums_text, archive_name)
    if not expected_sha:
        raise RuntimeError(f"SHASUMS256.txt 未找到 {archive_name} 的校验值")

    actual_sha = hashlib.sha256(tar_bytes).hexdigest().lower()
    if actual_sha != expected_sha:
        raise RuntimeError(
            "Node 压缩包 SHA256 校验失败: "
            f"expected {expected_sha[:12]}..., got {actual_sha[:12]}..."
        )

    runtime_root = ensure_data_subdir(data_dir, "mcp", "runtime")
    target_dir = runtime_root / archive_stem
    staging_parent = Path(tempfile.mkdtemp(prefix=".staging-", dir=runtime_root))
    try:
        archive_file = staging_parent / archive_name
        archive_file.write_bytes(tar_bytes)
        extract_dir = staging_parent / "extract"
        extract_dir.mkdir(mode=0o700)
        with tarfile.open(archive_file, mode="r:*") as tf:
            tf.extractall(path=extract_dir, filter="data")

        extracted_root = extract_dir / archive_stem
        if not extracted_root.is_dir():
            subdirs = [p for p in extract_dir.iterdir() if p.is_dir()]
            if len(subdirs) == 1:
                extracted_root = subdirs[0]
            else:
                raise RuntimeError("Node 压缩包目录结构无效")

        node_bin = extracted_root / "bin/node"
        if not node_bin.is_file():
            raise RuntimeError("解压后的 Node 缺少 bin/node")

        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.move(str(extracted_root), str(target_dir))
        (target_dir / ".installed").write_text(f"v{MANAGED_NODE_VERSION}\n", encoding="utf-8")
        return target_dir / "bin/node"
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def resolve_npm_executable(
    node_path: Path, path_extras: Sequence[str | Path] | None = None
) -> Path:
    sibling = node_path.parent / "npm"
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return sibling
    if path_extras is not None:
        for entry in path_extras:
            p = Path(entry)
            cand = p if p.is_file() and p.name == "npm" else p / "npm"
            if cand.is_file() and os.access(cand, os.X_OK):
                return cand
    else:
        found = shutil.which("npm")
        if found:
            return Path(found)
    raise RuntimeError("未找到可用的 npm 可执行文件")


def append_capped_output(current: str, chunk: str) -> str:
    redacted = redact_mcp(chunk)
    combined = (current + redacted).encode("utf-8", errors="replace")
    if len(combined) <= MAX_JOB_OUTPUT_BYTES:
        return combined.decode("utf-8", errors="replace")
    return combined[:MAX_JOB_OUTPUT_BYTES].decode("utf-8", errors="ignore")


def ensure_data_subdir(data_dir: Path, *parts: str) -> Path:
    if not data_dir.exists():
        data_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        data_dir.chmod(0o700)
    return secure_directory(data_dir, *parts)


def stage_locked_package_manifests(data_dir: Path) -> Path:
    packages_dir = ensure_data_subdir(data_dir, "mcp", "packages")
    for name in ("package.json", "package-lock.json"):
        src = RESOURCES_MCP_DIR / name
        if not src.is_file():
            raise RuntimeError(f"缺少锁定清单文件: {name}")
        dst = packages_dir / name
        shutil.copyfile(src, dst)
        dst.chmod(0o600)
    return packages_dir


async def run_supervised_step(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    path_extras: Sequence[str | Path],
    on_proc: Callable[[SupervisedProcess | None], None],
    on_output: Callable[[str], None],
) -> int:
    owner = await SupervisedProcess.start(
        argv,
        str(cwd),
        env=env,
        path_extras=path_extras,
        stdio=True,
    )
    on_proc(owner)
    try:
        async def _pump(stream: asyncio.StreamReader | None) -> None:
            if stream is None:
                return
            while line := await stream.readline():
                on_output(line.decode("utf-8", errors="replace"))

        await asyncio.gather(_pump(owner.stdout), _pump(owner.stderr))
        return await owner.proc.wait()
    finally:
        on_proc(None)
        await owner.close()


__all__ = [
    "INSTALL_TIMEOUT_S",
    "MAX_JOB_OUTPUT_BYTES",
    "MIN_NODE_TUPLE",
    "RESOURCES_MCP_DIR",
    "Runtime",
    "RuntimeFetcher",
    "append_capped_output",
    "default_runtime_fetcher",
    "detect_node_runtime",
    "figma_bin_js_path",
    "inspect_packages",
    "install_node_from_tarball",
    "lark_cli_js_path",
    "parse_node_version",
    "parse_shasums256",
    "probe_node_executable",
    "resolve_npm_executable",
    "run_supervised_step",
    "runtime_archive_stem",
    "stage_locked_package_manifests",
]
