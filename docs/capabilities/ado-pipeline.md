# ADO 流水线：任务（同步 / 构建 / 发布 / 回滚 / 停止）

## 这个能力做什么
把「本地 Git 同步 → ADO 构建 → ADO Release 发布」做成一键执行。后端 `next/backend` 提供任务 CRUD、预检（preflight）、启动、取消、核实（reconcile）和事件回放；桌面「任务」页和 Telegram 都走同一套接口。三种操作：`sync_build_release`（同步+构建+发布）、`deploy_only`（取最新成功构建只发布）、`rollback`（回滚 1..5 个历史 Release）。多目标串行，失败即停。

任务定义以「发布配置 + 运行命令」为准（v8，见 [发布配置](release-configs-next.md)），执行时展开成 `DynamicTask`；运行用的 task_id 即命令 id。

## 关键文件（均在 `next/`）

| 做什么 | 文件 |
| --- | --- |
| 任务/运行 HTTP 路由（`/api/tasks*`、`/api/runs*`） | `backend/src/toolbox_backend/api/task_routes.py`、`api/task_schemas.py` |
| 任务 CRUD、排序、引用保护（被 ACL 引用等） | `backend/src/toolbox_backend/services/tasks.py` |
| 运行服务：预检计划、启动、取消、核实、恢复循环、最多 4 并发 | `backend/src/toolbox_backend/services/runs.py` |
| 执行器协议与日志/检查点/副作用意图模型 | `backend/src/toolbox_backend/domain/task_execution.py` |
| 真实 ADO 执行器（预检、构建、Release、部署、回滚、只读核实） | `backend/src/toolbox_backend/adapters/ado_tasks.py` |
| 本地 Git 同步与推送 | `backend/src/toolbox_backend/adapters/task_git.py`、`adapters/git_process.py` |
| 运行记录（`<data-dir>/runs.sqlite3`，WAL）、事件流 | `backend/src/toolbox_backend/adapters/run_store.py`、`adapters/run_log.py` |
| 运行事件 WebSocket 订阅（按 run_seq 回放） | `backend/src/toolbox_backend/api/ws.py` |
| 测试用假 ADO / 开发用临时 Git 夹具 | `adapters/fake_task_ado.py`、`adapters/dev_tasks.py` |
| 桌面任务页（列表、运行卡、日志、历史、回滚、发布向导） | `desktop/src/features/tasks/TasksPage.vue`、`RunCard.vue`、`LogPanel.vue`、`RunHistory.vue`、`TaskRollbackSheet.vue`、`ReleaseWizardSheet.vue` |
| 契约 | `next/contracts/openapi.json`、`events.schema.json` |

## 执行流程
1. **预检** `POST /api/tasks/{id}/preflight`（带配置 `revision`、`operation`、回滚的 `rollback_offset`）：校验凭据来源、仓库/构建定义/Release 定义绑定，冻结目标、commit、阶段，返回 `plan_id`。
2. **启动** `POST /api/tasks/{id}/runs`（`plan_id`、`request_id` 幂等、`ack_old_app_idle` 必须为 true）→ 202。同一任务同时只能有一个活动 run。
3. **Git 步骤**（仅 `sync_build_release` 且配了本地仓库）：fetch → `update_branches` 逐个 `--ff-only` → `merges` 逐条 `git merge`（失败 `merge --abort`）→ `push_branches` 非强制推送；结束后切回原分支。
4. **每个目标串行**：创建/接管构建并等待 → 创建 Release、部署所选环境（回滚则对历史 Release 重新部署）→ 监控结果。远端写操作先落「副作用意图」再记回执。
5. **停止** `POST /api/runs/{id}/cancel`；结果不确定时状态为 `unknown`，由 `reconcile`（只读）或每 30 秒的恢复循环核实，15 分钟未核实转人工。
状态：`queued/running/cancelling/cancelled/succeeded/failed/unknown`。

## 怎么改
- 加任务字段：`domain/settings.py` + `api/task_schemas.py`，改完重新生成 `contracts` 与 `desktop/src/api/schema.d.ts`。
- 加远端能力：放 `adapters/ado_tasks.py`，经 `adapters/ado_http.py` 出站，PAT 由 credentials 提供，不进日志。

## 注意与坑
- Git 失败不做硬重置，已发生的推送保留；仓库处于 merge/rebase 中、origin 的 fetch/push URL 不一致、或指向本工具自身仓库路径时，预检/执行会拒绝。
- **未迁移**：旧版「无本地仓库时用 ADO PR 远程合并」。新版无本地路径但配了 update/merge/push 规则时预检直接报不支持；无本地路径只能取远端分支头构建。
- **未迁移**：旧 `~/.config/my-own-script/tasks.yaml`、`flows→tasks` 迁移不在运行时使用，旧配置经 [配置与密钥](config-and-secrets.md) 的导入进入。
- 日志与错误文本经脱敏（PAT、Authorization、URL 凭据）。
- 纯本地异常分类及收尾失败后的同进程恢复仍有审计待办，见 `docs/modernization/WORK_PACKAGES.md`、`PROGRESS.md`。
- Telegram 触发的发布菜单见 [Telegram 分层菜单](telegram-menu-next.md)。
