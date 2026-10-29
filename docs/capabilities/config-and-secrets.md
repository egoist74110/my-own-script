# 配置与密钥存储

## 这个能力做什么
非密配置统一存进数据目录下的单个 `config.json`（带 `revision` 乐观并发和 `schema_version` 迁移）；所有敏感凭据只进 macOS Keychain（`keyring`，service=`toolbox-next`）。ADO PAT 从 Keychain 取，驱动项目/仓库/分支/构建/发布发现；旧 PySide6 版配置（`~/.config/my-own-script/` 下的 YAML）通过「导入」一次性读入。

## 关键文件（均在 `next/`）

| 做什么 | 文件 |
| --- | --- |
| 配置文件读写：原子写（0600、fsync、`os.replace`）、flock、revision 校验、启动时迁移 | `backend/src/toolbox_backend/adapters/config_store.py` |
| 全部配置模型（`Config` v8：ado/tasks/telegram/ai/mcp/vpn/services/credentials/import） | `backend/src/toolbox_backend/domain/settings.py` 及同目录 `telegram.py`、`ai.py`、`mcp.py`、`services.py`、`vpn.py`（各自的版本迁移函数） |
| Keychain 存取（`KeyringCredentials`）与旧版只读源（`KeyringLegacySource`，service=`my-own-script`） | `backend/src/toolbox_backend/adapters/credentials.py` |
| 读取旧 YAML（只读 4 个文件）并换算成新配置 | `backend/src/toolbox_backend/adapters/legacy_config.py` |
| 设置服务：库/项目/本地仓库 CRUD、PAT 存删、连接测试、导入预览/执行/拒绝、孤立凭据清理 | `backend/src/toolbox_backend/services/settings.py` |
| 设置 HTTP 接口（`/api/settings`、`/api/ado*`、`/api/credentials*`） | `backend/src/toolbox_backend/api/settings_routes.py`、`api/settings_schemas.py` |
| 数据目录/旧配置目录等运行时设置 | `backend/src/toolbox_backend/settings.py` |
| 日志脱敏与密钥登记 | `backend/src/toolbox_backend/logging_setup.py` |
| 桌面设置页（ADO 库/项目、本地仓库、凭据、导入） | `desktop/src/features/settings/AdoTab.vue`、`LibraryPanel.vue`、`ProjectPanel.vue`、`LocalReposTab.vue`、`CredentialsTab.vue`、`ImportTab.vue`、`useSettings.ts` |
| 安全说明（PAT 最小权限） | `docs/SECURITY.md` |

## 存储布局
- 数据目录：默认 `~/Library/Application Support/toolbox-next`，可用 `TOOLBOX_DATA_DIR` 覆盖；内含 `config.json`、`runs.sqlite3`、`telegram.sqlite3`、`migrations/`（升级前备份）、`import/`（导入时的旧文件快照）。
- 旧配置目录：默认 `~/.config/my-own-script`，可用 `TOOLBOX_LEGACY_CONFIG_DIR` 覆盖；只读取 `ui_settings.yaml`、`tasks.yaml`、`lark_settings.yaml`、`figma_settings.yaml`，不会修改。
- 发布配置/命令的字段见 [发布配置](release-configs-next.md)。

## Keychain 账号一览（service=`toolbox-next`）
| account | 用途 |
| --- | --- |
| `ado_pat:<library_id>` | ADO PAT（每个库一个） |
| `telegram_bot_token`、`ai_bot_token:<ai_id>` | 主 Bot / 各 AI 专属 Bot |
| `lark_app_secret:<app_id>`、`figma_token` | MCP 的 Lark / Figma |
| `vpn_password`、`vpn_totp_secret` | VPN 登录 |
`config.json` 的 `credentials` 只记元数据（kind/ref/source/state），不含密钥值。

## 怎么改
- 加配置项：在 `domain/settings.py`（或对应领域文件）的模型加带默认值的字段，改 schema 版本时在 `config_store.py` 的迁移表注册 `vN → vN+1` 纯函数，并补迁移测试。
- 加凭据：账号名约定加进 `CredentialMeta.kind` 与 `Config.credential_accounts` 校验，经 `SettingsService` 的 `_get/_set/_delete` 读写。

## 注意与坑
- **红线**：PAT/Bot Token 等只进 Keychain，不写进 `config.json`、日志或仓库；写入前和迁移时用 `contains_secret` 检查，含密钥则拒绝。
- 迁移只在启动时执行（`initialize`），逐版 v1→…→v8，先写备份到 `migrations/` 再替换；失败则 `store_unavailable`，原件保留，进入只读。普通 `read()` 不升级。
- 导入流程：`POST /api/settings/import/preview` → `execute`（带预览指纹，源文件变化则 `import_source_changed`）；旧 PAT 从旧 Keychain（`azuredevops_pat:<id>`）读出写入新账号；源文件含凭据值则拒绝导入。可 `decline` 跳过。
- 删除库时有引用保护；删除失败的凭据标记 `pending_delete`，孤立凭据在「凭据」页清理。
- **未迁移**：旧版 `app_ado/task_migrate.py` 的 flows→tasks 在运行时迁移；现由导入阶段的 `migrate_tasks` 一次性换算。旧 `docs/ADO_PAT_DISCOVERY_FLOW.md` 描述的是 Qt 时代的发现流程，新版由 `adapters/ado_http.py` 与发布配置发现接口实现。
