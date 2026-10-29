# my-own-script

代码工具箱（TOOLBOX）：面向日常研发/运维的 macOS 桌面工具（Tauri + Vue 前端，Python 后端），覆盖 Azure DevOps 发布配置与一键执行、工单、Telegram 控制、MCP、AI 会话等。

代码位于 [`next/`](next/)：

- `next/backend`：Python 后端
- `next/desktop`：Tauri 桌面端
- `next/scripts`：构建、签名、打包脚本（本机一键安装：`bash next/scripts/install_local.sh --open`）

AI 协作入口见 [AGENTS.md](AGENTS.md)，能力索引见 [docs/CAPABILITIES.md](docs/CAPABILITIES.md)。

旧版 PySide6 应用（v0.1.x）已在 v1.0.0 移除，历史版本见 git 记录与 GitHub Releases。
