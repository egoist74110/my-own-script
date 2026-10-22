"""Fixed-argv Git boundary. Local file remotes require constructor-only test injection."""

import asyncio
import contextlib
import fcntl
import hashlib
import os
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from toolbox_backend.adapters.config_store import private_dir
from toolbox_backend.adapters.run_log import StreamRedactor
from toolbox_backend.adapters.run_store import secure_open
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.services.tasks import branch

SUPERVISOR = str(Path(__file__).with_name("git_process.py"))


class GitFailure(Exception):
    def __init__(self, code="git_failed", unknown=False):
        self.code = code
        self.unknown = unknown
        super().__init__(code)


class GitAdapter:
    def __init__(self, data_dir, *, test_remote_root=None, forbidden_roots=None):
        self.data_dir = Path(data_dir)
        self.test_remote_root = Path(test_remote_root).resolve() if test_remote_root else None
        self.forbidden_roots = tuple(
            Path(p).resolve()
            for p in (
                forbidden_roots
                or ("/Users/wesker/my-own-script", "/Users/wesker/my-own-script-next")
            )
        )
        self.executable = shutil.which("git") or "/usr/bin/git"
        self.command_timeout = 300
        self.lock_timeout = 300

    def environment(self):
        env = {
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(self.data_dir / "git-home"),
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "/usr/bin/false",
            "SSH_ASKPASS": "/usr/bin/false",
            "GIT_ALLOW_PROTOCOL": "ssh",
            "GIT_SSH_COMMAND": "ssh -F /dev/null -o BatchMode=yes "
            "-o StrictHostKeyChecking=yes -o ConnectTimeout=10 "
            "-o PermitLocalCommand=no -o ProxyCommand=none -o ProxyJump=none "
            "-o IdentityFile=none -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no",
            "GIT_SSH_VARIANT": "ssh",
        }
        if self.test_remote_root:
            env["GIT_ALLOW_PROTOCOL"] = "file"
        elif os.environ.get("SSH_AUTH_SOCK"):
            env["SSH_AUTH_SOCK"] = os.environ["SSH_AUTH_SOCK"]
        return env

    async def command(self, path, args, *, lock_fd=None, cancel=None, output=None):
        argv = [
            self.executable,
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.sshCommand=" + self.environment()["GIT_SSH_COMMAND"],
            "-c",
            "credential.helper=",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "push.gpgSign=false",
            "-c",
            "merge.gpgSign=false",
            "-c",
            "protocol.ext.allow=never",
            "-c",
            "submodule.recurse=false",
            "-c",
            "diff.external=",
            "-c",
            "core.pager=cat",
            *args,
        ]
        owned_fd = None
        if lock_fd is None:
            private_dir(self.data_dir / "locks")
            owned_fd = lock_fd = secure_open(self.data_dir / "locks" / "inspection.lock")
        lock_fds = (lock_fd,) if isinstance(lock_fd, int) else tuple(lock_fd)
        read_fd, write_fd = os.pipe()
        proc = None
        chunks = bytearray()
        sink_failed = asyncio.Event()
        sink_errors = []
        finishing = False

        async def drain(stream, capture):
            redactor = StreamRedactor()
            while block := await stream.read(4096):
                if capture and len(chunks) < 1024 * 1024:
                    chunks.extend(block[: 1024 * 1024 - len(chunks)])
                if output and not sink_errors and not finishing:
                    try:
                        await output("", raw_bytes=len(block))
                        for text in redactor.feed(block):
                            await output(text, raw_bytes=0)
                    except Exception as exc:
                        sink_errors.append(exc)
                        sink_failed.set()
            if output and not sink_errors and not finishing:
                try:
                    for text in redactor.finish():
                        await output(text, raw_bytes=0)
                except Exception as exc:
                    sink_errors.append(exc)
                    sink_failed.set()

        waiters = []
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                SUPERVISOR,
                str(read_fd),
                ",".join(map(str, lock_fds)),
                *argv,
                cwd=path,
                env=self.environment(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                pass_fds=(read_fd, *lock_fds),
            )
            os.close(read_fd)
            read_fd = None
            drains = [
                asyncio.create_task(drain(proc.stdout, True)),
                asyncio.create_task(drain(proc.stderr, False)),
            ]
            waiters = drains + [
                asyncio.create_task(proc.wait()),
                asyncio.create_task(sink_failed.wait()),
            ]
            stop = asyncio.create_task(cancel.wait()) if cancel else None
            if stop:
                waiters.append(stop)
            done, _ = await asyncio.wait(
                waiters[2:], timeout=self.command_timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if not done or (stop and stop in done):
                raise GitFailure("cancelled" if stop and stop in done else "timeout")
            if sink_errors:
                raise sink_errors[0]
            await asyncio.gather(*drains)
            if sink_errors:
                raise sink_errors[0]
            if proc.returncode:
                raise GitFailure()
            return chunks.decode("utf-8", errors="replace").strip()
        finally:
            finishing = True
            os.close(write_fd)  # EOF asks supervisor to terminate and reap its group.
            if proc:
                await asyncio.gather(*waiters[:2], return_exceptions=True)
                await asyncio.shield(proc.wait())
            for task in waiters:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
            if read_fd is not None:
                os.close(read_fd)
            if owned_fd is not None:
                os.close(owned_fd)

    def safe_path(self, path):
        path = Path(path).resolve()
        if (
            not path.is_absolute()
            or not path.is_dir()
            or any(path == root or path.is_relative_to(root) for root in self.forbidden_roots)
        ):
            raise SettingsError("unsafe_repository", "不允许在此目录执行任务")
        return path

    async def inspect(self, path):
        path = await asyncio.to_thread(self.safe_path, path)
        try:
            if await self.command(path, ["rev-parse", "--is-bare-repository"]) != "false":
                raise GitFailure()
            root = await asyncio.to_thread(
                self.safe_path, await self.command(path, ["rev-parse", "--show-toplevel"])
            )
            common = Path(await self.command(path, ["rev-parse", "--git-common-dir"]))
            common = await asyncio.to_thread((path / common).resolve)
            if any(common == p or common.is_relative_to(p) for p in self.forbidden_roots):
                raise GitFailure()
            return dict(
                root=str(root), common_dir=str(common), lock_keys=sorted({str(root), str(common)})
            )
        except GitFailure:
            raise SettingsError("unsafe_repository", "目录必须为受支持的非 bare 工作树") from None

    def remote(self, remote):
        if self.test_remote_root:
            url = urlsplit(remote)
            if url.scheme not in ("", "file") or url.netloc or url.query or url.fragment:
                raise GitFailure("unsafe_repository")
            target = Path(url.path).resolve()
            if not target.is_relative_to(self.test_remote_root) or not (target / "HEAD").is_file():
                raise GitFailure("unsafe_repository")
            return
        # Require an actual DNS name/IP, not an SSH config alias or arbitrary helper.
        user = r"[A-Za-z0-9_][A-Za-z0-9_-]*"
        host = r"[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z0-9.-]+"
        path = r"[A-Za-z0-9_./-]+"
        if (
            not (
                re.fullmatch(rf"{user}@{host}:{path}", remote)
                or re.fullmatch(rf"ssh://{user}@{host}(?::[0-9]{{1,5}})?/{path}", remote)
            )
            or ".." in remote
            or not os.environ.get("SSH_AUTH_SOCK")
        ):
            raise GitFailure("unsupported_task")

    async def check(self, root, fd):
        config = await self.command(
            root, ["config", "--local", "--no-includes", "--list"], lock_fd=fd
        )
        for line in config.splitlines():
            key = line.partition("=")[0].lower()
            if (
                key.startswith(("url.", "include.", "includeif.", "filter.", "extensions."))
                or key
                in {
                    "core.sshcommand",
                    "core.gitproxy",
                    "core.worktree",
                    "core.fsmonitor",
                    "core.hookspath",
                    "ssh.variant",
                }
                or key.startswith("remote.")
                and key not in {"remote.origin.url", "remote.origin.fetch", "remote.origin.pushurl"}
                or key.startswith(("merge.", "diff."))
                and key.endswith((".driver", ".command"))
                or key.startswith("branch.")
                and key.endswith(".mergeoptions")
            ):
                raise GitFailure("unsafe_repository")
        status = await self.command(root, ["status", "--porcelain"], lock_fd=fd)
        if status:
            raise GitFailure("unsafe_repository")
        for marker in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD"):
            location = await self.command(root, ["rev-parse", "--git-path", marker], lock_fd=fd)
            if (Path(root) / location).exists():
                raise GitFailure("unsafe_repository")
        urls = await self.command(root, ["remote", "get-url", "--all", "origin"], lock_fd=fd)
        pushes = await self.command(
            root, ["remote", "get-url", "--push", "--all", "origin"], lock_fd=fd
        )
        if len(urls.splitlines()) != 1 or pushes != urls:
            raise GitFailure("unsafe_repository")
        self.remote(urls)

    @contextlib.asynccontextmanager
    async def locked(self, info, cancel, *, wait_seconds=None):
        if (self.data_dir / "locks").is_symlink():
            raise GitFailure("unsafe_repository")
        private_dir(self.data_dir / "locks")
        fds = []
        deadline = time.monotonic() + (self.lock_timeout if wait_seconds is None else wait_seconds)
        try:
            for key in info["lock_keys"]:
                fd = secure_open(
                    self.data_dir / "locks" / (hashlib.sha256(key.encode()).hexdigest() + ".lock")
                )
                fds.append(fd)
                while True:
                    if cancel.is_set():
                        raise GitFailure("cancelled")
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise GitFailure("busy") from None
                        await asyncio.sleep(0.05)
            yield tuple(fds)
        finally:
            for fd in reversed(fds):
                # Do not LOCK_UN: child copies own the same open-file-description.
                os.close(fd)

    async def preflight(self, path):
        info = await self.inspect(path)
        try:
            async with self.locked(info, asyncio.Event(), wait_seconds=5) as fds:
                await self.check(info["root"], fds)
            return info
        except GitFailure as exc:
            if exc.code == "busy":
                raise SettingsError("busy", "仓库正在使用，请稍后预检", 503) from None
            raise SettingsError(
                exc.code if exc.code == "unsupported_task" else "unsafe_repository",
                "仓库状态或 origin 不受支持；请检查工作区及 SSH agent 配置",
            ) from None

    async def execute(self, task, context):
        info = await self.inspect(task["local_repo_path"])
        flow = task["git_flow"]
        branches = {flow["build_branch"], *flow["update_branches"], *flow["push_branches"]}
        for rule in flow["merges"]:
            branches.update((rule["source"], rule["target"]))
        for value in branches:
            branch(value)
        async with self.locked(info, context.cancelled) as fd:
            root = info["root"]
            await self.check(root, fd)

            async def cmd(*args):
                return await self.command(
                    root,
                    list(args),
                    lock_fd=fd,
                    cancel=context.cancelled,
                    output=getattr(context, "log", None),
                )

            original = await cmd("rev-parse", "--verify", "HEAD")
            symbolic = await cmd("rev-parse", "--abbrev-ref", "HEAD")
            original_refs = {}
            for value in sorted(branches):
                for prefix in ("refs/heads/", "refs/remotes/origin/"):
                    ref = prefix + value
                    try:
                        original_refs[ref] = await cmd("rev-parse", "--verify", ref)
                    except GitFailure:
                        original_refs[ref] = None
            checkpoint = {
                **info,
                "original_head": original,
                "original_branch": symbolic,
                "original_refs": original_refs,
            }
            await context.checkpoint("git", checkpoint)
            new_refs = {}
            merge_started = False
            failed = False
            try:
                async with asyncio.timeout(900):
                    await cmd(
                        "fetch",
                        "--no-tags",
                        "--no-recurse-submodules",
                        "origin",
                        *[f"+refs/heads/{b}:refs/remotes/origin/{b}" for b in sorted(branches)],
                    )
                    for value in sorted(branches):
                        await cmd(
                            "rev-parse", "--verify", f"refs/remotes/origin/{value}^{{commit}}"
                        )
                    for value in flow["update_branches"]:
                        await self.check(root, fd)
                        await cmd("checkout", value)
                        await cmd("merge", "--ff-only", f"refs/remotes/origin/{value}")
                        new_refs["refs/heads/" + value] = await cmd(
                            "rev-parse", "--verify", "refs/heads/" + value
                        )
                        await context.checkpoint("git", {**checkpoint, "new_refs": dict(new_refs)})
                    for rule in flow["merges"]:
                        await self.check(root, fd)
                        await cmd("checkout", rule["target"])
                        merge_started = True
                        await cmd("merge", "--no-edit", f"refs/remotes/origin/{rule['source']}")
                        merge_started = False
                        new_refs["refs/heads/" + rule["target"]] = await cmd(
                            "rev-parse", "--verify", "refs/heads/" + rule["target"]
                        )
                        await context.checkpoint("git", {**checkpoint, "new_refs": dict(new_refs)})
                    for value in flow["push_branches"]:
                        await self.check(root, fd)
                        commit = await cmd(
                            "rev-parse", "--verify", f"refs/heads/{value}^{{commit}}"
                        )
                        effect = await context.intent(
                            "git_push",
                            {
                                "branch": value,
                                "commit": commit,
                                "previous_remote_commit": await cmd(
                                    "rev-parse", "--verify", f"refs/remotes/origin/{value}"
                                ),
                            },
                        )
                        try:
                            await cmd(
                                "push",
                                "--no-verify",
                                "origin",
                                f"refs/heads/{value}:refs/heads/{value}",
                            )
                        except BaseException:
                            await context.receipt(effect, "unknown")
                            raise GitFailure("remote_unknown", unknown=True) from None
                        await context.receipt(effect, "confirmed")
                    commit = await cmd(
                        "rev-parse", "--verify", f"refs/heads/{flow['build_branch']}^{{commit}}"
                    )
                    remote = await cmd(
                        "ls-remote", "--refs", "origin", f"refs/heads/{flow['build_branch']}"
                    )
                    if remote.split() != [commit, f"refs/heads/{flow['build_branch']}"]:
                        raise GitFailure("plan_changed")
                    await context.checkpoint(
                        "git", {**checkpoint, "new_refs": dict(new_refs), "expected_commit": commit}
                    )
                    return commit
            except BaseException:
                failed = True
                if merge_started:
                    try:
                        await self.command(root, ["merge", "--abort"], lock_fd=fd)
                    except GitFailure:
                        raise GitFailure("repo_needs_attention") from None
                raise
            finally:
                try:
                    await self.command(
                        root, ["checkout", original if symbolic == "HEAD" else symbolic], lock_fd=fd
                    )
                except GitFailure:
                    if not failed:
                        raise GitFailure("repo_needs_attention") from None
