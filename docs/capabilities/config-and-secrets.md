# 配置与密钥存储

## 这个能力做什么
非密配置存 YAML（`~/.config/my-own-script/`），所有敏感凭据只进 macOS Keychain（`keyring`）。PAT 从 Keychain 读、驱动 ADO REST 发现项目/仓库/分支/构建/发布。

## 关键文件

| 做什么 | 文件 |
| --- | --- |
| 配置目录/读写（YAML，缺 PyYAML 时回退 JSON） | `app_ado/store.py` |
| 全部数据模型（pydantic） | `app_ado/models.py` |
| 密钥存取（keychain） | `app_ado/secrets.py` |
| 老格式迁移（flows→tasks、ACL task_ids） | `app_ado/task_migrate.py`、`store.migrate_acl_task_ids` |
| PAT 发现流程说明（认证/下拉填充/错误处理） | `docs/ADO_PAT_DISCOVERY_FLOW.md` |
| 安全说明（最小权限/泄露面） | `docs/SECURITY.md` |
| Library/Project/本地仓库配置 UI | `app_ado/ui/code_config_tab.py` |
| Figma PAT / Lark app_secret 的 keychain 存取 | `app_figma/secrets.py`、`app_lark/secrets.py` |

## 配置布局
- `~/.config/my-own-script/ui_settings.yaml` → `UiSettings`：libraries/projects/local_repos、active_*、Telegram（chat_id/whitelist/acl/notify）、work_items_*、ai（profiles/targets/policy/bots）。
- `~/.config/my-own-script/tasks.yaml` → `TaskSettings`：动态任务列表。
- `~/.config/my-own-script/services/`：服务面板状态 JSON。
- `~/.config/my-own-script/lark_login_state.json`：Lark OAuth 登录态。

## Keychain key 一览（service = `my-own-script`，`APP_ID`）
| key | 用途 |
| --- | --- |
| `azuredevops_pat:<library_id>` | ADO PAT（每 library 一个） |
| `telegram_bot_token` | 主机器人 |
| `ai_bot_token:<ai_id>` | 各 AI 专属机器人（claude_code/codex/gemini） |
| `vpn_*` / TOTP | Harmony SASE 凭据与种子 |
| Figma token / `lark app_secret:<app_id>` | 见各自 secrets 模块 |

## ADO PAT 发现流程要点（`docs/ADO_PAT_DISCOVERY_FLOW.md`）
- 认证：`Authorization: Basic base64(":PAT")`；`httpx.Client(follow_redirects=False)` 后台线程（QNetworkAccessManager/NTLM 不稳，httpx 稳）。
- 项目列表：`GET {base_url}/{collection}/_apis/projects?api-version=7.0`。
- 非 200 → 弹窗显示 library/PAT **长度**（绝不回显 PAT）/URL/status/headers/body 截断。

## 怎么改
- 加非密配置项：在 `app_ado/models.py` 对应 model 加字段（pydantic 自动带默认值），UI 走 `load_ui_settings`/`save_ui_settings`。
- 加新凭据：`app_ado/secrets.py` 加 `get_/set_` 一对，key 用 `service:key` 约定。

## 注意坑
- **红线：PAT/Bot Token 等密钥只进 Keychain，禁止写明文进 YAML 或提交仓库**（见 `AGENTS.md`）。
- 加载时自动跑迁移并落盘（`load_ui_settings`/`load_task_settings`），别在别处手改 YAML 结构。
- 日志/错误信息里绝不输出 Authorization/Token/PAT 原文，最多长度。
