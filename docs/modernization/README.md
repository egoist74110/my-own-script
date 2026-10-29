# 现代化重构

> **2026-10-29 完成**：重写已以 v1.0.0 发布并取代旧 PySide6 应用，旧应用代码、基线脚本与表征测试已移除（git 历史 `885d186` 及之前可找回）。本目录保留为历史记录；以下内容中提到的旧文件路径不再存在。

这是本次重构的项目内交接入口。先读 [协作规范](AGENT_WORKFLOW.md)，再从 [工作包](WORK_PACKAGES.md) 选择依赖已满足的工作；实际状态、署名与审计发现见 [进度账本](PROGRESS.md)。

> **2026-10-22 方向变更**：用户决定前后端分离重写——Vue 3 + Vite 界面、Tauri 2 薄壳、Python + FastAPI 后端，旧 UI 不保留；新代码在 `rewrite/next` 分支的 `next/` 目录，旧应用留在 `main` 日常使用。见 [架构决策](ARCHITECTURE.md)、[前端选型](FRONTEND_STACK.md)、[迁移计划](MIGRATION_PLAN.md)。下文“已接受的方向”中与此冲突的条目已标注作废；审计快照、证据与债务索引仍有效。

## 已接受的方向

- ~~本轮保留 Python 3.14 + PySide6，逐步分离业务与页面，不重做视觉设计，不启动 Tauri/Rust 重写。~~（2026-10-22 作废，见 ARCHITECTURE.md）
- 当前 Apple Silicon Mac 是正式验收目标；不宣称 Intel、Windows 或旧 macOS 已兼容。
- 所有现有业务能力先保留，按需加载；疑似废弃能力待确认，不删除用户配置和数据。
- 应用自身的目标是自包含；AI CLI、Harmony SASE、系统 Chrome 等保持外部工具边界。
- 关闭窗口后继续后台运行；明确退出时清理应用所属资源；独立常驻和外部复用进程明确区分。
- 不新建通用插件框架。~~不建长期 UI HTTP 服务~~（2026-10-22 改为仅本机、随机端口、每次启动 token 的后端接口，见 ARCHITECTURE.md §3）。核心接口不依赖 Qt / Tauri。
- 先执行阶段 0 基线和阶段 1 风险修复，再逐步抽离任务、统一生命周期、收敛 AI/TG 和打包。
- 交叉审计异步、不阻塞施工；发现问题先登记，必要时修复后定点复核。

## 审计快照与证据等级

初始代码基线：`c349243286d27ae82943a4381951f9f3b041b7d1`。审计时已存在 `app_ado/ui/deploy_target_dialog.py` 和 `config/ai_change_policy.yaml` 的用户修改；不覆盖它们。

| 事实 | 证据等级 |
| --- | --- |
| Telegram 发布入口调用 TasksTab，执行要求 TaskCard 已加载 | 静态调用：`app_main.py:174`、`app_ado/ui/tasks_tab.py:321` |
| 工单分析直接调用 AiDevTab | 静态调用：`app_ado/ui/work_items_tab.py:812` |
| .app 为指向仓库/.venv 的包装，设置页实际使用 Git 更新 | 静态：`pack_mac_app.sh`、`app_ado/ui/ado_tab.py:26` |
| 外部内联图片可收到 ADO 认证头 | 离线 MockTransport 复现；`work_item_view.py:65`、`ado_work_item_http.py:108`；未断言发生过真实泄露 |
| Telegram 401 异常含 Bot Token 并写入日志/状态 | 假 Token 离线复现；`tg_control.py:1538`；未读取真实日志或 Keychain |
| 旧 flows 保留时清空 tasks 会重新迁移并生成任务 | 纯数据复现；`task_migrate.py:63`；用户配置本身没有修改 |
| Pipeline 分支无法确认时仍可被接管 | 模拟详情请求失败复现；`ado_build_http.py:258` |
| MCP 握手等待持有状态锁 | 假进程/阻塞管道复现；`mcp_server_manager.py:29` |

初轮现有测试为 **36 passed、2 skipped**；270 个 tracked Python 文件在 3.14.7 下 AST 可解析。旧 ok-script 两个测试因符号不可用跳过。最新执行结果以账本和报告文件为准，不能把历史结果当新版本的验证。

本轮新增基线工具 25 个测试、离线表征 5 个测试，集成结果为 **66 passed、2 skipped**；见 [采集报告](baseline-2026-10-21.json) 与 [验证记录](verification-2026-10-21.json)。表征通过意味着五个缺陷仍可复现，生产逻辑尚未修改。

新的受限 import probe 明确返回 `error / ProcessExit / blocked_events=[os.putenv]`、清理成功。这是保护拦截，不是新发现的应用启动失败，也没有新的成功导入耗时/RSS。实际 GUI、空闲和工作状态仍为未测。

初轮本机文件体积约为：开发 `.venv` 1.423 GB、已安装 PySide6 Essentials 325.9 MB / Addons 864.5 MB、Playwright 140.9 MB、单个既有 DMG 3.41 MB。这些是不同口径，不能相互替代为发布包基线。

单次仅 `import app_main` 约 0.923 秒，进程最高 RSS 约 122.9 MB；未创建 QApplication/页面。这不是应用启动时间或空闲内存，更不能作为已优化结果。完整 GUI、长时间运行与真实业务进程树尚需阶段 0 测量。

## 技术债务索引

| 编号 | 问题 | 处理顺序 |
| --- | --- | --- |
| D01 | 工单图片的认证来源边界不一致 | 阶段 1 |
| D02 | Telegram 异常日志/状态未脱敏 | 阶段 1 |
| D03 | dsh/隧道凭据进入 argv；Lark Bearer 写 CLI 配置及备份 | 阶段 1，先确定各工具安全传递接口 |
| D04 | 空任务列表被旧 flows 重新迁移 | 阶段 1 |
| D05 | 配置非原子写、读取会写迁移、并发快照覆盖 | 阶段 1 |
| D06 | 构建接管未确认分支/提交身份 | 阶段 1 |
| D07 | 执行状态由页面持有、日志引用共享、仓库修改缺少互斥 | 阶段 2 任务核心 |
| D08 | MCP 握手无截止、管道未持续消费、停止失败丢句柄 | 阶段 1 止损，阶段 3 所有权统一 |
| D09 | 退出协调、AI 后代进程回收、GUI 多线程 fork 风险 | 阶段 3 |
| D10 | 隐藏页面探测与 UI 线程子进程开销 | 阶段 3/4 |
| D11 | AI 事件读取同步发送 TG，桥层重复 | 阶段 4 |
| D12 | 远端运行检查点与 Telegram 请求去重不足 | 阶段 1 定义，阶段 2 集成 |
| D13 | Lark 内部补丁/依赖漂移影响刷新与撤销语义 | 阶段 1 契约验证；不盲删补丁 |
| D14 | 包装交付、版本处理、发布失败与临时资源清理 | 阶段 5 |
| D15 | 关键执行、授权、取消、恢复测试不足 | 阶段 0 起逐包补齐 |
| D16 | 旧更新器/编辑器/空占位与文档漂移 | 已确认无行为项在批准后清理；业务入口待确认 |

## 后续阶段的模块方向

UI/TG/MCP 输入适配器 → 无 Qt 的应用接口 → 任务/工单/AI 业务流程 → ADO/Git/CLI/VPN/进程适配器。配置、Keychain、脱敏日志与运行记录是明确依赖，不经页面访问。

接口提供 start/cancel/get/list/subscribe；区分取消、远端仍在运行和结果未知。UI 不负责消费完成事件后才清理业务状态。保留 PTY 与 headless、不同 AI 协议、stdio 与共享 HTTP 的实际差异。

后续执行包在阶段 0/1 的结果上细化；本轮没有把未知凭据传递接口、未测包体或运行内存伪装成已经确定的实施事实。
