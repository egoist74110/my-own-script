# ruff: noqa: F811
"""S5-B: work-item analysis prompts/sessions, Claude resume candidates, config enums."""

import json
import os
import time
from uuid import uuid4

import pytest

from tests.s5b_helpers import (
    chat,  # noqa: F401  (fixture)
    events,
    new_body,
    records,
    wait_event,
)
from toolbox_backend.domain.ai import AIConfig, normalize_ai
from toolbox_backend.domain.settings import Library, Project


async def add_project(app, project_id="proj:11111111-1111-1111-1111-111111111111"):
    def add(c):
        c.ado.libraries.append(Library(id="lib1", name="库甲", base_url="https://ado.example.com"))
        c.ado.projects.append(
            Project(id=project_id, library_id="lib1", collection="DefaultCollection", project="项目`乙")
        )

    config = await app.state.config_store.read()
    await app.state.config_store.update(config.revision, add)
    return project_id


def analysis_body(profile, project_id, **extra):
    return dict(
        request_id=str(uuid4()), project_id=project_id, repo_id="repo", profile_id=profile, **extra
    )


@pytest.mark.asyncio
async def test_prompt_per_cli_names_and_no_work_item_body(chat):
    app, client, _, _ = chat
    pid = await add_project(app)
    prompts = {}
    for cli in ("claude", "codex", "agy"):
        r = await client.get(
            "/api/work-items/4242/ai-prompt", params=dict(project_id=pid, cli=cli)
        )
        assert r.status_code == 200, r.text
        prompts[cli] = r.json()
    claude = prompts["claude"]["prompt"]
    assert "mcp__ado-work-items__ado_get_work_item" in claude and "ToolSearch" in claude
    assert "mcp__adoWorkItems__ado_get_work_item" in prompts["codex"]["prompt"]
    assert "mcp__adoWorkItems__" not in claude and "ToolSearch" not in prompts["codex"]["prompt"]
    for value in prompts.values():
        text = value["prompt"]
        assert "库甲" in text and "项目 乙" in text and "#4242" in text  # backtick neutralised
        assert "`项目" not in text and "active_library_id" not in text
        assert "旧 MCP 可能无法解析" in text and value["warnings"]  # proj:<uuid> is new-only
    bad = await client.get("/api/work-items/1/ai-prompt", params=dict(project_id=pid, cli="other"))
    assert bad.status_code == 422
    nope = await client.get("/api/work-items/1/ai-prompt", params=dict(project_id="zzz", cli="claude"))
    assert nope.status_code in (404, 409)
    # prefix is configurable for Codex/agy
    config = await app.state.config_store.read()

    def change(c):
        c.ai.mcp_tool_prefix.codex = "mcp__custom__"

    await app.state.config_store.update(config.revision, change)
    r = await client.get("/api/work-items/9/ai-prompt", params=dict(project_id=pid, cli="codex"))
    assert "mcp__custom__ado_get_work_item" in r.json()["prompt"]


@pytest.mark.asyncio
async def test_analysis_sessions_use_analysis_tiers_and_are_idempotent(chat):
    app, client, _, log = chat
    pid = await add_project(app)
    config = await app.state.config_store.read()
    assert config.ai.analysis.agy.mode == "plan"
    out = {}
    for profile in ("claude_code", "codex", "gemini"):
        body = analysis_body(profile, pid)
        first = await client.post("/api/work-items/77/ai-analysis", json=body)
        assert first.status_code == 200, first.text
        again = await client.post("/api/work-items/77/ai-analysis", json=body)
        assert again.json()["id"] == first.json()["id"]
        out[profile] = first.json()
        assert first.json()["purpose"] == "work_item_analysis"
        assert first.json()["work_item_ref"] == {"id": 77, "project_id": pid}
        assert "legacy_mcp_may_not_resolve_project" in first.json()["warnings"]
        await wait_event(client, first.json()["id"], "turn_completed")
    assert out["claude_code"]["permission"] == "plan"
    assert out["codex"]["permission"] == "read-only"
    assert out["gemini"]["permission"] == "plan"
    runs = {r["cli"]: r for r in records(log) if "cli" in r}
    assert runs["claude"]["argv"][runs["claude"]["argv"].index("--permission-mode") + 1] == "plan"
    assert runs["codex"]["argv"][runs["codex"]["argv"].index("-s") + 1] == "read-only"
    assert "--mode" in runs["agy"]["argv"] and "plan" in runs["agy"]["argv"]
    # exactly one run per cli despite the duplicate requests; prompt reached the CLI via stdin
    assert len([r for r in records(log) if "cli" in r]) == 3
    assert runs["codex"]["stdin_prompt"].startswith("请通过 ADO MCP 分析工单 #77")
    # the prompt turn is recorded without work-item content and never touches repo settings
    turn = [e for e in await events(client, out["codex"]["id"]) if e["kind"] == "turn_started"][0]
    assert "库甲" in turn["payload"]["text"]
    after = await app.state.config_store.read()
    assert after.ado.active_project_id == config.ado.active_project_id
    for view in out.values():
        await client.post(f"/api/ai/sessions/{view['id']}/close")


@pytest.mark.asyncio
async def test_analysis_rejections(chat):
    app, client, _, _ = chat
    pid = await add_project(app)
    r = await client.post("/api/work-items/77/ai-analysis", json=analysis_body("nope", pid))
    assert r.status_code == 404
    r = await client.post("/api/work-items/0/ai-analysis", json=analysis_body("codex", pid))
    assert r.status_code == 422
    config = await app.state.config_store.read()

    def risky(c):
        c.ai.analysis.codex.sandbox = "danger-full-access"

    await app.state.config_store.update(config.revision, risky)
    r = await client.post("/api/work-items/5/ai-analysis", json=analysis_body("codex", pid))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "high_risk_ack_required"


def write_jsonl(directory, name, lines, mtime=None):
    path = directory / name
    path.write_text("\n".join(json.dumps(x) if not isinstance(x, str) else x for x in lines) + "\n")
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


@pytest.mark.asyncio
async def test_resume_candidates_are_bounded_and_safe(chat, tmp_path):
    app, client, repo, _ = chat
    home = tmp_path / "home"
    import re

    encoded = re.sub(r"[^a-zA-Z0-9]", "-", str(repo.resolve()))
    folder = home / ".claude/projects" / encoded
    folder.mkdir(parents=True)
    now = time.time()
    user = lambda text: {"type": "user", "message": {"content": text}}  # noqa: E731
    write_jsonl(folder, "aaa-1.jsonl", [{"type": "system"}, user("<meta>"), user("修复登录问题 " * 20)], now)
    write_jsonl(folder, "bbb-2.jsonl", ["not json", user([{"type": "text", "text": "Write docs"}])], now - 50)
    write_jsonl(folder, "deep.jsonl", [{"type": "system"}] * 85 + [user("too deep")], now - 60)
    (tmp_path / "outside.jsonl").write_text(json.dumps(user("secret outside")) + "\n")
    (folder / "link-3.jsonl").symlink_to(tmp_path / "outside.jsonl")
    (folder / "..bad.jsonl").write_text("{}\n")
    (folder / "notes.txt").write_text("x")
    r = await client.get("/api/ai/resume-candidates", params=dict(repo_id="repo", cli="claude"))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["session_id"] for i in items] == ["aaa-1", "bbb-2", "deep"]
    assert len(items[0]["title"]) <= 48 and items[0]["title"].startswith("修复登录问题")
    assert items[1]["title"] == "Write docs" and items[2]["title"] == "(无标题)"
    assert "outside" not in json.dumps(items)
    q = await client.get(
        "/api/ai/resume-candidates", params=dict(repo_id="repo", cli="claude", query="DOCS")
    )
    assert [i["session_id"] for i in q.json()["items"]] == ["bbb-2"]
    # more than 50 files: only the newest 50
    for index in range(60):
        write_jsonl(folder, f"many-{index}.jsonl", [user(f"m{index}")], now - 1000 - index)
    r = await client.get("/api/ai/resume-candidates", params=dict(repo_id="repo", cli="claude"))
    assert len(r.json()["items"]) == 50
    # unknown repo / unsupported cli
    assert (
        await client.get("/api/ai/resume-candidates", params=dict(repo_id="x", cli="claude"))
    ).status_code == 409
    assert (
        await client.get("/api/ai/resume-candidates", params=dict(repo_id="repo", cli="codex"))
    ).status_code == 422
    # a symlinked project folder is refused
    real = folder.with_name("real")
    folder.rename(real)
    folder.symlink_to(real)
    r = await client.get("/api/ai/resume-candidates", params=dict(repo_id="repo", cli="claude"))
    assert r.json()["items"] == []


@pytest.mark.asyncio
async def test_create_with_claude_external_id_and_guards(chat):
    app, client, _, log = chat
    sid = await client.post(
        "/api/ai/sessions",
        json=new_body(resume=dict(external_id="11111111-2222-3333-4444-555555555555")),
    )
    assert sid.status_code == 200, sid.text
    await client.post("/api/ai/sessions/%s/messages" % sid.json()["id"], json=dict(request_id=str(uuid4()), text="x"))
    await wait_event(client, sid.json()["id"], "turn_completed")
    argv = [r for r in records(log) if r.get("cli") == "claude"][0]["argv"]
    assert argv[argv.index("--resume") + 1] == "11111111-2222-3333-4444-555555555555"
    bad = await client.post("/api/ai/sessions", json=new_body(resume=dict(external_id="--evil")))
    assert bad.status_code == 422
    codex = await client.post(
        "/api/ai/sessions", json=new_body("codex", resume=dict(external_id="thread1"))
    )
    assert codex.status_code == 422
    live = await client.post(
        f"/api/ai/sessions/{sid.json()['id']}/resume", json=dict(request_id=str(uuid4()))
    )
    assert live.status_code == 409 and live.json()["detail"]["code"] == "session_active"
    await client.post(f"/api/ai/sessions/{sid.json()['id']}/close")
    other = await client.post("/api/ai/sessions", json=dict(
        request_id=str(uuid4()), kind="terminal", profile_id="codex", repo_id="repo",
        resume=dict(external_id="x1"),
    ))
    assert other.status_code == 409 and other.json()["detail"]["code"] == "unsupported_cli"


def test_config_enums_and_legacy_default_permission():
    config, _ = normalize_ai({"defaults": {"claude": {"permission": "default"}}})
    assert config.defaults.claude.permission == "manual"
    config = AIConfig.model_validate({"analysis": {"claude": {"permission": "default"}}})
    assert config.analysis.claude.permission == "manual"
    assert AIConfig().analysis.agy.mode == "plan" and AIConfig().defaults.agy.mode == "sandbox"
    for mode in ("sandbox", "plan", "auto"):
        assert AIConfig.model_validate({"defaults": {"agy": {"mode": mode, "effort": "max"}}})
    with pytest.raises(ValueError):
        AIConfig.model_validate({"defaults": {"agy": {"mode": "bogus"}}})
    with pytest.raises(ValueError):
        AIConfig.model_validate({"defaults": {"agy": {"effort": "ultra"}}})
    with pytest.raises(ValueError):
        AIConfig.model_validate({"mcp_tool_prefix": {"codex": "bad prefix`"}})
    assert AIConfig().mcp_tool_prefix.codex == "mcp__adoWorkItems__"


@pytest.mark.asyncio
async def test_permission_default_is_normalised_at_create(chat):
    app, client, _, log = chat
    r = await client.post("/api/ai/sessions", json=new_body(permission="default"))
    assert r.status_code == 200 and r.json()["permission"] == "manual"
    await wait_event(client, r.json()["id"], "notice")
    r2 = await client.post("/api/ai/sessions", json=new_body(permission="bypassPermissions"))
    assert r2.status_code == 409 and r2.json()["detail"]["code"] == "high_risk_ack_required"
    await client.post(f"/api/ai/sessions/{r.json()['id']}/close")
