# next：新版代码工具箱

前后端分离重写：Vue 3 + Vite 界面、Tauri 2 薄壳、Python 3.14 + FastAPI 后端。尚未搭建骨架（S0）。

- 架构决策：[ARCHITECTURE.md](../docs/modernization/ARCHITECTURE.md)
- 前端选型：[FRONTEND_STACK.md](../docs/modernization/FRONTEND_STACK.md)
- 迁移计划与切片：[MIGRATION_PLAN.md](../docs/modernization/MIGRATION_PLAN.md)
- 协作规范与账本：[AGENT_WORKFLOW.md](../docs/modernization/AGENT_WORKFLOW.md)、[PROGRESS.md](../docs/modernization/PROGRESS.md)

```text
next/
  desktop/     Vue 前端 + src-tauri/
  backend/     Python 后端
  contracts/   生成的 OpenAPI / 事件 Schema
```

本目录之外的旧代码只作参考，不在本分支修改；旧应用的日常使用与热修在 `main` 分支的原文件夹。
