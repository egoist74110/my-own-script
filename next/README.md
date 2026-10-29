# next：新版代码工具箱

代码工具箱 v1.0.0：Vue 3 + Vite 界面、Tauri 2 薄壳、Python 3.14 + FastAPI 后端。各子目录 README 说明运行与测试；打包 spike 见 `spikes/packaging/`。

- 架构决策：[ARCHITECTURE.md](../docs/modernization/ARCHITECTURE.md)
- 前端选型：[FRONTEND_STACK.md](../docs/modernization/FRONTEND_STACK.md)
- 迁移计划与切片：[MIGRATION_PLAN.md](../docs/modernization/MIGRATION_PLAN.md)
- 协作规范与账本：[AGENT_WORKFLOW.md](../docs/modernization/AGENT_WORKFLOW.md)、[PROGRESS.md](../docs/modernization/PROGRESS.md)

```text
next/
  desktop/     Vue 前端 + src-tauri/
  backend/     Python 后端
  contracts/   生成的 OpenAPI / 事件 Schema
  scripts/     构建、签名、打包、本机安装脚本
```

能力索引见 [docs/CAPABILITIES.md](../docs/CAPABILITIES.md)。旧 PySide6 应用已移除，源码在 git 历史（`885d186` 及之前）。
