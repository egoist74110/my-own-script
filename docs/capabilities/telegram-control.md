# Telegram 控制与通知

## 这个能力做什么
应用运行时通过长轮询接收 Telegram 指令（跑任务/回滚/停止/状态/VPN/工单/AI 对话），并把任务结果推送到 TG。共 4 条轮询线程：1 个主机器人 + 3 个专属 AI 机器人。

## 关键文件

| 做什么 | 文件 |
| --- | --- |
| 轮询主循环、命令分发、ACL、inline 回调 | `app_ado/tg_control.py` |
| 发消息（sendMessage 封装） | `app_ado/notifier_telegram.py` |
| 主机器人命令集：任务/工单/服务/MCP | `app_ado/tg_control.py` `_handle` |
| AI 机器人命令集（`/cc`、`cc:*`、选项目续聊） | `app_ado/tg_control.py` `_handle_ai` |
| inline 键盘（停止/回滚/工单/帮助） | `app_ado/tg_stop_inline.py`、`tg_rollback_inline.py`、`tg_help_inline.py`、`tg_help_run_inline.py`、`tg_work_items_inline.py` |
| 工单 TG 桥 | `app_ado/tg_work_items_bridge.py` |
| 三个 AI headless TG 桥 | `app_ado/ai_headless_tg_bridge.py`、`codex_headless_tg_bridge.py`、`antigravity_headless_tg_bridge.py` |
| ACL 配置 UI | `app_ado/ui/telegram_acl_mixin.py`、`app_ado/ui/telegram_card.py` |
| 通知/Token 配置 UI | `app_ado/ui/communication_config_tab.py` |

## 命令
- 主机器人：`/help` `/start` `/menu` `/run <任务>`（任务身份=`tg_command`）、`/stop`（列可停→选一个）、`/status`、`/rollback`（选任务→选偏移）、`/cancelrollback`（取消待确认回滚动作）、`/vpn`、`/wi`、`/services`（或 `/svc`、`/service`）、`/mcp`、`/cc`（指引前往 Claude Code 专属机器人）、系统操作/服务/MCP 菜单（inline 回调）。
- 专属 AI 机器人（`mode="ai"`）：`/cc` 及 `cc:*` 子命令，与对应 headless 会话多轮对话；`/cancel` 等。
- ACL：`telegram_chat_id` 命中者 = owner；`telegram_acl_groups`/`members` 按 `task_ids` 授权非 owner 跑指定任务。TG 触发时结果只回触发者；UI 触发时推 owner。

## 4 条轮询线程（`app_main.py` 注册）
1. 主机器人：任务/工单/服务/MCP，token 取 `telegram_bot_token`（Keychain）。
2. `ai`（Claude）：`token_fn=get_ai_bot_token("claude_code")`，只跑 Claude headless 会话。
3. `codex_ai`：`get_ai_bot_token("codex")`，只跑 Codex 会话。
4. `antigravity_ai`：`get_ai_bot_token("gemini")`（内部 id 保留 gemini），只跑 agy 会话。

专属机器人没配 Token 时线程空转，不影响主机器人。

## 怎么改
- 新命令：在 `_handle`/`_handle_ai` 加分支；inline 交互参考 `tg_*_inline.py` 的 callback_data 约定。
- 改 ACL：`_resolve_acl` + `_can`（role/group/action/task_id）。
- 通知隐私：`telegram_notify_include_details` 默认 False（只发摘要）。

## 注意坑
- 轮询只在应用运行时存活；offset 持久化在 `~/.config/my-own-script/` 下的状态文件。
- Bot Token 只进 Keychain（`app_ado/secrets.py`），日志绝不输出 Token。
- 长轮询超时/断线是正常噪音，别当错误弹。
- 改 Telegram 相关文件属于 `config/ai_change_policy.yaml` 的 review/forbidden 路径，AI 改动需谨慎（见 `docs/AI_CHANGE_POLICY.md`）。

## 重写版 Token 校验与前端接入（2026-10-28）

- 主 Bot `PUT /api/telegram/token`、`POST /api/telegram/token/import-legacy`，以及 `/api/telegram/ai-bots/{ai_id}` 下对应接口，保存后立即只读调用 `getMe`、`getWebhookInfo`，总超时 10 秒。不会启动轮询、读取更新或删除 webhook。
- 新增 `POST /api/telegram/token/verify` 与 `POST /api/telegram/ai-bots/{ai_id}/token/verify`，请求体 `{revision}`，重新检查已保存 Token；未保存时返回 `no_credential`，旧 revision 返回 `revision_conflict`。
- 保存、导入、重新检查响应为原 mutation 字段加 `verify: {ok, code, message, has_webhook, checked_at}`。校验失败仍返回 HTTP 200，Token 保持已保存；前端必须检查 `verify.ok`，并使用响应中的最新 `revision`。
- 错误码：`token_invalid`（401，文案“Token 无效或已被撤销”）；`telegram_unreachable`（网络或超时）；`telegram_request_failed`（其他 Telegram 错误或响应异常）。不透传远端错误描述或 webhook URL。
- 配置新增服务端管理字段：主 Bot `telegram.control.verified_bot`、`token_verify`；AI Bot `ai.bots.{ai_id}.verified_bot`、`token_verify`。身份为 `{id, username, first_name, verified_at}`，id 为字符串，username 不含 `@`。均默认 null，无需升级 schema 版本。
- 主 overview、AI Bot 详情及列表的 `bot.bot_id`、`bot.username` 优先返回已验证身份；另有 `bot.verified_bot` 和 `bot.verify`，control 也返回持久化字段。前端显示账号时补 `@`，使用 `bot.bot_id` 展示 Bot ID，不要用仍代表接管身份的 `control.bot_id`。
- 保存或导入后刷新 overview；`verify.ok=true` 且 `control.enabled=false` 时提示“Token 已验证，请启用远程控制”。`has_webhook=true` 时提示启用需确认删除 webhook，沿用 `delete_webhook` 参数。`verify.ok=false` 时显示 `message` 并提供“重新检查”。未校验的旧配置字段为 null，可以主动重新检查。
- 更换或删除 Token 会清空旧校验记录。相同 Token 重新检查失败时保留历史已验证身份，并返回最新失败结果；若 `getMe` 成功但 webhook 查询失败，仍保存此次身份，`has_webhook=null`，表示 webhook 状态未知。
- enable 使用其当次 `getMe` 更新接管身份和已验证身份，沿用原有冲突处理；disable/retry 状态机不变。本轮只交付后端和生成类型，前端提示与按钮需另行接入。


## 重写版分层菜单（2026-10-28）

主菜单为 🚀 发布 / 🛠 系统操作 / 📋 工单 / 🔌 服务 / 🧩 MCP，按权限裁剪；发布按配置→命令→动作→确认组织，回滚/停止/状态归系统操作。子页支持逐层返回、深层主菜单和原面板编辑。完整菜单树、权限边界、旧断言变更与真实验收见 [Telegram 分层菜单交付](telegram-menu-next.md)。
