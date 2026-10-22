import asyncio
import fcntl
import os
import subprocess
import sys

import pytest

from toolbox_backend.adapters.task_git import SUPERVISOR, GitAdapter, GitFailure


@pytest.fixture
def repository(tmp_path):
    adapter = GitAdapter(
        tmp_path / "data",
        test_remote_root=tmp_path,
        forbidden_roots=("/Users/wesker/my-own-script", "/Users/wesker/my-own-script-next"),
    )
    env = adapter.environment()
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "Fake Test"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "fake@example.test"

    def git(cwd, *args):
        assert cwd.resolve().is_relative_to(tmp_path.resolve())
        result = subprocess.run(
            [adapter.executable, "-c", "core.hooksPath=/dev/null", *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    remote, local = tmp_path / "remote.git", tmp_path / "local"
    git(tmp_path, "init", "--bare", str(remote))
    git(tmp_path, "init", "-b", "main", str(local))
    git(local, "config", "user.name", "Fake Test")
    git(local, "config", "user.email", "fake@example.test")
    (local / "file").write_text("base\n")
    git(local, "add", "file")
    git(local, "commit", "-m", "initial")
    git(local, "remote", "add", "origin", str(remote))
    git(local, "push", "origin", "main")
    git(local, "checkout", "-b", "source")
    (local / "new").write_text("new\n")
    git(local, "add", "new")
    git(local, "commit", "-m", "source")
    git(local, "push", "origin", "source")
    git(local, "checkout", "main")
    return adapter, local, remote, git


class Context:
    def __init__(self):
        self.cancelled = asyncio.Event()
        self.effects = []
        self.receipts = []
        self.checkpoints = []

    async def checkpoint(self, kind, data):
        self.checkpoints.append((kind, data))

    async def intent(self, kind, data):
        self.effects.append((kind, data))
        return len(self.effects)

    async def receipt(self, effect, state):
        self.receipts.append((effect, state))


async def test_merge_push_exact_build_branch_commit_and_checkout_restore(repository):
    adapter, local, remote, git = repository
    context = Context()
    original_remote = git(remote, "rev-parse", "main")
    task = {
        "local_repo_path": str(local),
        "git_flow": {
            "build_branch": "main",
            "update_branches": ["main"],
            "merges": [{"source": "source", "target": "main"}],
            "push_branches": ["main"],
        },
    }
    git(local, "checkout", "source")
    result = await adapter.execute(task, context)
    assert result == git(remote, "rev-parse", "refs/heads/main")
    assert result == git(local, "rev-parse", "refs/heads/main")
    assert git(local, "branch", "--show-current") == "source"
    assert context.effects == [
        (
            "git_push",
            {"branch": "main", "commit": result, "previous_remote_commit": original_remote},
        )
    ]
    assert context.receipts == [(1, "confirmed")]
    assert context.checkpoints[0][1]["original_refs"]["refs/heads/main"] == original_remote
    assert context.checkpoints[-1][1]["expected_commit"] == result


async def test_preflight_is_read_only_and_rejects_dirty_worktree(repository):
    adapter, local, remote, git = repository
    before = git(local, "show-ref")
    assert (await adapter.preflight(local))["root"] == str(local.resolve())
    assert git(local, "show-ref") == before
    (local / "file").write_text("dirty")
    from toolbox_backend.domain.errors import SettingsError

    with pytest.raises(SettingsError) as exc:
        await adapter.preflight(local)
    assert exc.value.code == "unsafe_repository"


async def test_explicit_fetch_can_refresh_rewritten_remote_tracking_ref(repository):
    adapter, local, remote, git = repository
    original_local = git(local, "rev-parse", "refs/heads/main")
    before = git(local, "rev-parse", "refs/remotes/origin/source")
    git(remote, "update-ref", "refs/heads/source", original_local)
    assert before != original_local
    await adapter.execute(
        {
            "local_repo_path": str(local),
            "git_flow": {
                "build_branch": "main",
                "update_branches": [],
                "merges": [{"source": "source", "target": "main"}],
                "push_branches": [],
            },
        },
        Context(),
    )
    assert git(local, "rev-parse", "refs/remotes/origin/source") == original_local
    assert git(local, "rev-parse", "refs/heads/main") == original_local


async def test_dirty_and_non_file_origin_are_rejected_before_fetch(repository):
    adapter, local, _, git = repository
    info = await adapter.inspect(str(local))
    context = Context()
    (local / "file").write_text("dirty")
    async with adapter.locked(info, context.cancelled) as fd:
        with pytest.raises(GitFailure) as exc:
            await adapter.check(str(local), fd)
    assert exc.value.code == "unsafe_repository"
    (local / "file").write_text("base\n")
    git(local, "remote", "set-url", "origin", "ssh://git@real.example.test/repo")
    async with adapter.locked(info, context.cancelled) as fd:
        with pytest.raises(GitFailure):
            await adapter.check(str(local), fd)


async def test_merge_conflict_aborts_without_hard_reset(repository):
    adapter, local, _, git = repository
    git(local, "checkout", "source")
    (local / "file").write_text("source conflict\n")
    git(local, "commit", "-am", "source conflict")
    git(local, "push", "origin", "source")
    git(local, "checkout", "main")
    (local / "file").write_text("main conflict\n")
    git(local, "commit", "-am", "main conflict")
    old = git(local, "rev-parse", "HEAD")
    with pytest.raises(GitFailure):
        await adapter.execute(
            {
                "local_repo_path": str(local),
                "git_flow": {
                    "build_branch": "main",
                    "update_branches": [],
                    "merges": [{"source": "source", "target": "main"}],
                    "push_branches": [],
                },
            },
            Context(),
        )
    assert git(local, "rev-parse", "HEAD") == old
    assert git(local, "status", "--porcelain") == ""
    assert not (local / ".git/MERGE_HEAD").exists()


def test_environment_drops_credentials_and_protocol_backdoors(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PAT", "must-not-pass")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "9")
    monkeypatch.setenv("HTTPS_PROXY", "https://unsafe.test")
    env = GitAdapter(tmp_path).environment()
    assert "FAKE_PAT" not in env and "HTTPS_PROXY" not in env and "GIT_CONFIG_COUNT" not in env
    assert env["GIT_ALLOW_PROTOCOL"] == "ssh"
    assert env["HOME"] != os.environ.get("HOME")


@pytest.mark.parametrize(
    "key,value",
    [
        ("remote.origin.vcs", "untrusted-helper"),
        ("merge.untrusted.driver", "untrusted-helper"),
        ("branch.main.mergeoptions", "--strategy=untrusted"),
        ("diff.untrusted.command", "untrusted-helper"),
    ],
)
async def test_command_config_is_rejected_before_remote_access(repository, key, value):
    adapter, local, _, git = repository
    git(local, "config", key, value)
    info = await adapter.inspect(local)
    async with adapter.locked(info, asyncio.Event()) as fds:
        with pytest.raises(GitFailure) as exc:
            await adapter.check(str(local), fds)
    assert exc.value.code == "unsafe_repository"


async def test_supervisor_keeps_all_locks_until_owned_child_exits(tmp_path):
    paths = [tmp_path / "root.lock", tmp_path / "common.lock"]
    fds = [os.open(p, os.O_CREAT | os.O_RDWR, 0o600) for p in paths]
    for fd in fds:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    read_fd, write_fd = os.pipe()
    marker = tmp_path / "child.pid"
    code = (
        "import os,signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(15)"
    )
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            SUPERVISOR,
            str(read_fd),
            ",".join(map(str, fds)),
            sys.executable,
            "-I",
            "-c",
            code,
            pass_fds=(read_fd, *fds),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        os.close(read_fd)
        read_fd = None
        for _ in range(100):
            if marker.exists() or proc.returncode is not None:
                break
            await asyncio.sleep(0.01)
        assert marker.exists(), "supervised child did not start"
        for fd in fds:
            os.close(fd)
        fds.clear()
        os.close(write_fd)  # Simulate backend death: EOF and all backend lock copies close.
        write_fd = None
        await asyncio.sleep(0.1)
        for path in paths:
            probe = os.open(path, os.O_RDWR)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(probe)
        await asyncio.wait_for(proc.wait(), 7)
        for path in paths:
            probe = os.open(path, os.O_RDWR)
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(probe)
    finally:
        if write_fd is not None:
            os.close(write_fd)
        if read_fd is not None:
            os.close(read_fd)
        for fd in fds:
            os.close(fd)
        if proc:
            await asyncio.wait_for(proc.wait(), 8)


async def test_output_sink_failure_stops_owned_process_instead_of_pipe_deadlock(tmp_path):
    from toolbox_backend.domain.errors import SettingsError

    executable = tmp_path / "fake_git.py"
    executable.write_text(
        f"#!{sys.executable}\nimport sys\n"
        'while True:\n sys.stdout.write("x"*4096); sys.stdout.flush()\n'
    )
    executable.chmod(0o700)
    adapter = GitAdapter(tmp_path / "data", test_remote_root=tmp_path)
    adapter.executable = str(executable)

    async def failed_sink(text, **kwargs):
        raise SettingsError("run_store_unavailable", "injected", 503)

    with pytest.raises(SettingsError) as exc:
        await asyncio.wait_for(adapter.command(tmp_path, ["status"], output=failed_sink), 2)
    assert exc.value.code == "run_store_unavailable"


async def test_late_output_journal_failure_cannot_report_command_success(tmp_path):
    from toolbox_backend.domain.errors import SettingsError

    adapter = GitAdapter(tmp_path / "data", test_remote_root=tmp_path)

    async def failed_sink(text, **kwargs):
        await asyncio.sleep(0.1)
        raise SettingsError("run_store_unavailable", "injected", 503)

    with pytest.raises(SettingsError):
        await adapter.command(tmp_path, ["--version"], output=failed_sink)


async def test_backend_sigkill_keeps_common_lock_and_supervisor_reaps_child(tmp_path):
    import contextlib
    import signal

    marker, ready = tmp_path / "child.pid", tmp_path / "supervisor.pid"
    lock = tmp_path / "common.lock"
    child_code = (
        "import os,signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(20)"
    )
    controller = (
        "import os,fcntl,subprocess,sys,time; from pathlib import Path; "
        f"fd=os.open({str(lock)!r},os.O_CREAT|os.O_RDWR,0o600); "
        "fcntl.flock(fd,fcntl.LOCK_EX); r,w=os.pipe(); "
        f'p=subprocess.Popen([sys.executable,"-I",{SUPERVISOR!r},str(r),str(fd),'
        f'sys.executable,"-I","-c",{child_code!r}],pass_fds=(r,fd),'
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        f"Path({str(ready)!r}).write_text(str(p.pid)); time.sleep(30)"
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-c",
        controller,
        env=GitAdapter(tmp_path / "data", test_remote_root=tmp_path).environment(),
    )
    child_pid = None

    def alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

    try:
        for _ in range(100):
            if marker.exists():
                break
            await asyncio.sleep(0.01)
        assert marker.exists() and ready.exists()
        child_pid = int(marker.read_text())
        proc.kill()  # Exact owned controller PID, never a process-name kill.
        await proc.wait()
        probe = os.open(lock, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(probe)
        for _ in range(140):
            if not alive(child_pid):
                break
            await asyncio.sleep(0.05)
        assert not alive(child_pid)
        probe = os.open(lock, os.O_RDWR)
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(probe)
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        if child_pid and alive(child_pid):
            with contextlib.suppress(ProcessLookupError):
                os.kill(child_pid, signal.SIGKILL)


async def test_partial_push_keeps_first_remote_ref_and_marks_second_unknown(
    repository, monkeypatch
):
    adapter, local, remote, git = repository
    old = git(remote, "rev-parse", "main")
    command = adapter.command

    async def fail_second(path, args, **kwargs):
        if args[0] == "push" and args[-1] == "refs/heads/source:refs/heads/source":
            raise GitFailure()
        return await command(path, args, **kwargs)

    monkeypatch.setattr(adapter, "command", fail_second)
    context = Context()
    with pytest.raises(GitFailure) as exc:
        await adapter.execute(
            {
                "local_repo_path": str(local),
                "git_flow": {
                    "build_branch": "main",
                    "update_branches": [],
                    "merges": [{"source": "source", "target": "main"}],
                    "push_branches": ["main", "source"],
                },
            },
            context,
        )
    assert exc.value.unknown
    assert context.receipts == [(1, "confirmed"), (2, "unknown")]
    assert git(remote, "rev-parse", "main") != old
    assert git(local, "rev-parse", "main") == git(remote, "rev-parse", "main")


async def test_explicit_origin_ignores_wrong_upstream_and_uses_build_ref(repository):
    adapter, local, remote, git = repository
    git(local, "config", "branch.source.remote", "wrong-upstream")
    git(local, "config", "branch.source.merge", "refs/heads/not-source")
    expected = git(remote, "rev-parse", "main")
    result = await adapter.execute(
        {
            "local_repo_path": str(local),
            "git_flow": {
                "build_branch": "main",
                "update_branches": ["source"],
                "merges": [],
                "push_branches": [],
            },
        },
        Context(),
    )
    assert result == expected
    assert result != git(local, "rev-parse", "source")


async def test_shared_common_dir_and_symlink_alias_use_same_repository_mutex(repository):
    adapter, local, _, git = repository
    worktree = local.parent / "other-worktree"
    git(local, "worktree", "add", "-b", "other-worktree", str(worktree), "main")
    alias = local.parent / "alias"
    alias.symlink_to(local, target_is_directory=True)
    first = await adapter.inspect(local)
    assert (await adapter.inspect(alias))["lock_keys"] == first["lock_keys"]
    second = await adapter.inspect(worktree)
    assert first["common_dir"] == second["common_dir"]
    adapter.lock_timeout = 0.01
    async with adapter.locked(first, asyncio.Event()):
        with pytest.raises(GitFailure) as exc:
            async with adapter.locked(second, asyncio.Event()):
                pytest.fail("shared common-dir lock was bypassed")
    assert exc.value.code == "busy"


async def test_two_clones_non_fast_forward_push_never_forces_or_resets(repository):
    adapter, local, remote, git = repository
    other = local.parent / "second-clone"
    git(local.parent, "clone", "-b", "main", str(remote), str(other))
    git(other, "config", "user.name", "Fake Other")
    git(other, "config", "user.email", "fake-other@example.test")
    (other / "second").write_text("second clone\n")
    git(other, "add", "second")
    git(other, "commit", "-m", "advance remote")
    git(other, "push", "origin", "main")
    old, advanced = git(local, "rev-parse", "main"), git(remote, "rev-parse", "main")
    context = Context()
    with pytest.raises(GitFailure):
        await adapter.execute(
            {
                "local_repo_path": str(local),
                "git_flow": {
                    "build_branch": "main",
                    "update_branches": [],
                    "merges": [],
                    "push_branches": ["main"],
                },
            },
            context,
        )
    assert git(local, "rev-parse", "main") == old
    assert git(remote, "rev-parse", "main") == advanced
    assert context.receipts == [(1, "unknown")]


@pytest.mark.parametrize("mode", ["cancel", "timeout"])
async def test_git_cancel_and_timeout_reap_exact_owned_process(tmp_path, mode, monkeypatch):
    import contextlib
    import signal

    marker = tmp_path / "owned.pid"
    executable = tmp_path / "fake_git.py"
    executable.write_text(
        f"#!{sys.executable}\nimport os,signal,time\nfrom pathlib import Path\n"
        + ("signal.signal(signal.SIGTERM,signal.SIG_IGN)\n" if mode == "timeout" else "")
        + f"Path({str(marker)!r}).write_text(str(os.getpid()))\ntime.sleep(20)\n"
    )
    executable.chmod(0o700)
    adapter = GitAdapter(tmp_path / "data", test_remote_root=tmp_path)
    adapter.executable = str(executable)
    adapter.command_timeout = 0.1 if mode == "timeout" else 5
    # Isolate deadline/TERM/KILL from Python cold-start latency: process creation only
    # returns after the test actor has installed its signal handler and published its PID.
    spawn = asyncio.create_subprocess_exec
    ready = asyncio.Event()

    async def ready_spawn(*args, **kwargs):
        proc = await spawn(*args, **kwargs)
        for _ in range(200):
            if marker.exists():
                ready.set()
                break
            await asyncio.sleep(0.01)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", ready_spawn)
    cancelled = asyncio.Event()
    task = asyncio.create_task(adapter.command(tmp_path, ["status"], cancel=cancelled))
    pid = None
    try:
        await asyncio.wait_for(ready.wait(), 2)
        assert marker.exists()
        pid = int(marker.read_text())
        if mode == "cancel":
            cancelled.set()
        with pytest.raises(GitFailure) as exc:
            await asyncio.wait_for(asyncio.shield(task), 7)
        assert exc.value.code == ("cancelled" if mode == "cancel" else "timeout")
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        pid = None
    finally:
        cancelled.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if pid:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
