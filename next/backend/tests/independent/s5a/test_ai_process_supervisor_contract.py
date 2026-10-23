"""Offline lifecycle contracts for the S5-A child supervisor."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pty
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from toolbox_backend.adapters.ai_process import SupervisedProcess

FAKE_CLI = Path(__file__).resolve().parents[2] / "fixtures" / "fake_cli" / "fake.py"
BACKEND_DIR = Path(__file__).resolve().parents[3]


def _read_pid_file(path: Path, expected: int, timeout: float = 3.0) -> list[int]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            values = [int(line) for line in path.read_text().splitlines()]
        except FileNotFoundError:
            values = []
        if len(values) >= expected:
            return values
        time.sleep(0.02)
    return values


def _pid_running(pid: int) -> bool:
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "stat="],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    state = result.stdout.strip()
    return bool(state) and not state.startswith("Z")


def _wait_pids_gone(pids: list[int], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_pid_running(pid) for pid in pids):
            return True
        time.sleep(0.03)
    return not any(_pid_running(pid) for pid in pids)


async def _read_pty_until(fd: int, marker: bytes, timeout: float = 4.0) -> bytes:
    deadline = asyncio.get_running_loop().time() + timeout
    chunks = bytearray()
    while marker not in chunks and asyncio.get_running_loop().time() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.05)
        if readable:
            try:
                chunks.extend(os.read(fd, 4096))
            except OSError:
                break
        else:
            await asyncio.sleep(0.01)
    return bytes(chunks)


@pytest.mark.asyncio
async def test_pipe_supervisor_owns_independent_process_group_and_reaps_normal_exit(tmp_path):
    owner = await SupervisedProcess.start(
        [sys.executable, str(FAKE_CLI), "--version"],
        str(tmp_path),
        path_extras=[],
    )
    try:
        identity = owner.identity
        assert identity["pid"] > 0
        assert identity["pgid"] == identity["pid"]
        assert identity["proc_start_time"]
        assert identity["executable"]
        assert owner.proc.stdout is not None
        output = await asyncio.wait_for(owner.proc.stdout.readline(), timeout=3)
        assert output.strip() == b"toolbox-fake-ai 1.0"
        assert await asyncio.wait_for(owner.proc.wait(), timeout=3) == 0
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_pipe_stop_kills_term_ignoring_cli_and_grandchild(tmp_path):
    pid_file = tmp_path / "pids.txt"
    owner = await SupervisedProcess.start(
        [
            sys.executable,
            str(FAKE_CLI),
            "--ignore-term",
            "--grandchild",
            "--pid-file",
            str(pid_file),
        ],
        str(tmp_path),
        path_extras=[],
    )
    pids = _read_pid_file(pid_file, 2)
    assert len(pids) == 2
    try:
        owner.stop()
        await asyncio.wait_for(owner.proc.wait(), timeout=4.8)
        assert all(not _pid_running(pid) for pid in pids)
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_start_reports_chdir_failure_without_launching_cli(tmp_path):
    pid_file = tmp_path / "must-not-exist.txt"

    with pytest.raises(RuntimeError, match="start_failed"):
        await SupervisedProcess.start(
            [sys.executable, str(FAKE_CLI), "--pid-file", str(pid_file)],
            str(tmp_path / "missing-cwd"),
            path_extras=[],
        )

    assert not pid_file.exists()


@pytest.mark.asyncio
async def test_pty_supervisor_attaches_controlling_terminal_and_echoes_input(tmp_path):
    master, slave = pty.openpty()
    owner = None
    pid_file = tmp_path / "pty-pid.txt"
    try:
        owner = await SupervisedProcess.start(
            [
                sys.executable,
                str(FAKE_CLI),
                "--echo",
                "--pid-file",
                str(pid_file),
            ],
            str(tmp_path),
            slave=slave,
            path_extras=[],
        )
        os.close(slave)
        slave = -1
        identity = owner.identity
        assert identity["pgid"] == identity["pid"]
        # macOS ps has no `sid` keyword; os.getsid is the portable session-id query.
        assert os.getsid(identity["pid"]) == identity["pid"]
        assert os.tcgetpgrp(master) == identity["pgid"]

        ready = await _read_pty_until(master, b"ready")
        assert b"ready" in ready
        os.write(master, b"terminal-input\n")
        echoed = await _read_pty_until(master, b"echo:terminal-input\r\n")
        assert b"echo:terminal-input\r\n" in echoed
    finally:
        if owner is not None:
            await owner.close()
        if slave >= 0:
            os.close(slave)
        os.close(master)


@pytest.mark.asyncio
async def test_control_writer_sigkill_reaps_cli_process_group(tmp_path):
    pid_file = tmp_path / "orphan-check-pids.txt"
    payload = {
        "argv": [
            sys.executable,
            str(FAKE_CLI),
            "--ignore-term",
            "--grandchild",
            "--pid-file",
            str(pid_file),
        ],
        "cwd": str(tmp_path),
    }
    helper_code = r"""
import asyncio, json, sys
from toolbox_backend.adapters.ai_process import SupervisedProcess

async def main():
    data = json.loads(sys.argv[1])
    owner = await SupervisedProcess.start(data["argv"], data["cwd"], path_extras=[])
    print(json.dumps({"supervisor_pid": owner.proc.pid, "identity": owner.identity}), flush=True)
    await asyncio.Event().wait()

asyncio.run(main())
"""
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path / ".config"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    helper = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        helper_code,
        json.dumps(payload),
        cwd=BACKEND_DIR,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    supervisor_pid = None
    child_pids: list[int] = []
    try:
        assert helper.stdout is not None
        line = await asyncio.wait_for(helper.stdout.readline(), timeout=8)
        assert line, "controller did not report supervisor startup"
        record = json.loads(line)
        supervisor_pid = record["supervisor_pid"]
        child_pids = _read_pid_file(pid_file, 2)
        assert len(child_pids) == 2

        helper.kill()
        await asyncio.wait_for(helper.wait(), timeout=5)
        assert await asyncio.to_thread(_wait_pids_gone, [supervisor_pid, *child_pids], 5)
    finally:
        if helper.returncode is None:
            helper.kill()
            await asyncio.wait_for(helper.wait(), timeout=5)
        if supervisor_pid and _pid_running(supervisor_pid):
            with contextlib.suppress(ProcessLookupError):
                os.kill(supervisor_pid, signal.SIGTERM)
        if child_pids and any(_pid_running(pid) for pid in child_pids):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child_pids[0], signal.SIGKILL)
