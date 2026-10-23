"""Fail-closed guards against accidentally launching a real AI CLI in tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.guards import install_ai_cli_guard
from toolbox_backend.adapters.ai_process import SupervisedProcess

EXEC_APIS = (
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "execl",
    "execlp",
    "execle",
    "execlpe",
    "posix_spawn",
    "posix_spawnp",
)


def _fake_claude(tmp_path: Path) -> tuple[Path, Path]:
    executable = tmp_path / "claude"
    marker = tmp_path / "must-not-run.txt"
    executable.write_text(f"#!/bin/sh\nprintf executed > {marker}\n")
    executable.chmod(0o700)
    return executable, marker


def _call_exec_api(name: str, executable: Path, tmp_path: Path):
    env = {"PATH": os.pathsep.join([str(tmp_path), "/usr/bin", "/bin"])}
    argv = [str(executable), "safe-argument"]
    if name == "execv":
        return os.execv(str(executable), argv)
    if name == "execve":
        return os.execve(str(executable), argv, env)
    if name == "execvp":
        return os.execvp("claude", ["claude", "safe-argument"])
    if name == "execvpe":
        return os.execvpe("claude", ["claude", "safe-argument"], env)
    if name == "execl":
        return os.execl(str(executable), "claude", "safe-argument")
    if name == "execlp":
        return os.execlp("claude", "claude", "safe-argument")
    if name == "execle":
        return os.execle(str(executable), "claude", "safe-argument", env)
    if name == "execlpe":
        return os.execlpe("claude", "claude", "safe-argument", env)
    if name in {"posix_spawn", "posix_spawnp"}:
        file = str(executable) if name == "posix_spawn" else "claude"
        return getattr(os, name)(file, argv, env)
    raise AssertionError(f"unexpected exec API: {name}")


def test_popen_guard_blocks_temporary_executable_named_claude(tmp_path, monkeypatch):
    executable, marker = _fake_claude(tmp_path)
    log = tmp_path / "guard.log"
    monkeypatch.setenv("TOOLBOX_TEST_GUARD_LOG", str(log))
    monkeypatch.setenv("PATH", os.pathsep.join([str(tmp_path), "/usr/bin", "/bin"]))
    restore = install_ai_cli_guard()
    try:
        with pytest.raises(RuntimeError, match="test isolation guard"):
            subprocess.Popen(["claude"], env={"PATH": os.environ["PATH"]})
    finally:
        restore()

    assert not marker.exists()
    assert log.read_text().splitlines() == ["subprocess.real_ai_cli"]
    assert executable.is_file()


@pytest.mark.parametrize("name", EXEC_APIS)
def test_exec_family_guard_rejects_fake_claude_before_reaching_os(tmp_path, monkeypatch, name):
    executable, marker = _fake_claude(tmp_path)
    log = tmp_path / f"{name}.guard.log"
    monkeypatch.setenv("TOOLBOX_TEST_GUARD_LOG", str(log))
    monkeypatch.setenv("PATH", os.pathsep.join([str(tmp_path), "/usr/bin", "/bin"]))
    called = []

    def safe_original(*args, **kwargs):
        called.append((args, kwargs))
        return 0

    monkeypatch.setattr(os, name, safe_original)
    restore = install_ai_cli_guard()
    try:
        with pytest.raises(RuntimeError, match="test isolation guard"):
            _call_exec_api(name, executable, tmp_path)
    finally:
        restore()

    assert called == []
    assert not marker.exists()
    records = log.read_text().splitlines()
    assert len(records) == 1
    assert "real_ai_cli" in records[0]


@pytest.mark.asyncio
async def test_supervisor_guard_rejects_fake_claude_before_process_identity_probe(
    tmp_path, monkeypatch
):
    executable, marker = _fake_claude(tmp_path)
    log = tmp_path / "supervisor.guard.log"
    monkeypatch.setenv("TOOLBOX_TEST_GUARD_LOG", str(log))
    restore = install_ai_cli_guard()
    try:
        with pytest.raises(RuntimeError, match="start_failed"):
            await SupervisedProcess.start(
                [str(executable)], str(tmp_path), path_extras=[]
            )
    finally:
        restore()

    assert not marker.exists()
    records = log.read_text().splitlines()
    assert len(records) == 1
    assert "real_ai_cli" in records[0]
