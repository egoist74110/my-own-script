# Telegram 控制与通知

## 这个能力做什么
应用运行时，后端用 Bot Token 轮询 Telegram（`getUpdates`，只收 message/callback_query），接收指令（发布/回滚/停止/状态/VPN/工单/服务/MCP）并推送任务结果。共 4 个槽位：1 个主 Bot（`main`）+ 3 个专属 AI Bot（`ai:claude_code`、`ai:codex`、`ai:gemini`），每个独立 Token、独立启停；AI Bot 只与对应 AI 会话多轮对话。本页不含菜单树，详见 [Telegram 分层菜单](telegram-menu-next.md)。

## 关键文件（均在 `next/`）

| 做什么 | 文件 |
| --- | --- |
| 配置/Token/启停/owner 绑定/ACL/测试消息/活动 HTTP 接口 | `backend/src/toolbox_backend/api/telegram_routes.py`、`api/telegram_schemas.py` |
| 轮询、Token 校验、ACL 解析、通知队列与发送、owner 绑定 | `backend/src/toolbox_backend/services/telegram.py` |
| 主 Bot 命令分发与权限（run/stop/rollback/vpn/wi/mcp/services） | `backend/src/toolbox_backend/services/telegram_commands.py` |
| 分层菜单 | `backend/src/toolbox_backend/services/telegram_menu.py` |
| 工单 TG 菜单 | `backend/src/toolbox_backend/services/telegram_work_items.py` |
| AI 专属 Bot：会话向导、聚焦、审批、事件投影 | `backend/src/toolbox_backend/services/telegram_ai.py` |
| Telegram HTTP 客户端 / 本地状态库（`telegram.sqlite3`：offset、更新、发件箱、按钮令牌） | `backend/src/toolbox_backend/adapters/telegram_http.py`、`adapters/telegram_store.py` |
| 配置模型（Control/Owner/Notify/ACL） | `backend/src/toolbox_backend/domain/telegram.py` |
| 测试用假 Telegram | `backend/src/toolbox_backend/adapters/fake_telegram.py` |
| 桌面设置页（Token、启用、ACL、AI Bot） | `desktop/src/features/settings/TelegramTab.vue`、`TelegramAiBotsCard.vue`、`TelegramEnableSheet.vue`、`TelegramGroupEditSheet.vue`、`TelegramMemberEditSheet.vue` |

## 命令与权限
- 主 Bot：`/help` `/start` `/menu`、`/run [<tg_command>]`、`/<tg_command>`（命令自带的 TG 指令）、`/status`、`/stop`、`/rollback`、`/cancelrollback`、`/vpn [动作]`、`/wi`、`/services`（`/svc`、`/service`）、`/mcp`、`/cc`（指向 AI Bot）、`/bind <6 位码>`。其中 `/vpn` `/wi` `/mcp` `/services` 仅 owner。
- AI Bot：`/start` `/help` `/menu` `/cc` 打开会话菜单，其余 `/` 命令一律忽略；纯文本按回复关系或当前聚焦会话发给 AI；仅识别私聊 owner。
- **角色**：owner（私聊 chat_id 命中）、group（ACL 成员）、legacy（旧白名单：可看菜单与状态）、none（零回复）。ACL 组带 `can_run/can_stop/can_status/can_rollback` 和 `task_ids`，非 owner 仅可操作所列命令；停止只能停自己（同 chat）从 TG 发起的运行。
- **owner 绑定**：桌面生成 10 分钟有效的 6 位绑定码（`POST /api/telegram/owner/bind-code`），在 Bot 私聊发 `/bind <码>`；错 5 次作废。发送超过 5 分钟的 `/` 指令按过期处理。
- **通知**：run 进入 running/succeeded/failed/cancelled/unknown/manual_required 时发一条；TG 发起的回给发起者，桌面发起的推 owner（`notify.ui_runs_to_owner`）；`notify.include_details` 默认 false（只发摘要，链接和 URL 被隐藏）。发件箱落库，重启后补发。

## Token 与启用
- `PUT /api/telegram/token`、`/token/import-legacy`、`/token/verify`（AI Bot 在 `/api/telegram/ai-bots/{ai_id}/…`）：保存后只读调用 `getMe`、`getWebhookInfo`，响应带 `verify: {ok, code, message, has_webhook, checked_at}`；失败仍 HTTP 200、Token 保持已保存，前端须检查 `verify.ok`。错误码 `token_invalid`/`telegram_unreachable`/`telegram_request_failed`，不透传远端描述。
- 启用 `control/enable`：若存在 webhook 需显式 `delete_webhook` 确认；`disable`/`retry` 管理轮询状态。接管身份与已验证身份见 `control.verified_bot`，前端展示用响应里的 `bot.*`。
- Token 存 Keychain（账号 `telegram_bot_token`、`ai_bot_token:<ai_id>`），见 [配置与密钥](config-and-secrets.md)。

## 注意与坑
- 轮询只在后端运行且已启用时存活；offset/基线保存在 `telegram.sqlite3`，启用时先建基线丢弃积压，避免重放旧指令。
- 日志、状态、回发用户的异常文本经 `redact_exception` 脱敏；Token 绝不入日志。
- 改 Telegram 相关文件的 AI 改动策略见 `docs/AI_CHANGE_POLICY.md`。
- **已变**：旧 4 线程模型改为 4 个槽位统一管理；`telegram_chat_id` / `telegram_acl_*` 不再读 `ui_settings.yaml`，旧配置经导入进入新配置，见 [配置与密钥](config-and-secrets.md)。
