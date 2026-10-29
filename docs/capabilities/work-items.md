# 工单（ADO Work Items）

## 这个能力做什么
只读浏览 Azure DevOps 工单（按看板列），查看详情/评论/历史/子项/附件，并把工单交给 AI 会话分析；Telegram「📋 工单」菜单提供同类功能（仅 owner）；本地 MCP server 把工单读取（及受开关控制的建单）暴露给 AI CLI。桌面端与 TG 只读，不改 ADO 工单。

## 关键文件（均在 `next/`）

| 做什么 | 文件 |
| --- | --- |
| 工单 HTTP 路由（`/api/work-items*`） | `backend/src/toolbox_backend/api/work_item_routes.py`、`api/work_item_schemas.py` |
| 工单服务：看板列表/详情/评论/updates/子项、HTML 清洗、媒体登记与取回 | `backend/src/toolbox_backend/services/work_items.py` |
| ADO 只读出站（同源校验、禁自动重定向、媒体逐跳校验） | `backend/src/toolbox_backend/adapters/ado_read.py`、`adapters/ado_http.py` |
| HTML 清洗 | `backend/src/toolbox_backend/adapters/html_sanitize.py` |
| AI 分析提示词与会话创建（`analyze`/`prompt`） | `backend/src/toolbox_backend/services/ai_prompt.py`、`services/ai_sessions.py` |
| TG 工单菜单（项目→版块→列表→全文/关联项/AI 分析/复制提示词） | `backend/src/toolbox_backend/services/telegram_work_items.py` |
| MCP server（stdio，工具清单见 `tools.json`） | `backend/src/toolbox_backend/mcp/ado_server.py`、`mcp/tools.json`、`mcp/policy.py` |
| MCP 启停/配置/自测 | `backend/src/toolbox_backend/services/mcp.py`、`desktop/src/features/settings/McpAdoCard.vue` |
| 桌面工单页（看板路线、列表、详情、各 Pane） | `desktop/src/features/work-items/WorkItemsPage.vue`、`BoardRoute.vue`、`WorkItemDetail.vue`、`CommentsPane.vue`、`HistoryPane.vue`、`ChildrenPane.vue`、`AttachmentsPane.vue` |

## 怎么用
- **桌面**：工单页选项目 → 看板列（新建/待开发/开发中/测试/已关闭，默认「开发中」）→ 点开看详情；可选 AI 档案与仓库发起「AI 分析」，在 AI 会话页继续。
- **接口**：`GET /api/work-items?project_id=&column=`、`/columns`、`/{id}`、`/{id}/comments|updates|children`、`/media/{media_id}`、`POST /{id}/ai-analysis`、`GET /{id}/ai-prompt?cli=claude|codex|agy`。
- **TG**：见 [Telegram 分层菜单](telegram-menu-next.md) 的「📋 工单」分支；AI 分析走对应 AI 专属机器人，见 [Telegram 控制](telegram-control.md)。
- **MCP 工具**：`ado_get_work_item`、`ado_get_work_item_comments`、`ado_query_work_items`、`ado_list_board_columns`、`ado_list_work_items_by_column`、`ado_get_attachment`、`ado_create_work_item`、`ado_evaluate_change_policy`。总览见 [MCP 服务](mcp-servers.md)。

## 怎么改
- 新 MCP 工具：在 `mcp/tools.json` 加定义，并在 `mcp/ado_server.py` 的 `call` 里实现。
- 改分析提示词：`services/ai_prompt.py`；改字段/清洗：`services/work_items.py`。

## 注意与坑
- `ado_create_work_item` 受配置 `mcp.ado.allow_create_work_item` 控制，默认 false（只读）；类型默认/推荐「用户情景」，「任务」仅用于明确拆分的子任务。
- 附件与内联图片：PAT 只发给与所选 library `base_url` 同源的 URL（拒绝 userinfo、反斜杠、编码穿越、非 http/https）；重定向不自动跟随，媒体逐跳校验；不同源直接拒绝，不匿名抓取。
- 媒体经后端登记 `media_id` 再取回，响应带 nosniff 和严格 CSP；详情 HTML 先清洗，前端用 `SafeHtml` 渲染。
- 旧 `UiSettings.work_items_*`、「MCP 分析」按钮直接在旧 AI 开发 Tab 灌入提示词的流程**未迁移**，改为 `ai-analysis` 创建会话。
- TG 工单操作仅 owner；ACL 成员不可见。
