# MCP 服务（ADO 工单 / 飞书 Lark / Figma）

## 这个能力做什么
MCP配置 Tab（`app_ado/ui/mcp_config_tab.py`）统一托管 3 类 MCP server：ADO 工单（stdio）、Lark/飞书（共享 streamable HTTP 单实例）、Figma（stdio wrapper）。每类都能：配凭据、启动/停止、看 token 状态、复制给 Claude/Codex/Antigravity 的接入配置。

**状态：三类都已接入 UI（MCP配置 Tab 内的三张卡片），不是独立顶层选项卡。**

## 关键文件

| 做什么 | 文件 |
| --- | --- |
| MCP配置 Tab（ADO工单MCP / Lark MCP / Figma MCP 三张卡） | `app_ado/ui/mcp_config_tab.py` |
| ADO 工单 MCP server（stdio，纯 Python） | `app_ado/mcp_ado_work_items_server.py` |
| ADO MCP 进程单例（UI 与 TG 共用） | `app_ado/mcp_server_manager.py` |
| ADO MCP 启动命令/客户端配置生成 | `app_ado/ai_work_item_flow.py` |
| Lark MCP wrapper（exec 官方 lark-mcp） | `app_lark/mcp_lark_server.py` |
| Lark 单例托管 + OAuth 登录/登出/token 状态 | `app_lark/mcp_server_manager.py`、`app_lark/token_status.py` |
| Lark 客户端接入配置生成（统一 URL） | `app_lark/lark_mcp_flow.py` |
| Lark 设置/登录态存储 | `app_lark/store.py`、`app_lark/secrets.py`（keychain 存 app_secret） |
| Bearer 注入补丁 | `app_lark/lark_token_inject.py` |
| 进程组监督/孤儿回收 | `app_lark/proc_supervise.py` |
| npx/node 路径引导 | `app_lark/node_bootstrap.py` |
| Figma MCP wrapper（exec 官方 figma-developer-mcp） | `app_figma/mcp_figma_server.py` |
| Figma 单例/设置/token 状态 | `app_figma/mcp_server_manager.py`、`app_figma/store.py`、`app_figma/secrets.py`（keychain 存 Figma PAT） |
| Figma 并发补丁 preload | `app_figma/figma_mcp_concurrency.js` |

## 怎么用
- **ADO**：先在本 UI 配好 library/project/PAT（MCP 直接复用，无需重复登录）→ MCP配置 Tab 启动 server → 把生成的命令复制进 Claude/Codex/Antigravity；或直接走已注册的 Codex 全局 `adoWorkItems`（`docs/ADO_MCP_QUICKSTART.md`）。
- **Lark**：MCP配置 Tab 填 app_id + app_secret（secret 进 keychain）→「登录」走 OAuth 托管流程 → server 以 `-m streamable --oauth` 单实例常驻，所有 AI 客户端连同一个 URL。
- **Figma**：填 Figma PAT（keychain）→ 启动 → 复制 stdio 接入命令。

## 注意坑（血泪教训，先读这两篇再动手）
- **`docs/MCP_SERVER_GUIDELINES.md`**：进程泄漏三信号（stdin EOF / SIGTERM / 孤儿 ppid→1）；会轮换的凭据必须收敛单实例；single-flight 刷新。
- **`docs/MCP_PROMPT_RULES.md`**：静态 vs 轮换凭据的架构分野；`--oauth` 模式 HTTP 层 401 在刷新逻辑之前（120 分钟被迫重登的坑）；信号处理器里绝不能 `proc.wait()`（重入 waitpid 卡死）。
- Lark 的 20038 = refresh_token 被并发刷新抢消费；Figma/ADO 用静态 PAT 不会互毁，但 stdio 多实例仍会泄漏进程，必须走 `proc_supervise`。
- TG 侧 MCP 菜单（主机器人）与 UI 共用同一进程单例，别自己再 fork。
