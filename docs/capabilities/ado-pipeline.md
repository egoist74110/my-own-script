# ADO 流水线：任务（同步 / 构建 / 发布 / 回滚 / 停止）

## 这个能力做什么
「任务」Tab 里 CRUD 动态任务（GitFlow 同步 → 构建 → 发布 的一键执行器）。每个任务 = 本地 git 仓库 + 可配置分支流 + 多个「构建+发布」目标，多目标串行、失败即停。

## 关键文件

| 做什么 | 文件 |
| --- | --- |
| 任务 Tab（卡片 CRUD、执行、日志、停止、回滚、历史） | `app_ado/ui/tasks_tab.py` |
| 任务卡片组件 | `app_ado/ui/task_card.py` |
| 任务定义模型（`DynamicTaskConfig`/`GitFlow`/`DeployTarget`） | `app_ado/models.py` |
| 本地 git 操作（fetch/checkout/merge/push，subprocess） | `app_ado/ui/tasks_tab.py` `_run` 内 + `app_ado/ado_git_ops.py` |
| 无本地仓库时的远程 PR 合并 | `app_ado/ado_git_ops.py`（`create_pull_request`/`complete_pull_request`/`merge_via_pr`） |
| 构建：Pipelines 与 Build Definitions 触发/查询/等待/取消、智能匹配运行中实例 | `app_ado/ado_build_http.py` |
| 发布：建 Release、取 envs、启动 notStarted 环境、列最近 Release | `app_ado/ado_release_http.py` |
| 构建列表/查询辅助 | `app_ado/ado_build_query.py` |
| 执行历史记录 | `app_ado/task_history.py` |
| 任务编辑/排序/目标/回滚等对话框 | `app_ado/ui/dynamic_task_dialog.py`、`task_sort_dialog.py`、`deploy_target_dialog.py`、`rollback_dialog.py` |

## 执行流程（`TasksTab._run`，`run_task` 入口）
1. **git 流**：`git_flow.update_branches` 逐个拉取更新 → `merges` 逐个合并（本地 `git merge`；失败自动 `merge --abort + reset --hard`；无本地仓库则走 ADO PR 远程合并）→ `push_branches` 逐个推送。
2. **每个 target 串行**：触发构建（有 `agent_queue_id` 覆盖时走 Build API）→ `find_matching_run` 智能接管已在运行的实例（防重复触发死循环）→ 等待完成 → `create_release_from_build` → 自动启动 `notStarted` 环境 → 监控选定 stages。
3. 全程 emit 日志到任务卡片，响应式停止（每步查 `should_stop`，非阻塞）。

对外回调（供 TG 调用）：`run_task` / `deploy_only_task`（只发不构建）/ `rollback_task`（回滚 N 个版本）/ `stop_one_task` / `list_stoppable_tasks` / `status_text`。

## 怎么改
- 加任务：UI「新增任务」或直接编辑 `~/.config/my-own-script/tasks.yaml`（模型见 `app_ado/models.py`）。
- 加构建/发布 API 能力：放 `app_ado/ado_*_http.py`，PAT 从 `app_ado/secrets.py` 的 `get_pat(library_id)` 取。

## 注意坑
- 任务运行中编辑被锁定（置灰防误触发）；`isValid` 保护 Qt 对象。
- 认证用 `Basic base64(":PAT")`，PAT 只存 Keychain，绝不进日志。
- PAT 最小权限建议见 `docs/SECURITY.md`（Build 读+执行、Release 读+写+执行、Code 只读）。
- 老格式 `flows` 会自动迁移成 `tasks`（`app_ado/task_migrate.py`，加载时落盘）。
