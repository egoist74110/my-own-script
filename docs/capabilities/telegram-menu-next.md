# 重写版 Telegram 分层菜单（2026-10-28）

范围为 `next/backend`。主 Bot 使用发布配置与运行命令模型；ACL、运行记录继续以原命令 id 关联。没有配置迁移或执行协议变化，未修改 `next/desktop`，未提交、stash 或切换分支。

## 最终菜单树与按钮

```text
🧰 代码工具箱
运行中 N 个 / VPN 已连接·未连接·未知 / 远程控制已启用·未启用
├ 🚀 发布
│ └ 📦 配置名（N 个命令）
│   └ ▶️ 命令名
│     ├ 🚀 构建并发布 ─┐
│     ├ 📤 只发布 ────┴→ 预检确认
│     │                  ✅ 确认执行 / ✖️ 取消 / ⬅️ 返回 / 🏠 主菜单
│     ├ ↩️ 回滚 → ↩️ 回滚偏移 1 … ↩️ 回滚偏移 5 → 预检确认
│     └ 运行中时替换动作：⏹ 停止这次运行 / 📄 查看进度
├ 🛠 系统操作
│ ├ 📊 运行状态
│ ├ ⏹ 停止运行 → ⏹ 配置名：命令名（运行列表）
│ └ ↩️ 回滚 → 📦 配置名（N 个命令）→ ▶️ 命令名
│                                      → ↩️ 回滚偏移 1 … 5 → 预检确认
├ 📋 工单（仅 owner）
│ └ 📁 项目名 → 📋 版块名 → 📋 #编号 标题
│   ├ 📄 全文
│   ├ 🔗 关联项 → 📋 工单 #编号
│   ├ 🔍 AI 分析 → 📦 仓库名 → AI 名称 → ✅ 确认分析 / ✖️ 取消
│   └ 📋 复制提示词 → Claude 版 / Codex 版 / agy 版（显示其他两种）
├ 🔌 服务（仅 owner）
│ ├ ▶️ 启动 code-server / ⏹ 停止 code-server
│ ├ ▶️ 启动 全局隧道 / ⏹ 停止 全局隧道
│ │ └ 启动前：✅ 确认公开到公网
│ ├ ⏹ 停止自定义隧道
│ ├ ➕ 新增自定义隧道 → 输入地址 → ✅ 确认公开到公网
│ ├ 🔌 连接 VPN（VPN 服务可用时）
│ └ 🔄 刷新状态
└ 🧩 MCP（仅 owner）
  ├ ▶️ 启动 Lark MCP / ⏹ 停止 Lark MCP
  └ 🔄 刷新状态
```

- 主菜单没有返回。所有子页都有 `⬅️ 返回`；第二层回主菜单，深层回上一级并附 `🏠 主菜单`。工单全文/关联项回详情，详情回原版块列表；关联项进入的详情回关联项。
- 发布始终先选配置；配置、命令分别按 `(sort_order, id)` 排序。只列含当前用户可见、已启用命令的配置，超过 8 项显示 `⬅️ 上一页 / 下一页 ➡️`；返回保留发布列表的原页码。
- 确认页的 `✖️ 取消` 与 `⬅️ 返回` 均消费待确认 token，并回命令详情。确认仍复核实时 ACL、命令启用状态，使用冻结计划与单次 token。
- 命令详情显示分支、目标与环境；有状态权限时显示上次结果与相对时间。运行中只提供有权限的停止/进度按钮。
- 运行状态、进度需要 `can_status + task_ids`；停止需要 `can_stop + task_ids`，并保留“Telegram 来源且同 chat”的限制。run/rollback 继续分别检查原 `allowed()` 权限。各回调重新检查权限。
- 主菜单按权限裁剪；owner 固定五项，组成员不显示工单/服务/MCP。无可用项时提示联系管理员授权。摘要的运行数量按状态权限过滤。
- 导航回调携带原面板 message_id，使用 `editMessageText`；主面板编辑失败不降级另发菜单。初次文本命令打开面板、运行开始/结束通知仍发新消息。专属 AI Bot 的投递恢复逻辑保持。
- 过期/已消费菜单 token 提示 `菜单已过期，请重新 /start` 并附 `🏠 主菜单`；确认重复点击不会再次执行。计划本身过期仍提供 `🔄 重新预检`。
- `/start`、`/menu`、`/help` 打开主菜单；`/run <tg_command>` 及动态命令（如 `/deploy`）直达详情；`/status`、`/stop` 直达相应系统子页；`/rollback` 直达回滚配置列表。
- 菜单不展示配置/命令/运行内部 id；预检保留用于核对冻结制品的远端 Build/Release 版本信息。工单编号沿用现有业务展示。

## 改动文件

生产实现：

- `next/backend/src/toolbox_backend/services/telegram.py`：主菜单、摘要、状态入口、主 Bot 就地编辑、通知去内部运行 id。
- `next/backend/src/toolbox_backend/services/telegram_commands.py`：分发、确认返回、过期提示、停止权限、服务/MCP 图标与返回。
- `next/backend/src/toolbox_backend/services/telegram_menu.py`（新增）：配置/命令树、分页、详情、版本选择、进度、公共返回导航。
- `next/backend/src/toolbox_backend/services/telegram_work_items.py`：工单图标、父级导航与提示词面板编辑。

测试：新增 `tests/test_telegram_menu_tree.py`（27 项）；调整 `test_telegram_system_menu.py`、`independent/s4b/test_telegram_dispatch_s4b.py`、`test_s4b_execution.py`、`test_s4a_boundaries.py`、`test_s4b_regressions.py`、`test_s4b_security_lifecycle.py`、`test_s5c_wi.py`。路径均位于 `next/backend/`。

文档：本页、`docs/CAPABILITIES.md`、`docs/capabilities/telegram-control.md`、`docs/modernization/PROGRESS.md`。

## 旧测试断言变更清单

只适配新菜单结构与文案，保留执行次数、冻结计划、ACL、来源、脱敏和只读限制断言；既有用户改动不算本轮增量。

| 测试（原名称） | 本轮变更 |
| --- | --- |
| `test_owner_system_menu_shows_all_buttons_and_navigates_to_existing_pages` | 系统页按钮及顺序改为运行状态/停止运行/回滚/返回；回滚入口改配置层；主菜单标题改代码工具箱 |
| `test_group_member_system_menu_respects_permissions_without_widening` | 精确匹配新图标和系统按钮顺序；保留权限裁剪及伪造系统回调拒绝 |
| `test_cancelrollback_with_and_without_pending_rollback` | 增加配置后的命令选择；确认按钮加图标；保留取消后旧 token 不执行 |
| `test_task_menu_is_visible_only_to_members_with_run_permission` | `任务` 改 `🚀 发布` |
| `test_menu_actions_are_server_tokens_and_single_use` | 新发布入口及命令层，`构建发布` 改 `构建并发布`；保留 22 字符 token、未确认不启动、重复确认仅一次 |
| `test_expired_confirmation_action_replans_without_starting` | token 过期改精确过期提示与主菜单按钮；保留 starts 为空 |
| `test_deploy_only_requires_confirmation_and_starts_the_frozen_plan` | `仅发布` 改 `只发布`，冻结计划断言不变 |
| `test_rollback_preflight_freezes_selected_offset_before_confirmation` | 增加命令层，偏移/计划/确认安全断言不变 |
| `test_expired_preflight_plan_never_starts_and_returns_fixed_replan` | 构建按钮新文案，重新预检增加图标；保留固定错误/不泄漏细节 |
| `test_confirmation_rechecks_task_and_acl_before_start`（三参数） | 构建按钮新文案；禁用/删除/撤权安全断言不变 |
| `test_non_owner_stop_menu_and_callback_are_limited_to_own_chat` | fixture 明确授权 task_ids；用 token 的 run_id 精确断言只有 own00001，替代包含内部运行 id 的按钮文案 |
| `test_run_origin_preserves_stop_ownership_after_backend_restart` | fixture 明确授权 task_ids；按显示名称选按钮并校验其 token 指向原运行，保留重启来源与未知结果断言 |
| `test_full_real_execution_and_duplicate_confirmation`（三参数） | 构建/只发布新文案，回滚增加命令层；实际成功、来源、单次执行、触发者通知均保留 |
| `test_cancel_button_invalidates_unconsumed_confirmation` | 构建/确认新文案；取消后旧确认不能创建运行不变 |
| `test_confirmed_telegram_run_uses_only_temporary_bare_git` | 仅构建按钮文案；隔离 Git 安全断言不变 |
| `test_help_menu_callbacks_use_bound_one_time_server_tokens` | outbox 从 2 改 3：重复菜单 token 会给过期提示；增加精确提示断言，保留跨 chat/伪造不执行和 consumed_at |
| `test_read_only_group_has_no_task_menu` | 原无任务入口断言同步为无 `🚀 发布` |
| `test_task_command_offers_modes_before_any_run` | 精确按钮文案改 `🚀 构建并发布 / 📤 只发布`；不启动运行断言不变 |
| `test_expired_confirmation_still_prompts_after_another_menu_opens` | token 过期提示改为菜单过期；保留另开菜单不吞掉过期回复 |
| `test_analysis_chain_without_ai_bot_is_desktop_only` | 将新返回/主菜单按钮独立断言，其余 AI 选项仍逐项断言“仅桌面可见” |
| `test_copy_prompt_is_plain_text_without_body` | 两个 CLI 按钮加两个导航按钮，仍断言恰好两个 CLI 选项；纯文本/内容断言不变 |

## 真实验收

施工运行时实际型号/档位无法验证，记 `unknown`。按仓库规范委派一层原生测试子 agent `/root/menu_tests`，仅新增测试文件；施工者接管后补 3 项辅助导航测试并验收最终版本。没有真实 TG/ADO/Keychain 或桌面人工验收。

指定命令（在 `next/backend`）：

```bash
UV_CACHE_DIR=/Users/wesker/my-own-script-next/next/.local/uv-cache uv run pytest -q tests/test_telegram_menu_tree.py tests/test_telegram_system_menu.py tests/independent/s4a tests/independent/s4b tests/test_s4b_execution.py tests/test_s4_lead_fixes.py tests/test_s4a_foundation.py tests/test_s4a_boundaries.py
```

真实输出：

```text
........................................................................ [ 50%]
......................................................................   [100%]
142 passed in 16.27s
```

相邻回归（S4 安全/生命周期、S5 工单 AI、VPN、服务 owner）：除下面保留失败项外，`43 passed, 1 deselected in 28.23s`。保留失败项 `tests/test_s5c_wi.py::test_analysis_routes_output_to_enabled_ai_bot` 连续两次等待 AI 机器人完成输出超时；单独复现 `1 failed in 16.23s`。测试库记录 `ai_sessions.state=failed, ended_reason=start_failed`，事件仅 starting→failed；会话创建及主 Bot 路由断言已通过。未删除/跳过其安全断言，未修改 AI 执行器，原因尚未定位；不能据此宣称相邻全量通过，也未无证据归因为沙箱端口限制。

改动 Python 文件 ruff 检查通过；`git diff --check` 通过。指定集合没有端口类失败。日志保留于 Git 忽略的 `next/.local/telegram-menu/`；临时 `/tmp/telegram-menu-*.log` 已移除。无任务常驻进程或新增监听端口，测试资源按 fixture 回收。
