# AI 会话：终端 + Claude / Codex / Antigravity 结构化会话

## 这个能力做什么
桌面端「AI 会话」页（`next/desktop/src/features/ai`）统一管两类会话，都由后端 `AISessionService` 独占拥有子进程：
- **terminal**：PTY 真终端，跑 profile 的 `command`（前端 xterm.js 渲染，WebSocket 收发）。
- **chat**：结构化 headless 会话，支持 Claude / Codex / Antigravity(agy)，事件落 SQLite，UI 与 Telegram AI 机器人共用同一套。
可从已结束会话续聊，或续聊 `~/.claude/projects` 里的旧 Claude 会话；工单页「AI 分析」会自动起 chat 会话并灌提示词。

## 关键文件（均在 `next/` 下）

| 做什么 | 文件 |
| --- | --- |
| 会话内核、profile/默认值、续聊、检查/升级 CLI、`agy models` | `backend/src/toolbox_backend/services/ai_sessions.py` |
| chat 会话状态机（轮次、中断、审批、超时） | `backend/src/toolbox_backend/services/ai_chat.py` |
| 工单分析提示词（只带工单号 + 库/项目名） | `backend/src/toolbox_backend/services/ai_prompt.py` |
| 三种 CLI 的 argv 与事件解析 | `backend/src/toolbox_backend/adapters/ai_cli/{claude,codex,agy,base}.py` |
| 子进程环境清洗、`SupervisedProcess` | `backend/src/toolbox_backend/adapters/ai_process.py` |
| PTY（2MB 字节偏移环形缓冲，终端字节不落盘） | `backend/src/toolbox_backend/adapters/pty_terminal.py` |
| 会话/事件/审批/进程 SQLite 日志 | `backend/src/toolbox_backend/adapters/ai_store.py` |
| 扫 Claude 历史会话（最多 50 个） | `backend/src/toolbox_backend/adapters/claude_history.py` |
| profile/默认值/权限档位模型 | `backend/src/toolbox_backend/domain/ai.py` |
| REST + 终端 WebSocket | `backend/src/toolbox_backend/api/ai_routes.py`、`ai_schemas.py` |
| TG AI 机器人（私聊菜单/向导/审批按钮） | `backend/src/toolbox_backend/services/telegram_ai.py` |
| 前端：会话页/新建/终端/聊天 | `desktop/src/features/ai/{AiSessionsPage,NewSessionSheet,TerminalView,ChatView}.vue` |
| 前端：AI CLI 配置 | `desktop/src/features/settings/AiCliTab.vue` |

## 三种 headless 协议（别照搬）
- **Claude**：每会话一个常驻进程，`--print --input-format/--output-format stream-json --permission-prompt-tool stdio`，stdin 按行喂 user 消息；工具审批走 `control_request(can_use_tool)`，UI/TG 点同意/拒绝回 `control_response`（审批 540s 过期，最多 8 条待决）。新会话后端自选 `--session-id`，续聊 `--resume`。权限档：acceptEdits/auto/bypassPermissions/manual/dontAsk/plan。空闲 4 小时回收。
- **Codex**：每轮一个 `codex exec --json … -`（prompt 走 stdin），首轮 `thread.started` 拿 thread_id，续聊 `codex exec resume <id>`；**resume 不传 `-s`/`-C`**（沙箱继承首轮，只有 danger 首轮会再带 bypass 标志）。沙箱：read-only / workspace-write / danger-full-access（后者用 `--dangerously-bypass-approvals-and-sandbox`）。Codex 无审批事件。
- **agy**：每轮一个 `agy --print --input-format stream-json --output-format stream-json`，解析 step_update（有工具/文本事件，不再是纯文本）；续聊用 `--conversation <id>`；模式 sandbox / plan（`--sandbox --mode plan`）/ auto（`--dangerously-skip-permissions`）。stdin 输入若快速失败会降级为 `--print=<prompt>` 并记 `prompt_visible_to_other_processes` 警告。

## 怎么用
- UI：AI 会话页「新建」选仓库 + profile + 模式；terminal 会话直接敲键盘；chat 会话发消息/中断/审批；续聊选已结束会话，或（Claude）从历史候选里选。
- 设置 → AI CLI：增删改 profile（`command`/`upgrade_command`）、默认模型/强度/权限、分析用权限、检查/升级 CLI（后台 job 可取消）、agy 模型列表（`agy models`，缓存 10 分钟）。
- TG：专属 AI 机器人里发消息即多轮对话（见 telegram-control 页）。

## 注意与坑
- 并发上限：chat、terminal 各最多 6 个活跃会话；同一 CLI 最多 4 个进程，超出报 `ai_session_limit`。
- 高权限（Claude bypassPermissions、Codex danger-full-access、agy auto）需 `ack_high_risk` 再确认，否则 409。
- 子进程环境会剔除含 TOKEN/SECRET/PASSWORD/API_KEY 的变量和 `TOOLBOX_*`；Claude/Codex 复用本机已登录订阅，不需要 API key。
- 终端输出后端重启后无法恢复（不落盘）；单个终端最多 2 个 WebSocket 连接。
- 终端会话不支持续聊；`other` 类 profile 只能开终端。内置 profile id `codex`/`gemini`/`claude_code` 保留（`gemini` 实为 agy，为不断旧机器人绑定）。
- 续聊候选目前只扫 Claude 历史（`resume_candidates` 不区分 CLI）；Codex/agy 只能续聊本应用里已结束且有 external_id 的会话。
- 未迁移：旧版 pyte 自绘终端/键盘注入、Claude 审批 hook 落盘桥（`cc_approval_hook`）——现改为 stream-json 内的 control_request。
