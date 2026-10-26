"""S6 integration-acceptance regressions (S6-ACC-00x): Lark state machine, login argv, PATCH guard."""

import asyncio
import json
from pathlib import Path

import pytest

from tests.test_s6b_lark import (  # noqa: F401  (fixture re-export)
    _make_lark_prober,
    _setup_fake_lark_env,
    isolated_supervisor,
)
from toolbox_backend.adapters.ai_process import SupervisedProcess
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.api.mcp_schemas import MCPSettingsPatch
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.mcp import LarkMcp
from toolbox_backend.mcp.runner import secure_directory
from toolbox_backend.services.events import EventHub
from toolbox_backend.services.mcp import McpService

pytestmark = pytest.mark.usefixtures("isolated_supervisor")


def _service(tmp_path: Path, **kwargs):
    data_dir = tmp_path / "data"
    store, creds, port, mode_path = _setup_fake_lark_env(data_dir, tmp_path, **kwargs)
    svc = McpService(
        store,
        creds,
        MemoryCredentials(),
        events=EventHub(),
        path_extras=[tmp_path / "fake_lark_bin"],
    )
    svc.lark_http_prober = _make_lark_prober(tmp_path)
    return svc, data_dir, mode_path


@pytest.mark.asyncio
async def test_login_argv_never_carries_scope(tmp_path):
    """S6-ACC-002: --scope selects the v1 OAuth2 provider, which does not issue a refresh token."""
    dump = tmp_path / "login_dump.json"
    svc, _, _ = _service(tmp_path, dump_file=dump)
    try:
        await svc.login_lark()
        argv = json.loads(dump.read_text(encoding="utf-8"))["argv"]
        assert argv[1] == "login"
        assert "--scope" not in argv and "-s" not in argv
        assert not any(item in argv for item in ("offline_access", "docx:document"))
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_start_failure_before_spawn_does_not_wedge_state(tmp_path):
    """S6-ACC-003: an exception after state=starting must leave a recoverable state."""
    svc, data_dir, _ = _service(tmp_path)
    try:
        run_dir = secure_directory(data_dir, "mcp", "run", "lark")
        (run_dir / "stray.txt").write_text("x")  # prepare_run_directory requires an empty dir
        with pytest.raises(ValueError):
            await svc.start_lark()
        snap = await svc.snapshot()
        assert snap.lark.state == "failed"
        assert snap.lark.last_error == "start_failed"
        (run_dir / "stray.txt").unlink()
        snap = await svc.start_lark()  # not rejected with mcp_busy
        assert snap.lark.state == "running"
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_login_failure_before_spawn_does_not_wedge_state(tmp_path):
    svc, data_dir, _ = _service(tmp_path)
    try:
        run_dir = secure_directory(data_dir, "mcp", "run", "lark")
        (run_dir / "stray.txt").write_text("x")
        with pytest.raises(ValueError):
            await svc.login_lark()
        snap = await svc.snapshot()
        assert snap.lark.state == "failed"
        assert snap.lark.last_error == "login_failed"
        (run_dir / "stray.txt").unlink()
        snap = await svc.stop_lark()  # state is not stuck in logging_in
        assert snap.lark.state == "stopped"
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_concurrent_starts_spawn_exactly_one_process(
    tmp_path, monkeypatch
):
    """S6-ACC-003: check-and-claim is atomic; the loser gets mcp_busy and nothing is orphaned."""
    svc, _, _ = _service(tmp_path)
    spawned = []
    original = SupervisedProcess.start.__func__

    async def counting(cls, *args, **kwargs):
        spawned.append(args[0][2:3])
        return await original(cls, *args, **kwargs)

    monkeypatch.setattr(SupervisedProcess, "start", classmethod(counting))
    try:
        results = await asyncio.gather(svc.start_lark(), svc.start_lark(), return_exceptions=True)
        errors = [r for r in results if isinstance(r, BaseException)]
        assert len(errors) == 1
        assert isinstance(errors[0], SettingsError) and errors[0].code == "mcp_busy"
        assert spawned == [["mcp"]]
        assert (await svc.snapshot()).lark.state == "running"
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_cancel_login_when_idle_keeps_running_state(tmp_path):
    """S6-ACC-003: cancelling a login that is not in progress must not rewrite the state."""
    svc, _, _ = _service(tmp_path)
    try:
        assert (await svc.start_lark()).lark.state == "running"
        snap = await svc.cancel_lark_login()
        assert snap.lark.state == "running"
        assert (await svc.stop_lark()).lark.state == "stopped"
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_logout_failure_is_reported_and_keeps_login_metadata(tmp_path):
    """S6-ACC-004: a failing logout must not clear the login state or claim success."""
    svc, _, mode_path = _service(tmp_path)
    try:
        await svc.login_lark()
        assert (await svc.snapshot()).lark.login.logged_in_at is not None
        mode = json.loads(mode_path.read_text(encoding="utf-8"))
        mode["logout"] = "fail"
        mode_path.write_text(json.dumps(mode), encoding="utf-8")
        snap = await svc.logout_lark()
        assert snap.lark.last_error == "logout_failed"
        assert snap.lark.login.logged_in_at is not None
        assert not any("旧 bearer" in w for w in snap.lark.warnings)
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_oversized_output_line_does_not_stall_the_child(tmp_path):
    """S6-ACC-004: a >1 MiB line must not stop the log pump (the child would block on a full pipe)."""
    svc, _, mode_path = _service(tmp_path)
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    mode["extra_logs"] = ["x" * (2 << 20), "after-the-long-line"]
    mode_path.write_text(json.dumps(mode), encoding="utf-8")
    try:
        snap = await svc.start_lark()
        assert snap.lark.state == "running"
        assert "after-the-long-line" in snap.lark.log_tail
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_settings_patch_cannot_bypass_ownership_or_login_metadata(tmp_path):
    """S6-ACC-005: only the ownership routes / login flow may change these fields."""
    svc, _, _ = _service(tmp_path, owner_confirmed=False)
    try:
        config = await svc.store.read()
        forged = LarkMcp.model_validate(
            {**config.mcp.lark.model_dump(), "owner_confirmed_at": "2026-01-01T00:00:00Z"}
        )
        with pytest.raises(SettingsError) as exc:
            await svc.patch(MCPSettingsPatch(revision=config.revision, lark=forged))
        assert exc.value.status == 422
        forged = LarkMcp.model_validate(
            {**config.mcp.lark.model_dump(), "login": {"logged_in_at": "2026-01-01T00:00:00Z"}}
        )
        with pytest.raises(SettingsError):
            await svc.patch(MCPSettingsPatch(revision=config.revision, lark=forged))
        # An unchanged echo of the snapshot values (what the UI sends) is still accepted.
        ok = LarkMcp.model_validate({**config.mcp.lark.model_dump(), "language": "en"})
        await svc.patch(MCPSettingsPatch(revision=config.revision, lark=ok))
        assert (await svc.store.read()).mcp.lark.language == "en"
    finally:
        await svc.close()


def test_data_dir_accepts_root_owned_system_symlink_ancestors(tmp_path):
    """S6-ACC-006: /var and /tmp are root-owned symlinks on macOS; $TMPDIR data dirs must pass."""
    from toolbox_backend.mcp.runner import validate_data_dir

    unresolved = Path("/var") / tmp_path.resolve().relative_to("/private/var")
    if not Path("/var").is_symlink():
        pytest.skip("platform without a /var symlink")
    data = unresolved / "data"
    data.mkdir(mode=0o700)
    assert validate_data_dir(data) == data


def test_data_dir_still_rejects_user_symlinks(tmp_path):
    from toolbox_backend.mcp.runner import validate_data_dir

    real = tmp_path / "real"
    (real / "data").mkdir(parents=True, mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(ValueError):
        validate_data_dir(link / "data")  # user-owned ancestor link
    (tmp_path / "leaf").symlink_to(real / "data")
    with pytest.raises(ValueError):
        validate_data_dir(tmp_path / "leaf")  # the data dir itself is a link


@pytest.mark.asyncio
async def test_settings_and_credential_writes_publish_mcp_status(tmp_path):
    """S6-ACC-007: every view of the MCP page must learn about writes made through another view."""
    svc, _, _ = _service(tmp_path)
    try:
        hub = svc.hub
        config = await svc.store.read()
        lark = LarkMcp.model_validate({**config.mcp.lark.model_dump(), "language": "en"})
        await svc.patch(MCPSettingsPatch(revision=config.revision, lark=lark))
        last = hub._mcp_history[-1]
        assert last.event == "mcp.status" and last.data.lark.language == "en"
        config = await svc.store.read()
        await svc.credential("figma_token", config.revision, value="figd_fake_token_value")
        assert hub._mcp_history[-1].data.figma.token_configured is True
    finally:
        await svc.close()


def test_terminate_group_tolerates_zombie_only_group():
    """S6-ACC-008: macOS reports EPERM for killpg on a group whose members are all zombies."""
    import subprocess
    import sys
    import time

    from toolbox_backend.adapters.proc_supervisor import terminate_group

    child = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    time.sleep(0.5)  # exited but not reaped: a zombie group leader
    assert terminate_group(child.pid, grace_s=1) == 0
