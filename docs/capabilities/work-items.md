# 工单（ADO Work Items）

## 这个能力做什么
读取/创建 Azure DevOps 工单：UI「工单」Tab 按看板列浏览与查看详情；Telegram `/wi` 菜单同功能（仅 owner）；「MCP 分析」按钮把工单丢给 AI 会话做分析。

## 关键文件

| 做什么 | 文件 |
| --- | --- |
| ADO 工单 REST（WIQL/详情/评论/Updates/看板/附件/子项/创建） | `app_ado/ado_work_item_http.py` |
| UI 工单 Tab（选项目/看板列、列表、详情、MCP 分析按钮） | `app_ado/ui/work_items_tab.py` |
| 工单详情视图 | `app_ado/work_item_view.py` |
| TG 桥（`/wi` 菜单：选项目→选列→列表→详情→MCP分析选仓库选AI） | `app_ado/tg_work_items_bridge.py` |
| TG 侧 inline 键盘 | `app_ado/tg_work_items_inline.py` |
| MCP 分析提示词生成 + MCP 启动命令 | `app_ado/ai_work_item_flow.py` |
| 本地 MCP server 进程单例管理 | `app_ado/mcp_server_manager.py` |
| 工单相关配置（team/board/project/local_repo） | `app_ado/models.py`（`UiSettings.work_items_*`） |

## 怎么用
- **UI**：工单 Tab 选项目/看板列 → 列表点开看详情/评论/子项；点「🔍 MCP 分析」→ 选仓库 → 选 AI → 在 AI 开发 Tab 起会话并自动灌入分析提示词（`build_mcp_prompt`）。
- **TG**：`/wi` 进入菜单（权限目前只放给 owner，改 `WorkItemsBridge.can_use` 一处即可放开）。
- **MCP server**：`app_ado/mcp_ado_work_items_server.py`（stdio），工具：`ado_get_work_item`、`ado_get_work_item_comments`、`ado_query_work_items`、`ado_list_board_columns`、`ado_list_work_items_by_column`、`ado_get_attachment`（图片自动压缩）、`ado_evaluate_change_policy`、`ado_create_work_item`。启动/停止在 MCP配置 Tab，或已注册进 Codex 全局配置（`~/.codex/config.toml` 的 `adoWorkItems`，见 `docs/ADO_MCP_QUICKSTART.md`）。

## 怎么改
- 新工单字段：加进 `app_ado/ado_work_item_http.py` 的 `DEFAULT_WORK_ITEM_FIELDS`。
- 新 MCP 工具：在 `mcp_ado_work_items_server.py` 加 `_tool_*` 函数并注册进 tools/list。
- 改分析提示词：`app_ado/ai_work_item_flow.py` 的 `build_mcp_prompt`。

## 注意坑
- 权限：TG 侧工单操作目前仅 owner；MCP 分析走的是各 AI **专属机器人**（`bridges` 按 ai_id 路由 claude_code/codex/gemini）。
- 附件走认证下载（`fetch_attachment_bytes`），图片落盘前原地压缩，别直接把原图塞进提示词。
- ADO 调用全同步、无后台线程（TG 侧在轮询线程里跑）；长操作注意别卡住轮询。
