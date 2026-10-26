"""S6-B regression tests for Node/npm runtime detection and install job."""

import asyncio
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from uuid import uuid4

import pytest

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.api.mcp_schemas import RuntimeInstallRequest
from toolbox_backend.domain.mcp import NodeRuntime
from toolbox_backend.logging_setup import register_secret
from toolbox_backend.services.events import EventHub
from toolbox_backend.services.mcp import McpService


@pytest.fixture
def isolated_supervisor(monkeypatch):
    original = asyncio.create_subprocess_exec

    async def spawn(*argv, **kwargs):
        if len(argv) >= 3 and argv[1:3] == ("-m", "toolbox_backend.adapters.proc_supervisor"):
            argv = (
                argv[0],
                "-c",
                "import sys; from toolbox_backend.adapters import proc_supervisor as m; "
                "m.process_identity=lambda pid: {}; sys.exit(m.main())",
            )
        return await original(*argv, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)


def _write_executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _make_fake_node(bin_dir: Path, version: str = "v24.13.0") -> Path:
    return _write_executable(
        bin_dir / "node",
        f"""
import sys
if "--version" in sys.argv or "-v" in sys.argv:
    print({version!r})
    sys.exit(0)
sys.exit(0)
""",
    )


def _make_node_tarball(
    archive_dir_name: str,
    *,
    version: str = "v24.13.0",
    traversal_member: str | None = None,
) -> tuple[bytes, str]:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        node_script = (
            f"#!{sys.executable}\n"
            f"import sys\n"
            f"if '--version' in sys.argv or '-v' in sys.argv:\n"
            f"    print({version!r})\n"
            f"    sys.exit(0)\n"
        ).encode()
        info = tarfile.TarInfo(name=f"{archive_dir_name}/bin/node")
        info.size = len(node_script)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(node_script))

        if traversal_member is not None:
            bad = b"traversal"
            bad_info = tarfile.TarInfo(name=traversal_member)
            bad_info.size = len(bad)
            bad_info.mode = 0o644
            tf.addfile(bad_info, io.BytesIO(bad))

    raw = buf.getvalue()
    sha256 = hashlib.sha256(raw).hexdigest()
    return raw, sha256


@pytest.mark.asyncio
async def test_runtime_detection_priority_and_min_version(tmp_path):
    """Detection order: confirmed config path -> managed dir -> detected path_extras / legacy bootstrap; must be >=20.20.0."""
    data_dir = tmp_path / "data"
    legacy_dir = tmp_path / "legacy"
    store = ConfigStore(data_dir)
    await store.initialize()

    # 1. Old version (< 20.20.0) in path_extras is rejected
    old_bin = tmp_path / "old_bin"
    _make_fake_node(old_bin, "v20.18.1")
    svc = McpService(
        store,
        MemoryCredentials(),
        MemoryCredentials(),
        events=EventHub(),
        path_extras=[old_bin],
        legacy_config_dir=legacy_dir,
    )
    snap = await svc.snapshot()
    assert snap.runtime.node.source == "none"
    assert snap.runtime.ready is False

    # 2. Legacy bootstrap node (>= 20.20.0) is detected read-only
    legacy_node = _make_fake_node(
        legacy_dir / "node/node-v24.13.0-darwin-arm64/bin", "v24.13.0"
    )
    snap = await svc.snapshot()
    assert snap.runtime.node.source == "detected"
    assert snap.runtime.node.path == str(legacy_node)
    assert snap.runtime.node.version == "v24.13.0"

    # 3. Managed directory takes precedence over detected/legacy
    managed_bin = data_dir / "mcp/runtime/node-v24.13.0-darwin-arm64/bin"
    managed_node = _make_fake_node(managed_bin, "v24.13.0")
    (managed_bin.parent / ".installed").write_text("v24.13.0\n", encoding="utf-8")
    snap = await svc.snapshot()
    assert snap.runtime.node.source == "managed"
    assert snap.runtime.node.path == str(managed_node)

    # 4. User-confirmed path in config.mcp.runtime.node.path takes top precedence
    confirmed_bin = tmp_path / "confirmed_bin"
    confirmed_node = _make_fake_node(confirmed_bin, "v22.14.0")
    await store.update(
        snap.revision,
        lambda cfg: setattr(
            cfg.mcp.runtime,
            "node",
            NodeRuntime(source="detected", path=str(confirmed_node), version="v22.14.0"),
        ),
    )
    snap = await svc.snapshot()
    assert snap.runtime.node.source == "detected"
    assert snap.runtime.node.path == str(confirmed_node)
    assert snap.runtime.node.version == "v22.14.0"


@pytest.mark.asyncio
async def test_runtime_install_job_success_redaction_and_ws_events(
    isolated_supervisor, tmp_path
):
    """Install job verifies SHA256, extracts with filter='data', runs npm ci --ignore-scripts then npm rebuild keytar, redacts output <=256KiB, emits mcp.job WS events."""
    data_dir = tmp_path / "data"
    store = ConfigStore(data_dir)
    await store.initialize()
    events = EventHub()

    secret_val = "super-secret-install-token-999"
    register_secret(secret_val)

    fake_bin = tmp_path / "fake_bin"
    npm_log = tmp_path / "npm_calls.log"
    _write_executable(
        fake_bin / "npm",
        f"""
import json, pathlib, sys
log = pathlib.Path({str(npm_log)!r})
with log.open("a", encoding="utf-8") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
print("npm output with secret {secret_val} and Bearer eyJabc123def456")
print("X" * 300000)
if sys.argv[1:2] == ["ci"]:
    idx = sys.argv.index("--prefix")
    prefix = pathlib.Path(sys.argv[idx + 1])
    lark_dir = prefix / "node_modules/@larksuiteoapi/lark-mcp/dist"
    lark_dir.mkdir(parents=True, exist_ok=True)
    (lark_dir / "cli.js").write_text("// fake lark cli\\n", encoding="utf-8")
    (lark_dir.parent / "package.json").write_text('{{"version": "0.5.1"}}', encoding="utf-8")
    figma_dir = prefix / "node_modules/figma-developer-mcp/dist"
    figma_dir.mkdir(parents=True, exist_ok=True)
    (figma_dir / "bin.js").write_text("// fake figma bin\\n", encoding="utf-8")
    (figma_dir.parent / "package.json").write_text('{{"version": "0.13.2"}}', encoding="utf-8")
sys.exit(0)
""",
    )

    svc = McpService(
        store,
        MemoryCredentials(),
        MemoryCredentials(),
        events=events,
        path_extras=[fake_bin],
        legacy_config_dir=tmp_path / "legacy",
    )
    archive_stem = svc.runtime_archive_stem()
    archive_name = f"{archive_stem}.tar.gz"
    tar_bytes, sha256 = _make_node_tarball(archive_stem)
    shasums_text = f"{sha256}  {archive_name}\n"

    async def fake_fetcher(url: str) -> bytes:
        if url.endswith("SHASUMS256.txt"):
            return shasums_text.encode("utf-8")
        if url.endswith(archive_name):
            return tar_bytes
        raise AssertionError(f"unexpected url: {url}")

    svc.runtime_fetcher = fake_fetcher

    job = await svc.install_runtime(RuntimeInstallRequest(request_id=uuid4()))
    final_job = await svc.wait_job(job.job_id, timeout=10.0)
    assert final_job.state == "completed", final_job.error
    assert len(final_job.output.encode("utf-8")) <= 256 * 1024
    assert "npm output with secret" in final_job.output
    assert secret_val not in final_job.output
    assert "eyJabc123def456" not in final_job.output

    calls = [
        line.strip()
        for line in npm_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(calls) == 2
    assert "--ignore-scripts" in calls[0]
    assert "--prefix" in calls[0]
    assert "rebuild" in calls[1] and "keytar" in calls[1]

    snap = await svc.snapshot()
    assert snap.runtime.ready is True
    assert snap.runtime.node.source == "managed"
    assert snap.runtime.packages_installed is True

    # Verify WS mcp.job events were published
    history = [ev.event for ev in events._state("mcp").history]
    assert "mcp.job" in history
    assert "mcp.status" in history


@pytest.mark.asyncio
async def test_runtime_install_rejects_sha256_mismatch(isolated_supervisor, tmp_path):
    """SHA256 mismatch must fail the install job and leave no extracted runtime."""
    data_dir = tmp_path / "data"
    store = ConfigStore(data_dir)
    await store.initialize()
    svc = McpService(
        store,
        MemoryCredentials(),
        MemoryCredentials(),
        events=EventHub(),
        path_extras=[],
        legacy_config_dir=tmp_path / "legacy",
    )
    archive_stem = svc.runtime_archive_stem()
    archive_name = f"{archive_stem}.tar.gz"
    tar_bytes, _ = _make_node_tarball(archive_stem)
    bad_shasums = f"{'0' * 64}  {archive_name}\n"

    async def fake_fetcher(url: str) -> bytes:
        if url.endswith("SHASUMS256.txt"):
            return bad_shasums.encode("utf-8")
        return tar_bytes

    svc.runtime_fetcher = fake_fetcher

    job = await svc.install_runtime(RuntimeInstallRequest(request_id=uuid4()))
    final_job = await svc.wait_job(job.job_id, timeout=5.0)
    assert final_job.state == "failed"
    assert "SHA256" in (final_job.error or "")
    assert not (data_dir / "mcp/runtime" / archive_stem).exists()


@pytest.mark.asyncio
async def test_runtime_install_rejects_tar_path_traversal(isolated_supervisor, tmp_path):
    """tarfile filter='data' must reject ../ path traversal entries."""
    data_dir = tmp_path / "data"
    store = ConfigStore(data_dir)
    await store.initialize()
    svc = McpService(
        store,
        MemoryCredentials(),
        MemoryCredentials(),
        events=EventHub(),
        path_extras=[],
        legacy_config_dir=tmp_path / "legacy",
    )
    archive_stem = svc.runtime_archive_stem()
    archive_name = f"{archive_stem}.tar.gz"
    tar_bytes, sha256 = _make_node_tarball(
        archive_stem, traversal_member="../escaped.txt"
    )
    shasums = f"{sha256}  {archive_name}\n"

    async def fake_fetcher(url: str) -> bytes:
        if url.endswith("SHASUMS256.txt"):
            return shasums.encode("utf-8")
        return tar_bytes

    svc.runtime_fetcher = fake_fetcher

    job = await svc.install_runtime(RuntimeInstallRequest(request_id=uuid4()))
    final_job = await svc.wait_job(job.job_id, timeout=5.0)
    assert final_job.state == "failed"
    assert not (data_dir / "mcp/escaped.txt").exists()
    assert not (tmp_path / "escaped.txt").exists()


@pytest.mark.asyncio
async def test_runtime_install_cancel_reaps_process_group(isolated_supervisor, tmp_path):
    """Cancelling a running install job must terminate npm and its grandchild process group."""
    data_dir = tmp_path / "data"
    store = ConfigStore(data_dir)
    await store.initialize()
    pid_file = tmp_path / "npm_pids.txt"
    fake_bin = tmp_path / "fake_bin"
    _write_executable(
        fake_bin / "npm",
        f"""
import os, pathlib, signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"])
pathlib.Path({str(pid_file)!r}).write_text(f"{{os.getpid()}}\\n{{child.pid}}\\n", encoding="utf-8")
print("npm started", flush=True)
time.sleep(60)
""",
    )
    svc = McpService(
        store,
        MemoryCredentials(),
        MemoryCredentials(),
        events=EventHub(),
        path_extras=[fake_bin],
        legacy_config_dir=tmp_path / "legacy",
    )
    archive_stem = svc.runtime_archive_stem()
    archive_name = f"{archive_stem}.tar.gz"
    tar_bytes, sha256 = _make_node_tarball(archive_stem)

    async def fake_fetcher(url: str) -> bytes:
        if url.endswith("SHASUMS256.txt"):
            return f"{sha256}  {archive_name}\n".encode()
        return tar_bytes

    svc.runtime_fetcher = fake_fetcher

    job = await svc.install_runtime(RuntimeInstallRequest(request_id=uuid4()))
    async with asyncio.timeout(5):
        while not pid_file.exists():  # noqa: ASYNC110
            await asyncio.sleep(0.05)
    pids = [int(x) for x in pid_file.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(pids) == 2

    cancelled = await svc.cancel_job(job.job_id)
    assert cancelled.state == "cancelled"

    for pid in pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    await svc.close()


def test_import_and_contracts_without_resources_dir(tmp_path):
    """Importing toolbox_backend.contracts or mcp.runtime from an isolated src copy without resources/ must not fail."""
    backend_dir = Path(__file__).resolve().parents[1]
    isolated_src = tmp_path / "next" / "backend" / "src"
    shutil.copytree(
        backend_dir / "src",
        isolated_src,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(isolated_src), env.get("PYTHONPATH", "")]
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import toolbox_backend.contracts as c, toolbox_backend.mcp.runtime as r; "
            "files = c.generate(); "
            "assert set(files) == {'openapi.json', 'events.schema.json'}; "
            "print(c.__file__)",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert probe.returncode == 0, probe.stderr
    assert str(isolated_src) in probe.stdout.strip()

