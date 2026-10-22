# 新版架构决策（ADR-001）

状态：用户已接受方向（2026-10-22）。本文件取代 README 中“保留 PySide6、逐步分离页面”的旧方向；阶段 0 的基线、表征与债务索引继续有效。

## 1. 决策

| 层 | 选择 | 职责 | 不做什么 |
| --- | --- | --- | --- |
| 界面 | Vue 3 + TypeScript + Vite（选型见 [FRONTEND_STACK.md](FRONTEND_STACK.md)） | 展示、交互、订阅事件 | 不持有业务状态、不直接读凭据、不直连 ADO/TG 等外部服务 |
| 桌面壳 | Tauri 2，Rust 薄壳 | 窗口、菜单栏托盘、关窗后台常驻、单实例、拉起/监督/回收后端、把连接信息交给页面 | 不写业务逻辑 |
| 后端 | Python 3.14 + FastAPI + uvicorn（asyncio） | 全部业务：任务、工单、AI 会话、TG、MCP、VPN、服务管理、配置与 Keychain | 不依赖 Qt / Tauri |
| 契约 | OpenAPI + JSON Schema 自动生成 | 前端 TS 类型与客户端由后端模型生成 | 不手写两份类型 |

理由：现有业务、脚本与外部工具集成（ADO、Lark/Figma MCP、TG、Codex/Claude/agy、Playwright、Keychain）都在 Python 生态，且已沉淀大量坑位经验；工作负载以 IO/子进程为主，asyncio 足够。Rust 只承担 Tauri 必需的系统集成。Nuxt 的 SSR/约定路由在本地 SPA 中没有收益，不采用。

被否决的替代：TypeScript 全栈（需重写全部业务）、Go（重写且缺生态）、Rust 业务层（开发效率低）、继续 PySide6（用户明确要求前端重写）。

## 2. 进程模型

```text
Tauri 应用（Rust）
 ├─ WebView：Vue SPA ──HTTP/WS(127.0.0.1:随机端口, Bearer token)──┐
 └─ 监督 → Python 后端进程（uvicorn）◄──────────────────────────────┘
              ├─ 应用服务：tasks / work_items / ai_sessions / mcp / vpn / services / settings
              ├─ 输入适配器：HTTP API、WebSocket 事件、Telegram 轮询、（MCP 见下）
              └─ 外部适配器：ADO REST、git、AI CLI(PTY/headless)、Keychain、进程监督
MCP stdio 进程（由 AI 客户端拉起）── 直接复用后端核心库，经统一 store 读写配置
```

- 后端是独立进程：页面崩溃或刷新不影响运行中的任务、TG 与 AI 会话。
- 关窗 = 隐藏到菜单栏，后端继续；明确“退出” = 协调停止（取消/等待任务 → 停止应用所属子进程组 TERM→有界等待→KILL→wait）。外部复用的进程（如已在跑的 dsh）只断开，不杀。
- 后端异常退出：壳按退避策略重启，页面显示“后端重连中”，不吞掉运行中任务的未知状态（见 §4）。
- 后续可选：后端以 launchd 无界面常驻（TG 在不开界面时也工作）。首版不做，接口不阻断。

## 3. 本地通信与安全

旧方向“不建长期 UI HTTP 服务”在前后端分离后不再适用，改为以下约束：

- 只绑定 `127.0.0.1`，端口由后端启动时随机选择，经 stdout 握手行告知壳；壳通过 Tauri command 交给页面，**不放进 URL**。
- 每次启动生成随机 token；HTTP 用 `Authorization: Bearer`，WebSocket 首帧认证，失败即关闭。
- 校验 `Host` 为 127.0.0.1:port（防 DNS rebinding）；CORS 只允许 Tauri 页面 origin；无 token 的请求一律 401。
- 后端对页面的响应永不包含 PAT、Bot Token、OAuth token、TOTP 种子；凭据只能写入（设置）与测试连通，不能读回明文。
- 外部内容由后端代取：工单内联图片/附件走后端代理，按本次 library 的可信 origin 逐跳校验（即 D01/WP-11 的规则），页面只拿到代理 URL；ADO HTML 在后端白名单清洗、前端再经 DOMPurify。
- 日志、错误、事件统一经脱敏器（D02/WP-12 的规则：bot URL token、认证头、已知当前密钥）。
- TG 的 ACL 与命令授权在后端应用服务内判定，与 UI 调用同一权限检查，不靠前端隐藏按钮。

## 4. 长操作的统一模型

所有执行类操作（同步/构建/发布/回滚、AI 会话、MCP 启停、VPN 恢复、服务启停）实现同一接口：

`start → run_id`；`cancel(run_id)`；`get(run_id)`；`list(filter)`；`subscribe(topic)`（WebSocket）。

状态：`queued / running / cancelling / cancelled / succeeded / failed / unknown`。`unknown` 专指“远端可能仍在运行、结果无法确认”（例如构建已触发但后端重启），不得显示为失败或已停止。

- 运行记录与检查点存 SQLite（WAL），重启后可恢复为 `unknown` 并重新查询远端（D12）。
- 构建复用只接受分支 + commit + definition 全匹配（D06）；只取消本任务创建的构建。
- 仓库写操作按仓库路径加互斥锁（D07）。
- 日志按 run 追加存储，事件流只推增量；页面断线重连后按序号补齐。

## 5. 数据、配置与凭据（与旧应用共存）

新旧应用会同时存在数月，必须避免互相覆盖：

| 资源 | 规则 |
| --- | --- |
| 配置 | 新应用使用独立数据目录（`~/Library/Application Support/<新应用 ID>/`），首次运行从旧 `~/.config/my-own-script/` **只读导入**，永不回写旧配置。schema 带版本号；写入原子替换 + 跨进程锁（D04/D05 规则在新 store 内实现）。 |
| 静态密钥（PAT、Bot Token、VPN 账号） | 可读取旧 Keychain 条目作为导入来源；新应用写入自己的服务名，不修改旧条目。 |
| 会轮换的凭据（Lark OAuth refresh_token） | 同一时间只能一个应用持有刷新权（否则重现 20038）。迁移该能力时显式“切换所有权”，并在旧应用停用。 |
| 单例资源（同一 Bot Token 的 TG 轮询、ADO/Lark MCP 单例、dsh 网关端口、code-server/cloudflared） | 同上：按能力切换所有权。两个应用同时用同一 Bot Token 轮询会互相 409，不能并行开启。 |

## 6. 目录与工具链

```text
next/
  desktop/            Vue 前端 + src-tauri/（Rust 壳）
  backend/            Python 包（pyproject + uv.lock），src/ 下按 api / services / domain / adapters 分层
  contracts/          生成的 openapi.json 与事件 JSON Schema（提交入库，CI 比对漂移）
```

- 前端包管理 pnpm；后端依赖 uv 锁定（本机已装 pnpm 11、uv 0.13、Rust 1.95、Node 24、Python 3.14.7）。
- 旧代码（`app_main.py`、`app_ado/` 等）在本分支保持只读参考；新代码可以**拷贝改写**旧模块，不 import 旧包，避免把 Qt 依赖带进后端。
- ok-script（`ok/`）是 Windows 图像自动化框架，不在新产品范围。

## 7. 打包与更新（D14）

目标是真正自包含的 `.app`：Tauri 打包 + 内置独立 Python 运行时（python-build-standalone 或 PyInstaller，S0 做对比 spike 后定）。签名/公证、更新机制（Tauri updater 或继续 GitHub Releases）在 S9 决定；在此之前新应用只以开发模式运行，不替换旧 `.app`。

## 8. 未决事项（不阻塞骨架）

- 内置 Python 方案与包体积（S0 spike 实测，不预估）。
- 是否需要 launchd 无界面常驻。
- 新应用名称与 bundle id。
- 视觉方向（见 FRONTEND_STACK §5，需用户在方向稿中选择）。
