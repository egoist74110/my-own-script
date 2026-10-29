"""真实临时仓库验证 hooks 隔离、HTTPS 来源约束和凭据脱敏。"""

import asyncio
import base64
import sys

import pytest

from tests.test_s3_git import Context
from tests.test_s3_git import repository as repository
from tests.test_s3b_ado_tasks import task_harness as task_harness
from toolbox_backend.adapters.task_git import GitAdapter, GitFailure
from toolbox_backend.domain.errors import SettingsError

ORIGIN = "https://azuredevops.example.test/DefaultCollection/CG/_git/CG_Vue_Front"
TASK = {
    "source": {
        "base_url": "https://azuredevops.example.test",
        "collection": "DefaultCollection",
        "project": "CG",
    },
    "repo_name": "CG_Vue_Front",
}


async def test_hooks_and_fsmonitor_are_disabled_for_preflight_and_execution(repository):
    adapter, local, _, git = repository
    hooks = local / ".git" / "test-hooks"
    hooks.mkdir()
    marker = local.parent / "hook-ran"
    # post-checkout 会在正常 checkout 时运行；所有本应用 Git 命令都必须绕过它。
    hook = hooks / "post-checkout"
    hook.write_text(
        f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n"
    )
    hook.chmod(0o700)
    git(local, "config", "core.hooksPath", str(hooks))
    git(local, "config", "core.fsmonitor", str(hook))
    assert (await adapter.preflight(local))["root"] == str(local)
    await adapter.execute(
        {
            "local_repo_path": str(local),
            "git_flow": {
                "build_branch": "main",
                "update_branches": ["main"],
                "merges": [],
                "push_branches": ["main"],
            },
        },
        Context(),
    )
    assert not marker.exists()
    assert git(local, "config", "--local", "core.hooksPath") == str(hooks)


async def https_repository(repository):
    adapter, local, _, git = repository
    adapter.test_remote_root = None
    git(local, "remote", "set-url", "origin", ORIGIN)
    return adapter, local, git


async def test_https_origin_passes_without_ssh_agent(repository, monkeypatch):
    adapter, local, _ = await https_repository(repository)
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    assert (await adapter.preflight(local, TASK))["root"] == str(local)
    assert adapter.remote(ORIGIN.replace("CG_Vue_Front", "%43g_vue_front"), TASK) == "https"
    assert adapter.remote(ORIGIN.replace("example.test", "EXAMPLE.TEST"), TASK) == "https"


@pytest.mark.parametrize(
    "url,reason",
    [
        (ORIGIN.replace("example.test", "evil.test"), "主机"),
        (ORIGIN.replace("example.test", "example.test:443"), "端口"),
        (ORIGIN.replace("DefaultCollection", "other"), "collection"),
        (ORIGIN.replace("/CG/", "/other/"), "project"),
        (ORIGIN.replace("CG_Vue_Front", "other"), "repo_name"),
        (ORIGIN.replace("/_git/", "/repos/"), "路径"),
        (ORIGIN + "/extra", "路径"),
        (ORIGIN.replace("/CG/", "/%2e%2e/"), "路径"),
        (ORIGIN.replace("CG_Vue_Front", "CG%2fVue_Front"), "路径"),
        (ORIGIN.replace("https://", "https://user:password@"), "用户名或密码"),
        (ORIGIN + "?token=private-value", "query"),
        (ORIGIN + "#private-value", "fragment"),
    ],
)
async def test_https_mismatch_is_specific_and_does_not_echo_url(repository, url, reason):
    adapter, local, git = await https_repository(repository)
    git(local, "remote", "set-url", "origin", url)
    with pytest.raises(SettingsError) as exc:
        await adapter.preflight(local, TASK)
    assert exc.value.code == "unsupported_task"
    assert reason in exc.value.message
    assert "请" in exc.value.message
    assert "password" not in str(exc.value) and "private-value" not in str(exc.value)


async def test_push_url_must_equal_fetch_url(repository):
    adapter, local, git = await https_repository(repository)
    git(local, "remote", "set-url", "--push", "origin", ORIGIN + "-other")
    with pytest.raises(SettingsError, match="fetch 与 push URL 必须相同"):
        await adapter.preflight(local, TASK)


def test_missing_repo_name_and_ssh_agent_have_specific_errors(tmp_path, monkeypatch):
    adapter = GitAdapter(tmp_path)
    with pytest.raises(GitFailure, match="repo_name"):
        adapter.remote(ORIGIN, {**TASK, "repo_name": None})
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    with pytest.raises(GitFailure, match="SSH agent 未配置"):
        adapter.remote("git@ado.example.test:c/p/_git/repo")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/fake-agent")
    adapter.remote("git@ado.example.test:c/p/_git/repo")


async def test_multiline_config_values_are_never_reported_as_keys(repository):
    adapter, local, _, git = repository
    git(local, "config", "notes.test", "safe\nfilter.private-value.clean=secret")
    assert (await adapter.preflight(local))["root"] == str(local)


@pytest.mark.parametrize(
    "key",
    [
        "url.https://evil.test/.insteadOf",
        "include.path",
        "filter.test.clean",
        "core.sshCommand",
        "core.gitProxy",
        "merge.test.driver",
        "diff.test.command",
        "http.extraHeader",
        "http.sslVerify",
        "credential.helper",
    ],
)
async def test_unsafe_config_names_are_reported_without_values(repository, key):
    adapter, local, git = await https_repository(repository)
    git(local, "config", key, "private-config-value")
    with pytest.raises(SettingsError) as exc:
        await adapter.preflight(local, TASK)
    assert exc.value.code == "unsafe_repository"
    assert key.lower() in str(exc.value)
    assert "private-config-value" not in str(exc.value)


@pytest.mark.parametrize(
    "marker", ["MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD"]
)
async def test_operation_markers_are_specific(repository, marker):
    adapter, local, _, _ = repository
    path = local / ".git" / marker
    if marker.startswith("rebase"):
        path.mkdir()
    else:
        path.write_text("0" * 40)
    with pytest.raises(SettingsError, match=marker):
        await adapter.preflight(local)


async def test_dirty_missing_origin_and_non_worktree_messages(repository, tmp_path):
    adapter, local, _, git = repository
    (local / "file").write_text("dirty")
    with pytest.raises(SettingsError, match="工作区有未提交改动"):
        await adapter.preflight(local)
    (local / "file").write_text("base\n")
    git(local, "remote", "remove", "origin")
    with pytest.raises(SettingsError, match="未配置有效地址"):
        await adapter.preflight(local)
    with pytest.raises(SettingsError, match="git 工作树"):
        await adapter.preflight(tmp_path)


@pytest.mark.parametrize("exit_code", [0, 1])
async def test_auth_argv_and_echoed_secrets_are_redacted(tmp_path, monkeypatch, caplog, exit_code):
    adapter = GitAdapter(tmp_path / "data")
    pat = "fake-sensitive-pat-123456"
    encoded = base64.b64encode((":" + pat).encode()).decode()
    header = "Authorization: Basic " + encoded
    # 假 Git 故意逐字回显 argv、PAT 和编码值到两个流，覆盖分块脱敏。
    executable = tmp_path / "fake_git.py"
    executable.write_text(
        f"#!{sys.executable}\nimport os,sys\n"
        f"text = ' '.join(sys.argv) + '\\n' + {pat!r} + '\\n' + {encoded!r} + '\\n'\n"
        "for fd in (1, 2):\n"
        " for byte in text.encode(): os.write(fd, bytes([byte]))\n"
        f"sys.exit({exit_code})\n"
    )
    executable.chmod(0o700)
    adapter.executable = str(executable)
    spawn = asyncio.create_subprocess_exec
    observed = []

    async def capture(*args, **kwargs):
        observed.append((args, kwargs["env"]))
        return await spawn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    logs = []

    async def sink(text, **kwargs):
        logs.append(text)

    result = ""
    if exit_code:
        with pytest.raises(GitFailure) as exc:
            await adapter.command(tmp_path, ["fetch", "origin"], pat=pat, output=sink)
        result = str(exc.value)
    else:
        result = await adapter.command(tmp_path, ["fetch", "origin"], pat=pat, output=sink)
    for secret in (pat, encoded, header):
        assert secret not in result + "".join(logs) + caplog.text
    args, env = observed[0]
    assert "http.extraHeader=" + header in args
    assert "credential.helper=" in args and "http.followRedirects=false" in args
    assert env["GIT_TERMINAL_PROMPT"] == "0" and env["GIT_ALLOW_PROTOCOL"] == "https"
    assert pat not in repr(env)


async def test_spawn_exception_cannot_expose_auth_arguments(tmp_path, monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError(repr(args))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail)
    with pytest.raises(GitFailure) as exc:
        await GitAdapter(tmp_path / "data").command(
            tmp_path, ["fetch", "origin"], pat="private-pat"
        )
    assert "private-pat" not in str(exc.value)
    assert exc.value.__suppress_context__


async def test_missing_pat_stops_before_starting_remote_command(tmp_path, monkeypatch):
    async def fail(*args, **kwargs):
        pytest.fail("未配置 PAT 不应启动 Git")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail)
    with pytest.raises(GitFailure, match="未配置 ADO 库 PAT"):
        await GitAdapter(tmp_path).command(tmp_path, ["fetch", "origin"], pat="")


async def test_ado_prepare_supplies_task_identity_and_execute_uses_source_pat(
    repository, task_harness, monkeypatch
):
    adapter, local, git = await https_repository(repository)
    _, executor, _, _, task = task_harness
    task.update(local_repo_path=str(local), repo_name="demo")
    git(local, "remote", "set-url", "origin", "https://ado.test/c/sample/_git/demo")
    executor.git = adapter
    prepared = await executor.prepare(task, "sync_build_release", None)
    assert prepared.steps[0]["kind"] == "git"
    task["prepared"] = {"targets": []}
    context = Context()
    context.snapshot, context.operation, context.step_no = task, "sync_build_release", 0

    async def noop(*args, **kwargs):
        pass

    context.log = context.complete_step = noop

    async def execute(snapshot, actual_context, *, pat):
        assert snapshot is task and actual_context is context
        assert pat == "fake-task-pat-1234"
        return "a" * 40

    monkeypatch.setattr(adapter, "execute", execute)
    outcome = await executor.execute(context)
    assert outcome.status == "succeeded"


async def test_execute_authenticates_every_remote_command_only(repository, monkeypatch):
    adapter, local, git = await https_repository(repository)
    original_command = adapter.command
    seen = []
    commit = git(local, "rev-parse", "HEAD")

    async def command(path, args, **kwargs):
        seen.append((args[0], kwargs.get("pat")))
        if args[0] in {"fetch", "push"}:
            return ""
        if args[0] == "ls-remote":
            return commit + "\trefs/heads/main"
        return await original_command(path, args, **kwargs)

    monkeypatch.setattr(adapter, "command", command)
    await adapter.execute(
        {
            **TASK,
            "local_repo_path": str(local),
            "git_flow": {
                "build_branch": "main",
                "update_branches": ["main"],
                "push_branches": ["main"],
                "merges": [],
            },
        },
        Context(),
        pat="fake-execution-pat",
    )
    assert {name for name, pat in seen if pat} == {"fetch", "push", "ls-remote"}
    assert all(
        pat == "fake-execution-pat" for name, pat in seen if name in {"fetch", "push", "ls-remote"}
    )
