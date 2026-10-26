import pytest

from toolbox_backend.services.ai_prompt import NEW_ONLY_WARNING, build_prompt, tool_prefix


@pytest.mark.parametrize("cli", ["claude", "codex", "agy"])
def test_toolbox_analysis_prefix_and_warning(cli):
    prefix = tool_prefix(cli, "old__", source="toolbox")
    assert prefix == "mcp__toolbox_ado__"
    text = build_prompt(
        cli=cli,
        work_item_id=12,
        library_name="L",
        project_name="P",
        prefix=prefix,
        new_only=True,
        source="toolbox",
    )
    assert NEW_ONLY_WARNING not in text
    assert "mcp__toolbox_ado__ado_get_work_item" in text
