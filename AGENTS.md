# AGENTS.md — 先读我

本仓库 = **代码工具箱**（macOS 桌面应用，v1.0.0）：Vue 3 + Vite 界面、Tauri 2 薄壳、Python 3.14 + FastAPI 后端。代码全部在 [`next/`](next/)：

```text
next/
  desktop/     Vue 前端 + src-tauri/（Rust 壳：窗口、托盘、更新器、拉起/回收后端）
  backend/     Python 后端（src/toolbox_backend：api/ services/ adapters/ domain/ mcp/ vpn/）
  contracts/   生成的 OpenAPI / 事件 Schema（前端 TS 类型由它生成，不手写）
  scripts/     构建、签名、打包、本机安装脚本
```

敏感信息（PAT / Bot Token / VPN / OTP）只进 macOS Keychain；非密配置走后端配置存储（数据目录 `~/Library/Application Support/toolbox-next`）。

> 本文件只做导航，不堆细节。**任何 AI 接手任务前，先看能力索引：**

## 📇 能力索引（从这里开始）

**[docs/CAPABILITIES.md](docs/CAPABILITIES.md)** —— 想做什么 → 查「能力清单」表 → 进 `docs/capabilities/*.md` 详情页 → 按里面的文件路径动手。

## 30 秒常用操作

| 要做的事 | 怎么做 |
| --- | --- |
| 本机构建并安装 | `bash next/scripts/install_local.sh --open`（ad-hoc 签名，仅本机） |
| 跑后端测试 | `cd next/backend && uv run pytest -q` |
| 跑前端检查 | `cd next/desktop && pnpm typecheck && pnpm lint && pnpm test`（以 package.json 为准） |
| 改后端接口后同步契约 | 见 [dev-and-tests](docs/capabilities/dev-and-tests.md) 的契约生成/检查命令 |
| 打包 DMG | `bash next/scripts/make_dmg.sh <.app> <outdir>` |
| 发布 | `gh release create vX.Y.Z <dmg> <zip> --latest`，流程见 [packaging-release](docs/capabilities/packaging-release.md) |
| 版本号 | 单一来源 `next/desktop/src-tauri/tauri.conf.json`，用 `next/scripts/sync_version.py` 同步 |

## 红线

- PAT / Bot Token 等密钥**只进 Keychain**，禁止写明文进配置或提交到仓库，日志与响应里也不得出现。
- 涉及 ADO/发布的改动，先读 [docs/SECURITY.md](docs/SECURITY.md) 与 [docs/AI_CHANGE_POLICY.md](docs/AI_CHANGE_POLICY.md)。
- 改后端 API 必须重新生成契约（OpenAPI + 桌面 `schema.d.ts`），不手改生成文件。
- 新增能力：代码落 `next/backend`（业务）与 `next/desktop`（界面），并在 `docs/CAPABILITIES.md` 索引 + `docs/capabilities/` 补一行/一页，保持索引可用。

## 历史

重写（原“现代化重构”）已完成并以 v1.0.0 取代旧 PySide6 应用。设计决策与过程记录仍在 [docs/modernization/](docs/modernization/README.md)：架构决策见 [ARCHITECTURE.md](docs/modernization/ARCHITECTURE.md)，逐切片历史在 `archive/`。旧应用源码可在 git 历史（提交 `885d186` 及之前）找回。
