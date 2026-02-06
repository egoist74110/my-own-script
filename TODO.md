# TODO (代码工具箱)

> 这个文件用来记录“接下来要做什么”，避免遗忘。
> 建议每次完成一项就勾掉，并在必要时补充测试步骤。

## P0 / 核心功能完善

- [ ] **GitFlow 配置 UI 列表化**（支持多 update_branches / 多 merges / 多 push_branches）
  - 目标：不再局限于“是否合并”的单一规则。
  - UI：可增删行；每行用分支下拉；提供“预览将执行的步骤”。
  - 影响文件：`app_ado/ui/dynamic_task_dialog.py`（或拆分新文件）。
  - 测试：
    - 新建任务：update 2 个分支 + 2 条 merge + push 2 个分支，保存后 tasks.yaml 正确落盘
    - 运行任务：日志顺序与配置一致

- [x] 删除任务时同步清理 ACL 引用（ui_settings.telegram_acl_groups[*].task_ids）

- [x] TG 通知脱敏开关（是否包含 repo/path/url 等敏感信息）

## P1 / 稳定性与体验

- [x] Telegram 控制状态可视化：最近一次轮询时间/最后错误（配置页显示）
- [ ] 更新流程增强：失败提示更明确 + 重试 + 手动安装引导

## P2 / 体验优化

- [ ] 任务排序/搜索
- [ ] 任务运行历史（最近 N 次结果/耗时）
