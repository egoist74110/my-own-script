"""Real process supervision with Python stand-ins, never a browser or VPN client.

Sandbox-denied identity/process-group operations are reported as not_run skips.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys

import pytest

from tests.test_vpn_lifecycle_s8b import Client
from toolbox_backend.adapters.ai_process import SupervisedProcess, child_environment
from toolbox_backend.adapters.vpn_browser import ChromeRegistry, ProcessLoginRunner, inspect_process
from toolbox_backend.domain.vpn import VpnConfig

WORKER = """import json, os, signal, subprocess, sys, time
options = json.loads(sys.stdin.readline())
mode = sys.argv[1]
if mode != "normal":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if mode == "grandchild":
    profile = options["data_dir"] + "/vpn/chrome-profile"
    child = subprocess.Popen([sys.executable, "-c",
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(600)",
        "--user-data-dir=" + profile], start_new_session=True)
    start = subprocess.run(["/bin/ps", "-p", str(child.pid), "-o", "lstart="],
                           capture_output=True, text=True, timeout=2).stdout
    print(json.dumps({"event":"chrome_started", "pid":child.pid,
                      "lstart":" ".join(start.split())}), flush=True)
print(json.dumps({"event":"step", "step":"workspace"}), flush=True)
while True:
    time.sleep(.1)
"""


@pytest.fixture(scope="module")
def process_metadata():
    try:
        probe = subprocess.run(
            ["/bin/ps", "-p", str(os.getpid()), "-o", "lstart="],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except PermissionError:
        pytest.skip("not_run: sandbox denied /bin/ps process identity")
    if probe.returncode and "permitted" in probe.stderr.lower():
        pytest.skip("not_run: sandbox denied /bin/ps process identity")
    assert probe.returncode == 0 and probe.stdout.strip()


async def wait_gone(pid, timeout=5):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await inspect_process(pid) is None:
            return
        await asyncio.sleep(0.1)
    pytest.fail(f"test-owned PID {pid} remains after cleanup")


@pytest.mark.parametrize("mode", ["normal", "ignore_term", "grandchild"])
async def test_supervised_worker_cancel_and_separate_group_fallback(
    tmp_path, process_metadata, mode
):
    script = tmp_path / "fake_worker.py"
    script.write_text(WORKER)
    started, cancel = asyncio.Event(), asyncio.Event()
    identities, owners = [], []

    async def factory(argv, cwd, **kwargs):
        try:
            owner = await SupervisedProcess.start(
                [sys.executable, str(script), mode], cwd, **kwargs
            )
        except RuntimeError as exc:
            if "PermissionError" in str(exc):
                pytest.skip("not_run: sandbox denied supervised process group")
            raise
        owners.append(owner)
        identity = await inspect_process(owner.identity["pid"])
        identities.append(identity)
        return owner

    registry = ChromeRegistry(tmp_path)
    runner = ProcessLoginRunner(
        tmp_path,
        Client(),
        process_factory=factory,
        registry=registry,
        on_event=lambda event: started.set(),
    )
    task = asyncio.create_task(runner.run(VpnConfig(), "S8_FAKE_PASSWORD", None, cancel, None))
    try:
        ready = asyncio.create_task(started.wait())
        done, _ = await asyncio.wait([ready, task], timeout=5, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
        assert ready in done
        identities.extend([await inspect_process(item["pid"]) for item in registry.records])
        cancel.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        for identity in identities:
            assert identity is not None
            await wait_gone(identity["pid"])
        assert owners[0].proc.returncode is not None
        assert registry.records == []
    finally:
        ready.cancel()
        await asyncio.gather(ready, return_exceptions=True)
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        # Only test-recorded, still-matching process groups may be reclaimed on assertion failure.
        for identity in identities:
            if identity:
                row = await inspect_process(identity["pid"])
                if row and row["lstart"] == identity["lstart"] and row["pgid"] == row["pid"]:
                    try:
                        os.killpg(row["pid"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass


BACKEND = """import asyncio, json, sys
from pathlib import Path
from types import SimpleNamespace
from toolbox_backend.adapters.ai_process import SupervisedProcess
from toolbox_backend.adapters.vpn_browser import ProcessLoginRunner
from toolbox_backend.domain.vpn import VpnConfig
class Client:
    def resolve(self, bundle):
        return SimpleNamespace(app_path="/fake/client.app")
async def main():
    async def factory(argv, cwd, **kwargs):
        owner = await SupervisedProcess.start([sys.executable, sys.argv[1], "grandchild"], cwd, **kwargs)
        print(json.dumps(owner.identity), flush=True)
        return owner
    runner = ProcessLoginRunner(Path(sys.argv[2]), Client(), process_factory=factory)
    await runner.run(VpnConfig(), "S8_FAKE_PASSWORD", None, asyncio.Event(), None)
asyncio.run(main())
"""


async def test_backend_sigkill_control_eof_and_next_startup_reclaims_recorded_group(
    tmp_path, process_metadata
):
    worker_script, backend_script = tmp_path / "fake_worker.py", tmp_path / "fake_backend.py"
    worker_script.write_text(WORKER)
    backend_script.write_text(BACKEND)
    backend = await asyncio.create_subprocess_exec(
        sys.executable,
        str(backend_script),
        str(worker_script),
        str(tmp_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=child_environment(path_extras=[]),
    )
    identities = []
    try:
        raw = await asyncio.wait_for(backend.stdout.readline(), 5)
        if not raw:
            error = (await backend.stderr.read()).decode()
            if "PermissionError" in error:
                pytest.skip("not_run: sandbox denied supervised process group")
            pytest.fail("fake backend failed before worker identity")
        worker = json.loads(raw)
        identities.append(await inspect_process(worker["pid"]))
        journal = tmp_path / "vpn/chrome-processes.json"
        async with asyncio.timeout(5):
            while not journal.exists() or not json.loads(journal.read_text()):  # noqa: ASYNC110
                await asyncio.sleep(0.05)
        recorded = json.loads(journal.read_text())
        identities.extend([await inspect_process(item["pid"]) for item in recorded])
        backend.kill()
        await asyncio.wait_for(backend.wait(), 2)
        # A new backend instance uses the durable, token-free identity journal.
        runner = ProcessLoginRunner(tmp_path, Client())
        await runner.initialize()
        for identity in identities:
            assert identity is not None
            await wait_gone(identity["pid"])
        assert json.loads(journal.read_text()) == []
    finally:
        if backend.returncode is None:
            backend.kill()
            await backend.wait()
        for identity in identities:
            if identity:
                row = await inspect_process(identity["pid"])
                if row and row["lstart"] == identity["lstart"] and row["pgid"] == row["pid"]:
                    try:
                        os.killpg(row["pid"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass
