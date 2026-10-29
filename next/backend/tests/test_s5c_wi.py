"""S5-C: main-slot /wi AI analysis and prompt copy (owner only, idempotent, plain text)."""

from tests.s5c_helpers import OWNER, callback, message, open_s5c, wait
from toolbox_backend.domain.settings import Library, Project


async def seed(ctx):
    config = await ctx.app.state.config_store.read()

    def save(c):
        c.ado.libraries = [Library(id="lib:p", name="LibName", base_url="https://ado.test")]
        c.ado.projects = [Project(id="project:p", library_id="lib:p", collection="c", project="ProjName")]

    await ctx.app.state.config_store.update(config.revision, save)


async def token(ctx, kind, payload, chat=OWNER):
    main = ctx.main
    return await main.store.action(main.bot_id, str(chat), str(chat), kind, payload)


async def step(ctx, label):
    before = await ctx.click("main", label)
    await wait(lambda: len(ctx.texts("main")) > before)


BASE = {"project_id": "project:p", "id": 42}


async def press(ctx, kind, payload, chat=OWNER):
    value = await token(ctx, kind, payload, chat)
    before = len(ctx.texts("main"))
    ctx.post("main", callback(ctx.uid(), value, chat))
    await wait(lambda: len(ctx.texts("main")) > before)
    return value


async def test_analysis_chain_without_ai_bot_is_desktop_only(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready(main=True)
        await seed(ctx)
        await press(ctx, "wi_ai", BASE)
        await step(ctx, "repo")
        assert "选择 AI" in ctx.texts("main")[-1]
        labels = [b["text"] for r in ctx.bots.last_markup(123456789)["inline_keyboard"] for b in r]
        assert {"⬅️ 返回", "🏠 主菜单"} <= set(labels)
        profiles = [x for x in labels if x not in {"⬅️ 返回", "🏠 主菜单"}]
        assert profiles and all("仅桌面可见" in x for x in profiles)
        await step(ctx, "Claude")
        assert "只读分析档" in ctx.texts("main")[-1]
        before = len(ctx.texts("main"))
        value = None
        for row in ctx.bots.last_markup(123456789)["inline_keyboard"]:
            for b in row:
                if "确认" in b["text"]:
                    value = b["callback_data"]
        ctx.post("main", callback(ctx.uid(), value))
        await wait(lambda: len(ctx.texts("main")) > before)
        assert "已在桌面 AI 会话页创建" in ctx.texts("main")[-1]
        # Double click / redelivery with the same token creates nothing more.
        ctx.post("main", callback(ctx.uid(), value))
        sessions = (await ctx.client.get("/api/ai/sessions")).json()["items"]
        assert len(sessions) == 1
        assert sessions[0]["purpose"] == "work_item_analysis"
        assert sessions[0]["origin"]["kind"] == "telegram"
        assert sessions[0]["permission"] == "plan"


async def test_analysis_routes_output_to_enabled_ai_bot(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code", main=True)
        await seed(ctx)
        await press(ctx, "wi_air", {**BASE, "repo_id": "repo"})
        labels = [b["text"] for r in ctx.bots.last_markup(123456789)["inline_keyboard"] for b in r]
        claude = next(x for x in labels if "Claude" in x)
        assert "仅桌面可见" not in claude
        await step(ctx, "Claude")
        await step(ctx, "确认")
        await wait(lambda: any("已创建会话" in t for t in ctx.texts("main")))
        assert "@bot_111111111x" in ctx.texts("main")[-1]
        await wait(lambda: any("完成" in t for t in ctx.texts("claude_code")))


async def test_wi_ai_buttons_owner_only(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready(main=True)
        await seed(ctx)
        value = await token(ctx, "wi_aic", {**BASE, "repo_id": "repo", "profile_id": "claude_code"}, 7001)
        ctx.post("main", callback(ctx.uid(), value, 7001))
        ctx.post("main", message(ctx.uid(), "/wi", 7001))
        await wait(lambda: len(ctx.bots.requests) > 20)
        assert (await ctx.client.get("/api/ai/sessions")).json()["items"] == []
        assert ctx.texts("main", 7001) == []


async def test_copy_prompt_is_plain_text_without_body(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready(main=True)
        await seed(ctx)
        await press(ctx, "wi_cp", BASE)
        sent = ctx.bots.sent[123456789][-1]["payload"]
        assert "parse_mode" not in sent
        assert "#42" in sent["text"] and "ProjName" in sent["text"] and "LibName" in sent["text"]
        assert "```" not in sent["text"].replace("`mcp", "")
        labels = [b["text"] for r in sent["reply_markup"]["inline_keyboard"] for b in r]
        assert {"⬅️ 返回", "🏠 主菜单"} <= set(labels)
        assert len([x for x in labels if x not in {"⬅️ 返回", "🏠 主菜单"}]) == 2


async def test_analysis_never_writes_config_repo_selection(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready(main=True)
        await seed(ctx)
        before = (await ctx.app.state.config_store.read()).ado.model_dump()
        value = await token(ctx, "wi_aic", {**BASE, "repo_id": "repo", "profile_id": "codex"})
        ctx.post("main", callback(ctx.uid(), value))
        await wait(lambda: any("已在桌面" in t for t in ctx.texts("main")))
        after = (await ctx.app.state.config_store.read()).ado.model_dump()
        assert before == after
        sessions = (await ctx.client.get("/api/ai/sessions")).json()["items"]
        assert sessions[0]["permission"] == "read-only"
