# MCP 服务（ADO 工单 / 飞书 Lark / Figma）

## 这个能力做什么
设置 → MCP 页（`McpTab.vue`，三张卡片）统一管理三类 MCP，但托管方式不同：
- **ADO 工单**：纯 Python stdio server，由 AI 客户端按需拉起（后端不常驻），后端只做配置、自检和接入配置生成。
- **Figma**：stdio wrapper，从系统钥匙串读 token 后 exec 官方 `figma-developer-mcp`；同样由客户端拉起，后端只做自检/配置。
- **Lark/飞书**：后端唯一**常驻托管**的 MCP（streamable HTTP 单实例 + OAuth），所有 AI 客户端连同一个 URL。
另有「运行组件」安装（Node.js ≥20.20 检测/受管安装 + 锁定版本 npm 包）。

## 关键文件（均在 `next/` 下）

| 做什么 | 文件 |
| --- | --- |
| 配置/凭据/Lark 托管/运行组件安装/自检/客户端配置生成 | `backend/src/toolbox_backend/services/mcp.py` |
| REST（`/api/mcp/*`） | `backend/src/toolbox_backend/api/mcp_routes.py`、`mcp_schemas.py` |
| MCP 配置模型 | `backend/src/toolbox_backend/domain/mcp.py` |
| ADO MCP server（8 个工具，定义见 `tools.json`） | `backend/src/toolbox_backend/mcp/ado_server.py`、`tools.json` |
| ADO 变更策略（显式导入旧策略） | `backend/src/toolbox_backend/mcp/policy.py` |
| 附件缓存（私有、有上限、flock 淘汰） | `backend/src/toolbox_backend/mcp/cache.py` |
| Figma wrapper | `backend/src/toolbox_backend/mcp/figma_wrapper.py` |
| Node/npm 运行组件检测与安装 | `backend/src/toolbox_backend/mcp/runtime.py`；包清单 `backend/resources/mcp/package.json` |
| Lark 日志轮转/token 状态推断/端口探测 | `backend/src/toolbox_backend/mcp/lark_logs.py` |
| 受限 stdio 握手、自检、日志脱敏 | `backend/src/toolbox_backend/mcp/runner.py` |
| 进程组监督（control EOF 即杀整组） | `backend/src/toolbox_backend/adapters/proc_supervisor.py` |
| Lark 单飞刷新补丁 / Figma 并发限流补丁 | `backend/resources/mcp/lark_mcp_patches.js`、`figma_mcp_concurrency.js` |
| 前端卡片 | `desktop/src/features/settings/{McpTab,McpAdoCard,McpLarkCard,McpFigmaCard,useMcp}`（`.vue`/`.ts`） |

## 怎么用
- **ADO**：设置里先配好 ADO 库/项目/PAT（stdio server 从钥匙串读 `ado_pat:<库id>`）→ 卡片「自检」→ 用 `GET /api/mcp/client-config` 或卡片的复制按钮拿 Claude/Codex/agy 接入片段（server 名 `toolbox_ado`）。`ado_create_work_item` 默认关闭，需在卡片里确认开启。
- **Figma**：保存 Figma token（钥匙串 `figma_token`）→ 自检 → 复制 `toolbox_figma` 接入片段。
- **Lark**：先点「运行组件」安装 → 填 app_id + app_secret（secret 进钥匙串）→ 确认「旧应用里的飞书 MCP 已停」（ownership）→「登录」走 OAuth → 启动；接入 URL 为 `http://localhost:<port>/mcp`。TG 主机器人有 Lark 启停面板（`telegram_commands.mcp_panel`）。
- 旧凭据/策略可显式导入（`import-legacy`）。

## 注意与坑
- Lark 以 `-m streamable --oauth --token-mode user_access_token` 单实例运行：会轮换的 refresh_token 只能一个进程消费（旧版实测 20038 即多实例抢刷新所致，新版代码里未专门处理该错误码）。`lark_mcp_patches.js` 做单飞刷新，启动时输出 `[toolbox-lark-patch] <名>=applied|skipped|failed` 标记，缺目标只降级不挂。
- 未确认 ownership（旧应用里的飞书 MCP 已停）不让启动，端口被占报 `mcp_port_in_use`；token 状态是从日志推断的（ok / refresh_failing），不读钥匙串。
- 子进程都挂在 `proc_supervisor` 下，后端被 SIGKILL 也会因 control EOF 杀整组，不留孤儿；信号处理里不要 `proc.wait()`（见 `docs/MCP_SERVER_GUIDELINES.md`、`docs/MCP_PROMPT_RULES.md`）。
- npm 包版本锁定（lark-mcp 0.5.1、figma-developer-mcp 0.13.2），只在显式安装 job 里 `npm ci`，运行时不联网解析。
- 工单 AI 分析的提示词默认用旧注册的 `mcp__ado-work-items__` 前缀（`ai.analysis.mcp_source=legacy`），切到 `toolbox` 才用 `toolbox_ado`（卡片有切换确认）。
- 未迁移：Codex 全局 `adoWorkItems` 一键注册、ADO/Figma 由 UI 常驻托管并启停——新版只生成接入配置，不代写客户端配置文件。
