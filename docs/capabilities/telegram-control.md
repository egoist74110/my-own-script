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
- 主机器人：`/help` `/menu` `/run <任务>`（任务身份=`tg_command`）、`/stop`（列可停→选一个）、`/status`、`/rollback`（选任务→选偏移）、`/vpn`、`/wi`、服务与 MCP 菜单（inline 回调）。
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
