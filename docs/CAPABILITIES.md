# 能力索引（CAPABILITIES）

本仓库 = **代码工具箱**（macOS 桌面应用 v1.0.0，代码在 `next/`）。本文件是**能力索引**：想做什么 → 在下表定位能力行 → 进「详细文档」按里面的文件路径动手。后端根路径 `next/backend/src/toolbox_backend/`，下表简写为 `be/`；前端 `next/desktop/src/`，简写为 `fe/`。

## 能力清单

### 应用核心（运行 / 打包 / 发布 / 更新）

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 本机构建安装 | 一键构建（ad-hoc）→ 退出旧进程 → 替换 `/Applications/代码工具箱.app` | `next/scripts/install_local.sh`、`build_app.sh` | [packaging-release](capabilities/packaging-release.md) |
| 打包 DMG / zip、签名、公证 | 校验脚本、DMG、更新包；Developer ID 与公证流程待真实证书 | `next/scripts/*.sh` | [packaging-release](capabilities/packaging-release.md) |
| 应用内更新器 | Tauri updater：校验签名、可取消、协调关闭后重启 | `next/desktop/src-tauri/src/updater.rs` | [packaging-release](capabilities/packaging-release.md) |
| 版本号 | 单一来源 `tauri.conf.json`，`sync_version.py` 同步 | `next/scripts/sync_version.py` | [packaging-release](capabilities/packaging-release.md) |

### 发布与任务（同步 / 构建 / 发布 / 回滚）

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 发布配置与运行命令 | 仓库→分支→目标→命令模型，v8 迁移，兼容任务视图 | `be/api/release_routes.py`、`be/services/releases.py` | [release-configs-next](capabilities/release-configs-next.md) |
| 发布配置自动发现 | 只读发现仓库/分支/目标/队列，供向导使用 | `be/api/release_discovery_routes.py`、`fe/features/tasks/ReleaseWizardSheet.vue` | [release-configs-next](capabilities/release-configs-next.md) |
| 任务执行 / 回滚 / 停止 | git 同步→构建→发布，多目标串行失败即停，运行记录与增量事件 | `be/api/task_routes.py`、`be/services/runs.py`、`be/services/tasks.py` | [ado-pipeline](capabilities/ado-pipeline.md) |

### 工单

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 工单看板 / 详情 / 分析 | 按项目/看板列浏览工单，详情/评论，交给 AI 分析 | `be/services/work_items.py`、`fe/features/work-items/` | [work-items](capabilities/work-items.md) |

### Telegram 控制

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 指令、ACL、通知、AI 机器人 | 主 Bot + 专属 AI Bot，Token 保存后只读校验 | `be/services/telegram.py`、`telegram_commands.py` | [telegram-control](capabilities/telegram-control.md) |
| 分层菜单 | 发布配置→命令→预检；系统操作；权限裁剪、就地编辑 | `be/services/telegram_menu.py` | [telegram-menu-next](capabilities/telegram-menu-next.md) |

### AI 开发

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| AI 会话 | 终端 / Claude / Codex / Antigravity 会话、续聊旧会话、CLI 配置 | `be/services/ai_sessions.py`、`be/api/ai_routes.py`、`fe/features/ai/` | [ai-dev](capabilities/ai-dev.md) |

### MCP 服务（ADO / 飞书 / Figma）

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| MCP 托管 | ADO 工单 MCP、飞书 Lark MCP、Figma MCP 的启停、凭据与接入配置 | `be/services/mcp.py`、`be/mcp/` | [mcp-servers](capabilities/mcp-servers.md) |

### VPN（Harmony SASE）

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 连接自愈 / 远程登录 / TOTP | 检测→重开→重登阶梯、Playwright 登录、本地 TOTP | `be/services/vpn.py`、`be/vpn/`、`be/adapters/vpn_*.py` | [vpn](capabilities/vpn.md) |

### 服务管理

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| code-server / cloudflared / dsh | 进程启停、状态与日志、隧道与网关 | `be/services/services.py`、`be/adapters/service_runtime.py` | [services](capabilities/services.md) |

### 配置、密钥与改动策略

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 配置存储与旧配置迁移 | 版本化配置、原子迁移与备份、旧应用配置导入 | `be/adapters/config_store.py`、`legacy_config.py` | [config-and-secrets](capabilities/config-and-secrets.md) |
| Keychain 密钥 | PAT / Bot Token / VPN / OTP 只存 Keychain | `be/adapters/credentials.py` | [config-and-secrets](capabilities/config-and-secrets.md) |
| 改动准入策略 | MCP 创建工单前评估 allow/review/deny | `be/mcp/policy.py` | [ai-collab-rules](capabilities/ai-collab-rules.md) |

### 开发 / 测试 / 历史

| 能力 | 一句话说明 | 入口/关键文件 | 详细文档 |
| --- | --- | --- | --- |
| 开发运行与测试 | 后端 pytest、前端 vitest/typecheck、Rust、脚本测试、契约生成 | `next/backend/`、`next/desktop/` | [dev-and-tests](capabilities/dev-and-tests.md) |
| 重构历史与架构决策 | 为何这样分层、切片历史、设计探索 | `docs/modernization/` | [modernization](capabilities/modernization.md) |

## 常用操作速查

```bash
bash next/scripts/install_local.sh --open     # 本机构建并安装（ad-hoc）
cd next/backend && uv run pytest -q           # 后端测试
cd next/desktop && pnpm test                  # 前端测试
```

**新增能力时的落点**：业务 → `next/backend/src/toolbox_backend/`（api/services/adapters/domain 分层）；界面 → `next/desktop/src/features/`；密钥 → Keychain（`adapters/credentials.py`）；改接口后重新生成契约；**别忘了**在本索引加一行 + `docs/capabilities/` 补一页。涉及 ADO/发布的改动先读 [SECURITY](SECURITY.md) 与 [AI_CHANGE_POLICY](AI_CHANGE_POLICY.md)。

## 状态备注

- 发布构建为 ad-hoc 签名，未做 Developer ID 签名与公证，仅供私有使用；真实签名/公证与更新源见 [packaging-release](capabilities/packaging-release.md)。
- 旧 PySide6 应用（v0.1.x）与其 ok-script 框架已在 v1.0.0 移除，源码在 git 历史（`885d186` 及之前）。
