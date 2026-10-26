# 现代化重构与 Agent 工作包

本能力管理本仓库重构的协作规则、分阶段合同、验证证据和异步审计。业务功能仍由各原能力页面导航。

| 文档/工具 | 用途 |
| --- | --- |
| [重构入口](../modernization/README.md) | 已接受方向、审计快照、债务索引 |
| [架构决策](../modernization/ARCHITECTURE.md) | 新版 Vue + Tauri + Python/FastAPI 分层、进程模型、本地通信安全、新旧共存规则 |
| [前端选型](../modernization/FRONTEND_STACK.md) | 组件底座、样式、状态、终端、测试与视觉方向流程 |
| [迁移计划](../modernization/MIGRATION_PLAN.md) | 两个文件夹、切片 S0..S9、搬完标准、旧阶段 1 风险处置 |
| `next/` | 新产品代码根目录（`rewrite/next` 分支） |
| [协作规范](../modernization/AGENT_WORKFLOW.md) | 模型/档位、权限、署名、委派、非阻塞交叉审计 |
| [工作包](../modernization/WORK_PACKAGES.md) | 当前切片合同；已完成切片与阶段 0/1 在 [archive](../modernization/archive/README.md) |
| [进度账本](../modernization/PROGRESS.md) | 切片状态总表、跨切片待办、当前切片记录；逐轮历史在 archive |
| `scripts/modernization_baseline.py` | 标准库只读采集；默认 JSON 到 stdout，可选受限 import probe |
| `tests/test_modernization_characterization.py` | 五个已知缺陷的离线 current_behavior 证据；不表示安全通过 |

从仓库根执行：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/modernization_baseline.py --help
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/modernization_baseline.py
```

显式 `--output <不存在的报告文件>` 才写文件，父目录需存在，不覆盖旧报告；`--import-probe` 可选、有超时和副作用保护（不是 OS 沙箱）。当前应用的受限导入会因 `os.putenv` 被保护拦截，结果为 error，不产生有效导入性能指标。不能把错误、导入峰值、venv 字节数或包装 DMG 当完整应用性能。

用户约定：Claude 全 medium；GPT 6 Luna high；GPT 6.1 Sol 主控 high/施工 medium。施工可开一层测试子 agent；交叉审计异步登记，不阻塞施工，不强制清零。

历史协作模板不覆盖本项目当前规则；不得自动修改用户全局 agent 配置。基线不得通过 `dev_run.sh` 采集（该脚本会 pull/install/start），不得读取真实凭据或触发真实远端写入。
