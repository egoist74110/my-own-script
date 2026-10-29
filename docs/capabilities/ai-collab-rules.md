# AI 协作规则（改动准入策略）

> 本仓库的 Agent 协作与模型分工以 [Agent 协作规范](../modernization/AGENT_WORKFLOW.md) 为准；重写历史见 [modernization](modernization.md)。

## 这个能力做什么
让本地 AI 通过 MCP 读工单并尝试改代码**之前**先过一轮策略评估（allow / review / deny）。

## 关键文件

| 做什么 | 文件 |
| --- | --- |
| 策略加载/合并/评估（纯逻辑）、基线一次性导入 | `next/backend/src/toolbox_backend/mcp/policy.py` |
| MCP 工具入口 `ado_evaluate_change_policy` | `next/backend/src/toolbox_backend/mcp/ado_server.py` |
| 导入基线的 API：`POST /api/mcp/ado/policy/import-legacy` | `next/backend/src/toolbox_backend/api/mcp_routes.py`、`services/mcp.py` |
| 策略文件（运行时，数据目录内） | `<数据目录>/mcp/ai_change_policy.yaml`（默认 `~/Library/Application Support/toolbox-next/mcp/`） |
| 项目级覆盖/默认策略来源 | 导入配置的 `imported.ai.default_policy`、`imported.ai.project_overrides` |
| 策略说明文档 | `docs/AI_CHANGE_POLICY.md` |

## 策略评估（`policy.evaluate_change_policy`）
- 输入：工单类型/标题/描述/标签等 + `target_paths` + `change_summary` → 输出 `PolicyEvaluation`（decision、reasons、命中关键词/路径、recommended_action）。
- **建议顺序**：先调 `ado_evaluate_change_policy` → `allow` 才改；`review` 先人工确认范围；`deny` 只许分析不许改。
- 合并顺序：数据目录基线 → `default_policy` → 项目覆盖（仅当该项目 `use_default_policy=false`，非空字段覆盖，`merge_policy`）。
- 判定要点：命中 deny 类型/关键词/forbidden_paths → `deny`；review 类型、非放行类型、review 关键词/路径、文件数超 `max_target_files_without_review`、无目标文件且 `require_human_review_if_no_target_paths` → `review`；否则取 `default_decision`（默认 `review`）。

## 怎么改
- 调策略：改数据目录里的 `mcp/ai_change_policy.yaml`（`load_policy` 要求为普通文件、≤1 MiB、不含疑似密钥、`default_decision` ∈ allow/review/deny）。
- 首次建立基线：新版**不随包附带默认策略**，需导入一次（`import_policy` 用 `O_EXCL`，已存在则 409，不会覆盖）。可从旧版策略起步：`git show 885d186:config/ai_change_policy.yaml > <临时文件>`，把其中旧路径（`app_ado/…`、`*.sh`）改成 `next/…` 对应路径后，作为 `path` 调导入 API。

## 历史协作模板已移除
旧版 `config/model_collaboration_templates/`（Claude/Codex/Gemini 三套模板）与 `config/ai_change_policy.yaml` 已随旧应用删除。需要时从 git 历史找回：`git show 885d186:config/model_collaboration_templates/<路径>`（`git ls-tree -r 885d186 --name-only config/` 可列文件）。当前协作约定以 `AGENTS.md` 与 `docs/modernization/AGENT_WORKFLOW.md` 为准。

## 注意坑
- 数据目录缺 `mcp/ai_change_policy.yaml` 时评估工具会失败（`load_policy` 打不开文件），先导入基线。
- 策略与 MCP server 共用 `policy.py`，改字段两边一起看。
- 改 forbidden/review 路径本身属高风险改动，AI 需谨慎。
