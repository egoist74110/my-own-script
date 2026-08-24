# AI 开发：终端会话 + Claude / Codex / Antigravity headless

## 这个能力做什么
「AI开发」Tab 本地跑 AI CLI 会话（PTY 真终端），另有一套「headless 结构化会话」供 Telegram 远程对话：Claude（常驻 stream-json 多轮）、Codex（每轮一个 `codex exec --json` 进程 + resume）、Antigravity/agy（每轮一个 `agy --print` 纯文本进程 + conversation 续聊）。

## 关键文件

| 做什么 | 文件 |
| --- | --- |
| AI开发 Tab（运行按钮/会话列表/自绘终端/键盘注入） | `app_ado/ui/ai_dev_tab.py` |
| PTY 多会话（pyte 虚拟屏、5000 行回滚、send_key/resize） | `app_ado/ai_dev_session.py` |
| 终端渲染组件 | `app_ado/ui/ai_dev_terminal.py` |
| 选仓库对话框 | `app_ado/ui/ai_dev_repo_dialog.py` |
| Claude headless（stream-json、逐条工具事件、审批） | `app_ado/ai_headless_session.py` |
| Claude 审批 hook + TG 审批桥（落盘监听线程） | `app_ado/cc_approval_hook.py`、`app_ado/ai_headless_tg_bridge.py` |
| Codex headless（thread/turn/item 事件、沙箱三档） | `app_ado/codex_headless_session.py`、`app_ado/codex_headless_tg_bridge.py` |
| Antigravity headless（cwd→conversation_id 续聊） | `app_ado/antigravity_headless_session.py`、`app_ado/antigravity_headless_tg_bridge.py` |
| 扫 `~/.claude/projects` 选项目/续聊旧会话 | `app_ado/claude_sessions.py` |
| AI CLI profile 配置（内置 codex/gemini/claude_code） | `app_ado/ui/ai_config_tab.py`、`app_ado/models.py`（`AiCliProfile`） |

## 三种 headless 的协议差异（别照搬）
- **Claude**：常驻进程，stdin 按行喂 `{"type":"user",...}`，stdout 读结构化事件；复用本机已登录订阅 OAuth（无需 API key）；会话落 `~/.claude/projects/<encoded-cwd>/<id>.jsonl` 供 `--resume`。
- **Codex**：每轮一个进程：`codex exec --json -C cwd "<prompt>"`，首轮从 `thread.started` 拿 thread_id，续聊 `codex exec resume <thread_id>`；**resume 不接受 `-s`**（沙箱继承首轮）；沙箱档位：read-only / `--full-auto` / `--dangerously-bypass-approvals-and-sandbox`。
- **agy**：每轮 `agy --print` 只回最终纯文本（无工具/思考事件）；按 cwd 归档会话（`~/.gemini/antigravity-cli/cache/last_conversations.json`），续聊用 `--conversation <id>`（别用 `--continue`，多会话会串）；两档都带 `--dangerously-skip-permissions`，否则 print 模式卡权限弹窗。

## 怎么用
- UI：AI开发 Tab 选仓库 + 点运行按钮 → PTY 终端直接敲键盘；会话列表可删。
- TG：各 AI 专属机器人里直接发消息即多轮对话（详见 telegram-control）；工单 Tab 的「MCP 分析」会自动起对应 headless 会话并灌提示词。
- 命令可执行名：AI配置 Tab 里 profile 的 `command`（agy 只取第一个词，沙箱参数由会话自补）。

## 注意坑
- PTY 会话仅 POSIX（macOS/Linux），Windows 不支持 fork+pty。
- Claude/Codex 都复用本机已登录订阅，**不需要 API key**；没登录就起不来。
- 退出清理：`aboutToQuit` 统一 shutdown（`app_main.py` 第 248 行），新增会话管理器要挂进去。
- 内置 profile id `codex`/`gemini`/`claude_code` 不可删（改名/改命令可以）；`gemini` 内部 id 保留是为不断老用户的机器人绑定。
