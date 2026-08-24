# 应用核心（入口 / 选项卡 / 启动流程）

## 这个能力做什么
「代码工具箱」是一个 macOS PySide6 + Fluent 风格桌面应用，入口 `app_main.py`。
单窗口（`MSFluentWindow`）挂 9 个选项卡，启动时拉起 4 条 Telegram 轮询线程和 1 条 git 更新检查线程。

## 选项卡一览（app_main.py 第 237-245 行注册）

| 选项卡 | 类 | 文件 |
| --- | --- | --- |
| 任务 | `TasksTab` | `app_ado/ui/tasks_tab.py` |
| 工单 | `WorkItemsTab` | `app_ado/ui/work_items_tab.py` |
| 服务 | `ServicesTab` | `app_ado/ui/services_tab.py` |
| 通讯配置 | `CommunicationConfigTab` | `app_ado/ui/communication_config_tab.py` |
| 代码配置 | `CodeConfigTab` | `app_ado/ui/code_config_tab.py` |
| 设置（含检查更新） | `AdoReleaseTab` | `app_ado/ui/ado_tab.py` |
| AI配置 | `AiConfigTab` | `app_ado/ui/ai_config_tab.py` |
| MCP配置 | `McpConfigTab` | `app_ado/ui/mcp_config_tab.py` |
| AI开发 | `AiDevTab` | `app_ado/ui/ai_dev_tab.py` |

Tab 基类复用 ok-script 的 `ok/gui/widget/Tab.py`。

## 启动时做了什么（main() 顺序）
1. 建 `QApplication`，图标取 `TOOLBOX_APP_ICON` 或仓库 `logo.png`。
2. 建 9 个 Tab 实例；`WorkItemsTab` 持有 `ai_dev_tab` 引用以便「MCP 分析」跳转。
3. 建 3 套 headless 会话管理器 + TG 桥（Claude / Codex / Antigravity），`bridge.start()` 启动监听线程。
4. 起 4 条 `TelegramController` 轮询线程：主机器人（任务/工单/服务/MCP）+ 3 个专属 AI 机器人（`mode="ai"`）。
5. 显示窗口；起后台线程做 git 更新检查：`origin/main` 领先且工作区干净 → 弹窗询问 → `pull_ff_only` + `pip_sync` + `restart_self`（`app_ado/updater.py`）。
6. `aboutToQuit` 时清理所有 AI 会话与桥（第 248 行）。

## 怎么用 / 怎么改
- 新增选项卡：在 `app_main.py` 里 `import` + 实例化 + `w.addSubInterface(...)`，类继承 `ok/gui/widget/Tab.py` 的 `Tab` 或 `QtWidgets.QWidget`。
- 改启动行为（新增后台线程/会话）：照 headless bridge 的写法，在 `main()` 里 start、在 `aboutToQuit` 里 shutdown。
- 配置读取统一走 `app_ado/store.py`（`load_ui_settings` / `load_task_settings`），不要在 Tab 里直接读 YAML。

## 注意坑
- 多线程环境必须用 `shiboken6.isValid()` 校验 Qt 对象有效性后再访问，否则 C++ 对象误访问会段错误（`tasks_tab.py` 已有此防护模式）。
- TG 轮询线程只在应用运行期间存活；应用关了 Telegram 就不再响应。
- 本地有未提交改动时 git 更新检查静默跳过，不弹窗打扰。
- 运行环境：Python 3.14 + `.venv`（见 `RUN_MAC.md`）；`.app` 是轻量 wrapper，依赖仓库 venv（见 `BUILD_MAC_APP.md`）。
