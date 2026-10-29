"""Fixed-argv Git boundary. Local file remotes require constructor-only test injection."""

import asyncio
import base64
import contextlib
import fcntl
import hashlib
import os
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

from toolbox_backend.adapters.config_store import private_dir
from toolbox_backend.adapters.run_log import StreamRedactor
from toolbox_backend.adapters.run_store import secure_open
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.logging_setup import register_secret
from toolbox_backend.services.tasks import branch

SUPERVISOR = str(Path(__file__).with_name("git_process.py"))


class GitFailure(Exception):
    def __init__(self, code="git_failed", unknown=False, *, message=None):
        self.code = code
        self.unknown = unknown
        self.message = message or "Git 检查失败；请确认仓库可访问且 Git 安装正常后重试"
        super().__init__(self.message)


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

    async def command(self, path, args, *, lock_fd=None, cancel=None, output=None, pat=None):
        env = self.environment()
        auth_args = []
        secrets = []
        if pat is not None:
            if not pat:
                raise GitFailure("unsupported_task", message="未配置 ADO 库 PAT；请先保存该库凭据")
            encoded = base64.b64encode((":" + pat).encode()).decode()
            header = "Authorization: Basic " + encoded
            secrets = [header, encoded, pat]
            for secret in secrets:
                register_secret(secret)
            env["GIT_ALLOW_PROTOCOL"] = "https"
            auth_args = [
                "-c",
                "http.extraHeader=",
                "-c",
                "http.extraHeader=" + header,
                "-c",
                "http.followRedirects=false",
                "-c",
                "http.sslVerify=true",
            ]

        def redact(text):
            for secret in secrets:
                text = text.replace(secret, "***")
            return text

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
            *auth_args,
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
                            await output(redact(text), raw_bytes=0)
                    except Exception as exc:
                        sink_errors.append(exc)
                        sink_failed.set()
            if output and not sink_errors and not finishing:
                try:
                    for text in redactor.finish():
                        await output(redact(text), raw_bytes=0)
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
                env=env,
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
            return redact(chunks.decode("utf-8", errors="replace").strip())
        except Exception as exc:
            # 启动失败或日志回调异常也可能回显 argv，认证命令不传播原始异常。
            if pat is not None and not isinstance(exc, GitFailure):
                if isinstance(exc, SettingsError):
                    raise SettingsError(exc.code, redact(exc.message), exc.status) from None
                raise GitFailure() from None
            raise
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
            raise SettingsError(
                "unsafe_repository",
                "不是受支持的 git 工作树（可能为 bare 仓库或受保护目录）；请选择普通仓库根目录",
            ) from None

    def remote(self, remote, task=None):
        if self.test_remote_root:
            url = urlsplit(remote)
            if url.scheme not in ("", "file") or url.netloc or url.query or url.fragment:
                raise GitFailure("unsafe_repository")
            target = Path(url.path).resolve()
            if not target.is_relative_to(self.test_remote_root) or not (target / "HEAD").is_file():
                raise GitFailure("unsafe_repository")
            return

        def unsupported(reason):
            raise GitFailure(
                "unsupported_task",
                message="origin 不受支持：" + reason + "；请核对任务来源及 origin",
            )

        if remote.lower().startswith("https:"):
            try:
                url = urlsplit(remote)
                if url.username is not None or url.password is not None:
                    unsupported("URL 不得包含用户名或密码")
                if "?" in remote or "#" in remote:
                    unsupported("URL 不得包含 query 或 fragment")
                if "\\" in remote or any(ord(c) < 33 or ord(c) == 127 for c in remote):
                    unsupported("URL 含不允许的字符")
                source = (task or {}).get("source", {})
                base = urlsplit(source.get("base_url", ""))
                if not url.hostname or url.netloc.lower() != base.netloc.lower():
                    unsupported("origin 主机与 ADO 库不一致（含端口）")
                # 每段单独解码，不允许编码的分隔符或路径穿越改变实际目标。
                parts = [unquote(p) for p in url.path.split("/")[1:]]
                if (
                    any(
                        p in {"", ".", ".."}
                        or "/" in p
                        or "\\" in p
                        or "%" in p
                        or any(ord(c) < 32 or ord(c) == 127 for c in p)
                        for p in parts
                    )
                    or len(parts) != 4
                    or parts[2].lower() != "_git"
                ):
                    unsupported("路径必须为 /{collection}/{project}/_git/{repo}")
                for index, key, label in (
                    (0, "collection", "collection"),
                    (1, "project", "project"),
                ):
                    if parts[index].casefold() != source.get(key, "").casefold():
                        unsupported(label + " 与任务来源不一致")
                if parts[3].casefold() != ((task or {}).get("repo_name") or "").casefold():
                    unsupported("repo 与任务 repo_name 不一致")
                return "https"
            except ValueError:
                unsupported("URL 格式无效")
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
        ):
            unsupported("仅支持匹配任务来源的 HTTPS 地址或完整 SSH 地址")
        if not os.environ.get("SSH_AUTH_SOCK"):
            unsupported("SSH agent 未配置；请启动 agent 并加载密钥")

    async def check(self, root, fd, task=None):
        config = await self.command(
            root, ["config", "--local", "--no-includes", "--name-only", "--null", "--list"],
            lock_fd=fd,
        )
        # 只读取键名，避免多行配置值被误当成键名并出现在错误提示中。
        keys = [key.lower() for key in config.split("\0") if key]
        for key in keys:
            if (
                key.startswith(("url.", "include.", "includeif.", "filter.", "extensions."))
                or key
                in {
                    "core.sshcommand",
                    "core.gitproxy",
                    "core.worktree",
                    "ssh.variant",
                }
                or key.startswith("remote.")
                and key not in {"remote.origin.url", "remote.origin.fetch", "remote.origin.pushurl"}
                or key.startswith(("merge.", "diff."))
                and key.endswith((".driver", ".command"))
                or key.startswith("branch.")
                and key.endswith(".mergeoptions")
            ):
                raise GitFailure(
                    "unsafe_repository",
                    message=f"本地 git 配置含不允许的项 {key}；请移除该项后重试（配置值已隐藏）",
                )
        for marker in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD"):
            location = await self.command(root, ["rev-parse", "--git-path", marker], lock_fd=fd)
            if (Path(root) / location).exists():
                raise GitFailure(
                    "unsafe_repository",
                    message=f"仓库正在 merge、rebase 或 cherry-pick（{marker}）；"
                    "请先完成或中止该操作",
                )
        status = await self.command(root, ["status", "--porcelain"], lock_fd=fd)
        if status:
            raise GitFailure(
                "unsafe_repository", message="工作区有未提交改动；请先提交或自行保存改动后重试"
            )
        try:
            urls = await self.command(root, ["remote", "get-url", "--all", "origin"], lock_fd=fd)
            pushes = await self.command(
                root, ["remote", "get-url", "--push", "--all", "origin"], lock_fd=fd
            )
        except GitFailure:
            raise GitFailure(
                "unsupported_task", message="origin 不受支持：未配置有效地址；请设置 origin 后重试"
            ) from None
        if len(urls.splitlines()) != 1 or pushes != urls:
            raise GitFailure(
                "unsupported_task",
                message="origin 不受支持：fetch 与 push URL 必须相同且各只有一个；"
                "请统一 origin 地址",
            )
        protocol = self.remote(urls, task)
        if protocol == "https":
            for key in keys:
                if key.startswith(("http.", "credential.")):
                    raise GitFailure(
                        "unsafe_repository",
                        message=f"本地 git 配置含不允许的项 {key}；"
                        "请移除该项后重试（配置值已隐藏）",
                    )
        return protocol

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

    async def preflight(self, path, task=None):
        info = await self.inspect(path)
        try:
            async with self.locked(info, asyncio.Event(), wait_seconds=5) as fds:
                await self.check(info["root"], fds, task)
            return info
        except GitFailure as exc:
            if exc.code == "busy":
                raise SettingsError("busy", "仓库正在使用，请稍后预检", 503) from None
            raise SettingsError(
                exc.code if exc.code == "unsupported_task" else "unsafe_repository",
                exc.message,
            ) from None

    async def execute(self, task, context, *, pat=None):
        info = await self.inspect(task["local_repo_path"])
        flow = task["git_flow"]
        branches = {flow["build_branch"], *flow["update_branches"], *flow["push_branches"]}
        for rule in flow["merges"]:
            branches.update((rule["source"], rule["target"]))
        for value in branches:
            branch(value)
        async with self.locked(info, context.cancelled) as fd:
            root = info["root"]
            protocol = await self.check(root, fd, task)

            async def cmd(*args):
                return await self.command(
                    root,
                    list(args),
                    lock_fd=fd,
                    cancel=context.cancelled,
                    output=getattr(context, "log", None),
                    **(
                        {"pat": pat or ""}
                        if protocol == "https" and args[0] in {"fetch", "push", "ls-remote"}
                        else {}
                    ),
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
                        await self.check(root, fd, task)
                        await cmd("checkout", value)
                        await cmd("merge", "--ff-only", f"refs/remotes/origin/{value}")
                        new_refs["refs/heads/" + value] = await cmd(
                            "rev-parse", "--verify", "refs/heads/" + value
                        )
                        await context.checkpoint("git", {**checkpoint, "new_refs": dict(new_refs)})
                    for rule in flow["merges"]:
                        await self.check(root, fd, task)
                        await cmd("checkout", rule["target"])
                        merge_started = True
                        await cmd("merge", "--no-edit", f"refs/remotes/origin/{rule['source']}")
                        merge_started = False
                        new_refs["refs/heads/" + rule["target"]] = await cmd(
                            "rev-parse", "--verify", "refs/heads/" + rule["target"]
                        )
                        await context.checkpoint("git", {**checkpoint, "new_refs": dict(new_refs)})
                    for value in flow["push_branches"]:
                        await self.check(root, fd, task)
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
