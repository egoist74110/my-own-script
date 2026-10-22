# AGENTS.md — 先读我

本仓库 = **代码工具箱**（macOS PySide6 桌面应用，入口 `app_main.py`）+ **ok-script**（图像识别自动化框架，`ok/`）。
Python 3.14，`.venv` 隔离，敏感信息走 macOS Keychain（keyring），配置走 YAML。

## 现代化重构协作入口

参与本次重构前，必须阅读 [协作规范](docs/modernization/AGENT_WORKFLOW.md)、[工作包](docs/modernization/WORK_PACKAGES.md) 和 [进度账本](docs/modernization/PROGRESS.md)。
按工作包分工；施工模型可委派一层测试子 agent；Claude 全部 medium，GPT 6 Luna 固定 high，GPT 6.1 Sol 主控 high、施工 medium。实际型号/档位不可验证时记录 unknown，不得虚构署名或静默替换。
交叉审计异步开展、登记发现，不阻塞下一工作包，不强制审到零问题。具体职责、验收和升级条件以协作规范为准。
`config/model_collaboration_templates/` 是历史可复制模板，不得覆盖本仓库当前协作规范；不自动修改用户全局 agent 配置。

> 本文件只做导航，不堆细节。**任何 AI 接手任务前，先看能力索引：**

## 📇 能力索引（从这里开始）

**[docs/CAPABILITIES.md](docs/CAPABILITIES.md)** —— 本项目全部能力的索引。

使用方式：
1. 想做什么 → 打开 `docs/CAPABILITIES.md` 查「能力清单」表，定位对应能力行；
2. 点进该能力的详细文档（`docs/capabilities/*.md`），里面有关键文件、用法、坑；
3. 按文档里的文件路径直接动手。

## 30 秒常用操作

| 要做的事 | 怎么做 |
| --- | --- |
| 本地运行应用 | `bash dev_run.sh`（自动 pull + 建 venv + 装依赖 + 启动） |
| 打包 .app / .dmg | `bash pack_mac_app.sh` → `bash pack_mac_dmg.sh` |
| 发布到 GitHub Releases | `VERSION=x.y.z bash release_github.sh` |
| 改版本号 | 改 `app_version.py`（第 4 段由 pre-commit 自动递增） |
| 跑测试 | `pytest`（见 `tests/`，`pytest.ini` 配置） |

## 红线

- PAT / Bot Token 等密钥**只进 Keychain**（`app_ado/secrets.py`），禁止写明文进 YAML 或提交到仓库。
- 涉及 ADO/发布操作的改动，先读 `docs/SECURITY.md` 与 `docs/AI_CHANGE_POLICY.md`。
- 新增能力：代码落 `app_ado/`（或对应模块），并在 `docs/CAPABILITIES.md` 索引 + `docs/capabilities/` 补一行/一页，保持索引可用。
