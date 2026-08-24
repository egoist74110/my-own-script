# AI 协作规则（改动准入策略 + 多模型协作模板）

## 这个能力做什么
让本地 AI 通过 MCP 读工单并尝试改代码**之前**先过一轮策略评估（allow / review / deny）；另有一套可复制到别的项目的多模型协作规范模板（Claude/Codex/Gemini）。

## 关键文件

| 做什么 | 文件 |
| --- | --- |
| 策略文件（类型/关键词/禁止路径/阈值） | `config/ai_change_policy.yaml` |
| 策略加载/合并/评估（纯逻辑） | `app_ado/ai_policy.py` |
| MCP 工具入口（`ado_evaluate_change_policy`） | `app_ado/mcp_ado_work_items_server.py` |
| 策略说明文档 | `docs/AI_CHANGE_POLICY.md` |
| 多模型协作模板（Claude/Codex/Gemini） | `config/model_collaboration_templates/{claude,codex,gemini}/` |
| UI：AI 配置（profiles/targets/policy/bots） | `app_ado/ui/ai_config_tab.py` |
| 策略模型（`AiPolicyConfig`/`ProjectAiSettings`） | `app_ado/models.py` |

## 策略评估（`app_ado/ai_policy.evaluate_change_policy`）
- 输入：工单类型/文本/目标路径等 → 输出 `PolicyEvaluation`（decision + reasons + 命中详情 + recommended_action）。
- **建议顺序**：先调 `ado_evaluate_change_policy` → `allow` 才改；`review` 先人工确认范围；`deny` 只许分析不许改。
- 支持**项目级覆盖**：`UiSettings.ai.project_overrides[project_id].policy`，非空字段覆盖基础策略（`_merge_policy`）。

## 当前默认策略（`config/ai_change_policy.yaml`，`default_decision: review`）
- 自动放行类型：Bug / 缺陷 / 用户情景；需复核：任务 / Task / 未提供目标文件 / 命中 review 关键词或路径 / 文件数 > 5。
- **forbidden_paths**（AI 禁止自动改）：`app_ado/secrets.py`、`tg_control.py`、`ado_release_http.py`、`ado_build_http.py`、`release_github.sh`、`pack_mac_app.sh`、`pack_mac_dmg.sh`。
- review_paths：通知/Telegram/UI 相关文件 + `app_main.py`。

## 多模型协作模板
`config/model_collaboration_templates/` 下三套（`claude/CLAUDE.md`、`codex/AGENTS.md+RULES.md+STYLE.md+WORKFLOW.md+config.toml.template`、`gemini/GEMINI.md+ORCHESTRATION.md+RULES.md+STYLE.md+WORKFLOW.md+gemini_codex_orchestrator.sh+settings.json`）。核心约定：中文/简洁/关键点先行/不编造；**Flash gate**——一次意图并行打开 ≥5 个文件或连续 Grep/Read >3 次，必须先写 Context Request 让 Flash 跑，是硬性前置。复制整套目录到新项目即可。

## 怎么改
- 调策略：改 `config/ai_change_policy.yaml`（评估逻辑在 `ai_policy.py`，有 `required_output_fields` 约定）。
- 加项目覆盖：UI AI配置 Tab 或直接在 `ui_settings.yaml` 的 `ai.project_overrides` 写。
- 改协作模板：直接编辑模板目录，复制到目标项目。

## 注意坑
- 策略文件缺失会 `RuntimeError`（`load_ai_change_policy`），别删 `config/ai_change_policy.yaml`。
- `ai_policy.py` 与 MCP server 共享同一份加载逻辑，改字段要两边一起看。
- 改 forbidden/review 路径本身属于高风险改动（这些文件就在 review/forbidden 名单里），AI 改动需谨慎。
