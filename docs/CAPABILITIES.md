# 能力索引（CAPABILITIES）

本仓库 = **代码工具箱**（macOS PySide6 桌面应用，`app_main.py`）+ **ok-script**（图像识别自动化框架，`ok/`）。本文件是**能力索引**：想做什么 → 在下表定位能力行 → 进「详细文档」按里面的文件路径动手。

## 能力清单

### 应用核心（运行 / 打包 / 发布 / 更新）

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 应用入口与选项卡 | 9 个 Tab 的单窗口 Fluent 应用，启动拉起 TG/更新线程 | `app_main.py` | [app-core](capabilities/app-core.md) |
| 本地运行 | 一键 git pull + 建 venv + 装依赖 + 启动 | `dev_run.sh` | [packaging-release](capabilities/packaging-release.md) |
| 打包 .app / .dmg | sips 图标 + wrapper app + hdiutil 打 dmg 到 `dist/` | `pack_mac_app.sh`、`pack_mac_dmg.sh` | [packaging-release](capabilities/packaging-release.md) |
| 发布到 GitHub Releases | gh CLI 建 tag、上传 dmg，供应用内更新 | `release_github.sh` | [packaging-release](capabilities/packaging-release.md) |
| 应用内自更新 | 启动 git 检查（ff pull+重启）+ 设置页 GitHub DMG 更新 | `app_ado/updater.py`、`app_ado/release_updater.py`、`app_ado/app_installer.py` | [packaging-release](capabilities/packaging-release.md) |
| 版本号管理 | 4 段版本，pre-commit 每 commit 自动 +1 第 4 段 | `app_version.py`、`app_ado/versioning.py`、`scripts/bump_version.py`、`.githooks/pre-commit` | [packaging-release](capabilities/packaging-release.md) |

### ADO 流水线（同步 / 构建 / 发布 / 回滚）

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 任务执行（git 同步→构建→发布） | 动态任务 CRUD，多目标串行、失败即停，构建实例智能匹配 | `app_ado/ui/tasks_tab.py` | [ado-pipeline](capabilities/ado-pipeline.md) |
| 只发布 / 回滚 / 停止 | 跳过构建只发 Release、回滚 N 版本、毫秒级响应式停止 | `app_ado/ui/tasks_tab.py`（`deploy_only_task`/`rollback_task`/`stop_one_task`） | [ado-pipeline](capabilities/ado-pipeline.md) |
| 构建 API | Pipelines 与 Build Definitions 触发/查询/等待/取消、agent 池覆盖 | `app_ado/ado_build_http.py`、`app_ado/ado_build_query.py` | [ado-pipeline](capabilities/ado-pipeline.md) |
| 发布 API | 建 Release、自动启动 notStarted 环境、监控 stages | `app_ado/ado_release_http.py` | [ado-pipeline](capabilities/ado-pipeline.md) |
| Git 合并（本地/远程 PR） | 本地 `git merge`（失败自动 abort+reset）或 ADO PR 远程合并 | `app_ado/ado_git_ops.py` | [ado-pipeline](capabilities/ado-pipeline.md) |

### 工单

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 工单 UI（看板浏览/详情） | 按项目/看板列列工单，看详情/评论/子项 | `app_ado/ui/work_items_tab.py`、`app_ado/ado_work_item_http.py` | [work-items](capabilities/work-items.md) |
| TG 工单菜单 | `/wi` 选项目→选列→列表→详情（仅 owner） | `app_ado/tg_work_items_bridge.py` | [work-items](capabilities/work-items.md) |
| 工单 MCP 分析 | 选仓库选 AI → headless 会话自动灌分析提示词 | `app_ado/ai_work_item_flow.py` | [work-items](capabilities/work-items.md) |
| ADO 工单 MCP server | stdio server：查询/详情/评论/附件/创建/策略评估 8 个工具 | `app_ado/mcp_ado_work_items_server.py` | [work-items](capabilities/work-items.md)、[ADO_MCP_QUICKSTART](ADO_MCP_QUICKSTART.md) |

### Telegram 控制

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 指令控制 | `/run` `/stop` `/status` `/rollback` `/vpn` `/wi` + 动态任务命令 | `app_ado/tg_control.py` | [telegram-control](capabilities/telegram-control.md) |
| ACL 授权 | owner + 组/成员按 task_ids 授权，TG 触发只回触发者 | `app_ado/tg_control.py`（`_resolve_acl`/`_can`） | [telegram-control](capabilities/telegram-control.md) |
| 通知 | 任务摘要推送，可选「包含细节」 | `app_ado/notifier_telegram.py` | [telegram-control](capabilities/telegram-control.md) |
| 专属 AI 机器人 ×3 | claude/codex/agy 各走独立 Bot Token 轮询线程 | `app_main.py` + 三个 `*_headless_tg_bridge.py` | [telegram-control](capabilities/telegram-control.md) |

### AI 开发（终端会话 / Claude / Codex / Antigravity headless）

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 本地终端会话 | PTY 多会话 + pyte 虚拟屏，真终端可敲键盘 | `app_ado/ui/ai_dev_tab.py`、`app_ado/ai_dev_session.py` | [ai-dev](capabilities/ai-dev.md) |
| Claude headless | 常驻 stream-json 多轮，逐条工具审批（落盘监听） | `app_ado/ai_headless_session.py`、`app_ado/ai_headless_tg_bridge.py` | [ai-dev](capabilities/ai-dev.md) |
| Codex headless | 每轮 `codex exec --json` + resume，沙箱三档 | `app_ado/codex_headless_session.py`、`app_ado/codex_headless_tg_bridge.py` | [ai-dev](capabilities/ai-dev.md) |
| Antigravity headless | 每轮 `agy --print` 纯文本，cwd→conversation 续聊 | `app_ado/antigravity_headless_session.py`、`app_ado/antigravity_headless_tg_bridge.py` | [ai-dev](capabilities/ai-dev.md) |
| 续聊旧 Claude 会话 | 扫 `~/.claude/projects` 选项目/选 session | `app_ado/claude_sessions.py` | [ai-dev](capabilities/ai-dev.md) |
| AI CLI 配置 | profile（命令/升级命令）、内置 codex/gemini/claude_code | `app_ado/ui/ai_config_tab.py` | [ai-dev](capabilities/ai-dev.md) |

### MCP 服务（ADO / 飞书 / Figma）

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| MCP配置 Tab | 三张卡片统一托管：配凭据/启停/token 状态/复制接入配置 | `app_ado/ui/mcp_config_tab.py` | [mcp-servers](capabilities/mcp-servers.md) |
| ADO 工单 MCP | stdio 单例进程（UI 与 TG 共用） | `app_ado/mcp_server_manager.py` | [mcp-servers](capabilities/mcp-servers.md) |
| 飞书 Lark MCP | 共享 streamable HTTP 单实例 + OAuth 托管（根治 20038） | `app_lark/mcp_server_manager.py` | [mcp-servers](capabilities/mcp-servers.md) |
| Figma MCP | stdio wrapper exec 官方 figma-developer-mcp，PAT 存 keychain | `app_figma/mcp_figma_server.py` | [mcp-servers](capabilities/mcp-servers.md) |
| 进程监督/孤儿回收 | stdin EOF/SIGTERM/孤儿三信号自杀，防 stdio 进程泄漏 | `app_lark/proc_supervise.py` | [mcp-servers](capabilities/mcp-servers.md) |

### VPN（Harmony SASE）

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 连接自愈 | 档0/A/B/C 阶梯：检测→重开→重启 app→SSO 重登 | `app_ado/vpn_control.py` | [vpn](capabilities/vpn.md) |
| 远程自动登录 | Playwright + 系统 Chrome 持久 profile + CDP 截深链 + MFA | `app_ado/vpn_login.py` | [vpn](capabilities/vpn.md) |
| TOTP | Ente 导出抽种子存 keychain，本地 pyotp 算码 | `app_ado/vpn_totp.py` | [vpn](capabilities/vpn.md) |
| 点掉更新提示 | 截屏 + Vision OCR + Quartz 点击（AX 对 Harmony 无效） | `app_ado/vpn_update.py` | [vpn](capabilities/vpn.md) |

### 服务管理

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| code-server / cloudflared 启停 | detached 进程 + 状态落盘 + 端口/签名扫描双兜底 | `app_ado/services_panel.py`、`app_ado/ui/services_tab.py` | [services](capabilities/services.md) |

### 配置与密钥存储

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| YAML 配置 + 模型 | `~/.config/my-own-script/` 下 ui_settings/tasks，pydantic 校验 + 自动迁移 | `app_ado/store.py`、`app_ado/models.py` | [config-and-secrets](capabilities/config-and-secrets.md) |
| Keychain 密钥 | PAT/Bot Token/VPN/OTP 全部 keyring 存取，绝不落明文 | `app_ado/secrets.py` | [config-and-secrets](capabilities/config-and-secrets.md) |
| ADO PAT 发现流程 | Basic 认证 + httpx 后台线程 + 下拉填充 + 错误弹窗 | `docs/ADO_PAT_DISCOVERY_FLOW.md` | [config-and-secrets](capabilities/config-and-secrets.md) |

### AI 协作规则（config 模板 + AI_CHANGE_POLICY）

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 改动准入策略 | 改代码前评估 allow/review/deny（类型/关键词/禁止路径） | `config/ai_change_policy.yaml`、`app_ado/ai_policy.py` | [ai-collab-rules](capabilities/ai-collab-rules.md) |
| 多模型协作模板 | Claude/Codex/Gemini 三套协作规范（Flash gate 等），可复制 | `config/model_collaboration_templates/` | [ai-collab-rules](capabilities/ai-collab-rules.md) |

### ok-script 框架

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 图像识别自动化框架 | 纯 Python，Windows/模拟器/ADB：截图/模板匹配/OCR/UI/浮层/打包 | `ok/`（独立 vendored 框架） | [ok-script](capabilities/ok-script.md) |

### 开发 / 测试

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 开发运行与测试 | `dev_run.sh` 一键跑；`pytest` 覆盖版本/迁移/ok | `dev_run.sh`、`pytest.ini`、`tests/` | [dev-and-tests](capabilities/dev-and-tests.md) |
| 新增能力落点约定 | 代码落对应模块 + 索引补一行/一页 + 密钥走 Keychain | `AGENTS.md` 红线 | [dev-and-tests](capabilities/dev-and-tests.md) |

## 常用操作速查

```bash
bash dev_run.sh                        # 本地开发运行（pull + venv + 依赖 + 启动）
bash pack_mac_app.sh                   # 打包 dist/代码工具箱.app
bash pack_mac_dmg.sh                   # 打包 dist/代码工具箱-<版本>-mac.dmg
VERSION=x.y.z bash release_github.sh   # 发布到 GitHub Releases（需 gh CLI）
.venv/bin/python scripts/bump_version.py   # 手动改版本号（正常由 pre-commit 自动 +1）
pytest                                 # 跑测试
```

**新增能力时的落点**：代码 → `app_ado/`（或 `ok/`/`app_figma/`/`app_lark/`）；密钥 → `app_ado/secrets.py`（Keychain）；非密配置 → `app_ado/models.py`；**别忘了**在本索引表加一行 + `docs/capabilities/` 补一页。涉及 ADO/发布的改动先读 `SECURITY.md` 与 `AI_CHANGE_POLICY.md`。

## 状态备注（诚实标注）

- `app_figma/` 与 `app_lark/` **不是独立顶层选项卡**，但**已接入 UI**：由 MCP配置 Tab（`app_ado/ui/mcp_config_tab.py`）的三张卡片托管（ADO/Lark/Figma），见 [mcp-servers](capabilities/mcp-servers.md)。
- `pytest.ini` 声明了 `integration` testpath，但当前仓库没有该目录（`tests/` 正常跑）。
- 上游 ok-script 目标 Python 3.12/Windows；本仓库工具箱跑 Python 3.14，macOS 上只用其 UI 层。
