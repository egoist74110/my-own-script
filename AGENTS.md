# AGENTS.md — 先读我

本仓库 = **代码工具箱**（macOS PySide6 桌面应用，入口 `app_main.py`）+ **ok-script**（图像识别自动化框架，`ok/`）。
Python 3.14，`.venv` 隔离，敏感信息走 macOS Keychain（keyring），配置走 YAML。

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
