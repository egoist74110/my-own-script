# 重构历史与架构决策

重写（旧 PySide6 应用 → Vue 3 + Tauri 2 + Python/FastAPI）已完成，v1.0.0 取代旧应用。本页只做历史文档的导航；业务功能见各能力页。

| 文档 | 用途 |
| --- | --- |
| [重构入口](../modernization/README.md) | 方向变更记录、审计快照（历史） |
| [架构决策](../modernization/ARCHITECTURE.md) | 分层、进程模型、本地通信安全 —— 仍是当前架构依据 |
| [前端选型](../modernization/FRONTEND_STACK.md) | 组件底座、样式、状态、终端、测试 |
| [迁移计划](../modernization/MIGRATION_PLAN.md) | 切片 S0..S9 与搬完标准（历史） |
| [进度账本](../modernization/PROGRESS.md) | 切片状态、验收记录、开放项（发布、签名、公证等待办在此） |
| [协作规范](../modernization/AGENT_WORKFLOW.md)、[工作包](../modernization/WORK_PACKAGES.md) | 重构期间的协作规则与合同（历史） |
| [archive/](../modernization/archive/README.md) | 已完成切片的逐轮记录 |
| [design/](../modernization/design/) | 界面方向探索稿（HTML 原型） |

旧应用源码在 git 历史中（提交 `885d186` 及之前，分支标签见 GitHub Releases v0.1.x）。重构用的旧应用基线脚本与表征测试已随旧代码移除，`baseline-2026-10-21.json` / `verification-2026-10-21.json` 仅作当时的证据留存。
