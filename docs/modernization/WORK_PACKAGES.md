# 工作包（阶段 0/1 与新产品切片）

- plan_id: modernization-20261021
- revision: 5（2026-10-22 追加 S0；同日追加 S0.5 方向 E 前端改造；同日追加 S1 合同草案；同日追加 S2 合同草案）
- base: c349243286d27ae82943a4381951f9f3b041b7d1 + 账本所列用户修改
- executor_autonomy: standard
- max_same_failure_attempts: 2
- delivery: 阶段 0/1 为本地文件与验证报告；S0 起用户授权在 `rewrite/next` 本地提交，不 push/merge/publish/deploy
- workflow: [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md)
- 状态、真实署名和检查结果只写 [PROGRESS.md](PROGRESS.md)，不能在本文件预填通过。
- 2026-10-22：方向改为前后端分离重写。WP-03、WP-11..16 的处置建议见 [MIGRATION_PLAN.md §4](MIGRATION_PLAN.md)，待用户确认；确认前不对旧应用施工。新产品切片 S0..S9 的合同派工前追加到本文件。

本轮授权落实协作规范、施工包及安全基线。后续业务修复按以下包推进；主控在派工前复核事实、范围及触发的后端/安全技能。策略文件是业务内工单准入机制，不通过修改用户的 `config/ai_change_policy.yaml` 给本次重构放行。

## 通用施工合同

每个包派工时必须完整携带本包目标、上下文、文件范围、禁止行为和验收条件，不依赖子 agent 继承聊天。角色/档位按协作规范显式设置；施工者委派一层便宜测试者。包完成表示自动验收满足，不表示交叉审计已通过。

- 用户现有修改与数据不覆盖；测试和测量禁止读取/写入真实 Keychain、用户配置，禁止真实 Telegram/VPN/ADO 副作用。配置路径指向临时目录；HOME/XDG 对专用子进程隔离，凭据接口使用 fake 并在意外真实访问时失败（仅改 HOME 不足以隔离 macOS Keychain）。网络/进程入口显式拦截；记录即使被业务捕获的违规尝试。
- 不安装未授权工具，不扩大权限，不改真实外部 CLI 配置，不启动 `dev_run.sh`（会 pull/install/start）。
- 下列命令从仓库根执行，`PYTHONDONTWRITEBYTECODE=1` 避免生成模块字节码；pytest 禁用持久缓存。
- Git diff 范围含 untracked 文件；验收针对集成版本。所有退出、失败、异常路径清理任务产生的临时资源。
- 审计异步，发现登记到稳定编号；不因审计未返回或旧问题未清零阻塞无关包。
- 所有 ADO/发布/凭据相关包先读 `docs/SECURITY.md` 和 `docs/AI_CHANGE_POLICY.md`。各包依赖的专项技能只在触发时加载，不通过降低策略或权限完成测试。
- 集成写范围：`tests/test_modernization_characterization.py` 由主控独占。WP-11..15 施工者只提交本包新回归测试，不直接改共享表征文件；主控按顺序把对应 current_behavior 场景替换/迁入正确契约回归，并与生产改动一起验收。尚未转正的旧缺陷断言不得作为“修复完成”的证据。

## WP-00：协作规范和交接入口

- 目标：新 agent 能找到唯一当前规则，确认模型档位、工作边界、测试职责、署名和非阻塞交叉审计。
- 依赖：无。
- write_scope：`AGENTS.md`、`.gitignore`（忽略本地审计缓存）、`docs/modernization/*.md`、`docs/CAPABILITIES.md`、`docs/capabilities/modernization.md`、`docs/capabilities/ai-collab-rules.md`；历史模板入口仅添加当前规则提示，不重写跨项目模板。
- 验收：所有相对文档链接存在；Claude 全 medium、Luna high、Sol 主控 high/施工 medium 一致；无“审到零才施工”的条款；目标型号与真实调用值分别记录；用户修改不变。
- 回退：只撤销本包文档增量，不触碰既有用户修改。

## WP-01：安全、可重复的基线采集工具

- 目标：以同一可执行命令得到可比较的环境/磁盘/导入数据，明确未测项目，不在基线中启动真实业务。
- 依赖：WP-00 的工作边界。
- write_scope：`scripts/modernization_baseline.py`、`tests/test_modernization_baseline.py`；采集报告保存在 `docs/modernization/baseline-*.json`。
- 实现：标准库 CLI；默认只读仓库/依赖元信息，stdout JSON；只有显式 output 才写报告。可选 import probe 在有超时的独立进程中仅导入 app_main，标为 import_only。禁止跟随目录 symlink 扫出范围、读取 Keychain/用户配置、联网或安装。
- 验收：帮助可用；缺目录/依赖如实记录；目录与 distribution 体积不混成安装包；失败/超时不报告通过；默认不写文件；报告无环境变量、凭据或用户 home 路径。
- run：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_modernization_baseline.py`，预期 exit 0。
- run：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/modernization_baseline.py --help`，预期 exit 0。
- 回退：移除本包工具/测试/报告，不改生产入口。

## WP-02：关键风险的离线复现与行为基线

- 目标：把已有最小复现变成可重复证据，记录缺陷存在；建立阶段 1 修复的回归起点。
- 依赖：WP-00；可与 WP-01 并行，只改不同测试路径。
- write_scope：`tests/test_modernization_characterization.py`；证据写账本。
- 场景：外部内联图片请求是否携带假 PAT；TG 假 401 是否进入日志/状态；保留旧 flows 清空 tasks 是否复活；未知分支是否被接管；MCP 假握手持锁与失败回收。
- 约束：MockTransport/假进程/内存配置；禁止真实网络、Keychain、磁盘用户配置；测试产生的线程须有截止并退出。表征测试明确当前缺陷，阶段 1 对应修复后改为正确契约的回归，不保留“必须有 bug 才通过”的永久断言，不用 blanket xfail 遮盖未知失败。
- run：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_modernization_characterization.py`，预期 exit 0，断言说明为 current_behavior，不是安全验收通过。
- 回退：仅撤销新测试；没有真实配置需要恢复。

## WP-03：完整 GUI 与运行负担测量

- 目标：补齐 import probe 不能回答的首屏、空闲、工作状态和退出资源数据。
- 依赖：WP-01；先准备隔离用户目录和无密钥配置，确定启动入口不会操作真实服务。
- write_scope：仅专用测量辅助脚本、测试、报告；若必须改 app_main 才能隔离，主控先限定小型注入改动并补包，不能偷偷 mock 后标成真实应用。
- 测量：当前 Apple Silicon/macOS；空配置与脱敏代表配置分别记录；多次启动报告样本数、缓存条件和分位数；首个窗口可交互时间；稳定空闲时段的 CPU/RSS；任务模拟、AI/服务的独立负载；退出后任务所属 PID/FD/线程残留。
- 口径：主进程与 Python/Node/CLI/浏览器等子进程分列；共享 RSS 不简单加总成物理内存。隔离模拟与真实业务测量分别标注，缺一项就是 not_run/partial。
- 验收：不读真实凭据、不触发真实发布/连接/安装；清理隔离进程与目录；输出可重复命令及未测项。
- 回退：停止明确归属的测量进程，移除临时配置。不能按进程名批量清理。

## WP-11：统一附件认证来源边界（D01）

- 依赖：WP-02；施工前读 SECURITY、backend-security-review，对现有 UI/TG/MCP 调用同时追踪。
- write_scope：`app_ado/ado_work_item_http.py`、`app_ado/work_item_view.py`、`app_ado/ui/work_items_tab.py`、`app_ado/tg_work_items_bridge.py`、`app_ado/mcp_ado_work_items_server.py`、对应附件测试及能力文档。
- 决策：可信 origin 来自本次明确选定 library 的 base_url，显式传到底层下载；以 scheme/host/有效端口判断来源。不可信初始 URL 一律不发请求，UI/TG 显示占位/错误，不改为匿名抓取。逐跳校验重定向：同 origin 保持认证，跨 origin 终止并返回明确错误，绝不传播 PAT；拒绝 URL 用户信息和 HTTPS 降级。若证据表明现有业务需要跨源 CDN，先由主控核验下载来源并补明示受信策略，不让施工者猜白名单或静默损失已确认功能。
- 验收：可信附件正常；恶意 host/端口/scheme/重定向不收到认证；UI/TG/MCP 一致；无真实网络。修复后对应表征改成安全回归。
- run：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_attachment_security.py`，预期 exit 0（本包创建该文件）。
- 回退：整包调用方与客户端一起回退，不只回退校验器。

## WP-12：Telegram 错误脱敏（D02）

- 依赖：WP-02；可与 WP-11 在独立 worktree 施工。
- write_scope：`app_ado/tg_control.py`、`app_ado/notifier_telegram.py`、新脱敏辅助模块、`tests/test_telegram_redaction.py` 及对应文档。
- 决策：进入日志、状态、错误上下文之前统一清理 bot URL 中 Token、认证头及已知当前 Token；保留 HTTP 状态、方法、非敏感路径和错误类型。不得用隐藏全部错误替代脱敏；不修改 ACL/命令执行行为。
- 验收：HTTP 401/409/timeout/嵌套异常与缺 Token 情况；假 Token 在日志/状态均不存在，诊断信息仍在；不连接 TG。
- run：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_telegram_redaction.py`，预期 exit 0。
- 回退：撤销本包增量；保留复现与发现记录，不清理旧日志或轮换真实 Token。

## WP-13：配置迁移与写入一致性（D04/D05）

- 依赖：WP-02；与修改同一配置模型的包串行。
- write_scope：`app_ado/store.py`、`app_ado/task_migrate.py`、`app_ado/models.py`、`app_lark/store.py`、`app_figma/store.py`、`app_main.py`、`app_ado/mcp_ado_work_items_server.py`、读取/保存上述模型的必要 UI 调用方、迁移/存储测试。派工前列明实际调用方清单。
- 决策：显式 schema 版本和迁移完成标记；合法空 tasks 不恢复 flows。纯解析/迁移返回新值，由单个写入所有者备份、校验、原子替换；读取不持久化。旧任务 ID、ACL 映射、未知字段保留；跨进程写使用锁与版本冲突检测，避免旧快照覆盖。
- 迁移入口：应用启动和独立 MCP 启动在处理业务前调用同一迁移入口，并以跨进程锁串行；普通读取遇到尚需迁移的旧配置返回明确 needs_migration，不能把旧数据当空配置。
- 无版本标记的存量配置判定：原始 YAML 缺少 `tasks` 键且存在 flows 时迁移；原始 `tasks` 键存在（包括 `[]`）则优先保留其意图，不从 flows 补回任务，仅做必要字段规范化并写完成标记；两者都不存在时建立空配置。`tasks: null`/错误类型直接报验证错误，不能按空值回退。所有情况保留 flows 及备份，不删除历史数据；原始键存在性必须在模型默认值注入之前判定。
- 验收：旧flows、新tasks、空tasks、旧ACL、重复迁移、崩溃写入、损坏文件、两个写者冲突。失败保留原件；不操作 ~/.config 真实数据。需要跨文件迁移时记录恢复检查点。
- run：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_task_migrate.py tests/test_acl_migrate.py tests/test_store_consistency.py`，预期 exit 0（创建后一文件）。
- 回退：代码与schema一起回退；先导出升级后新增数据，不自动把旧快照覆盖到有新数据的目录。

## WP-14：MCP 有界握手与完整回收（D08）

- 依赖：WP-02；保留现有协议及 Lark 刷新架构。
- write_scope：ADO/Figma 的 `mcp_server_manager.py`、`app_lark/proc_supervise.py`、`tests/test_mcp_lifecycle.py`；不得顺手改成通用共享 HTTP。
- 决策：启动/状态锁只保护短状态更新；初始化有明确截止；stdio 持续消费或明确关闭；失败/取消都 TERM→有界等待→KILL→wait→关闭管道。未回收进程不能丢句柄并显示“已停止”；状态查询不会等待网络握手锁。
- 验收：无响应、错响应、提前退出、大量 stderr、忽略 TERM、重复 start/stop、并发状态查询、EOF。用假进程及任务自己启动的无害子进程，不启动真实 MCP。
- run：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_mcp_lifecycle.py`，预期 exit 0。
- 回退：管理器与监督辅助一起回退，先停止本包测试产生的进程。

## WP-15：构建复用身份（D06）

- 依赖：WP-02；修改 TasksTab 时与阶段 2 串行。
- write_scope：`app_ado/ado_build_http.py`、`app_ado/ado_build_query.py`、`app_ado/ui/tasks_tab.py`、`tests/test_build_identity.py`。
- 决策：对本次构建分支在 ADO 中取得目标提交，再决定复用。匹配 library/project/definition、规范化分支和 commit；未知、详情失败或不匹配均不复用。不使用“当前 checkout 的 HEAD”冒充不同 build_branch 的提交；远程模式也获取目标版本。停止时区分接管与本任务创建的构建，不误取消其他调用者的任务。
- 验收：同分支不同提交、缺 branch、详情失败、不同定义、canceling 状态、agent queue 覆盖及本地/纯远端模式；模拟 REST，不触发构建。
- run：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_build_identity.py`，预期 exit 0。
- 回退：接口与任务调用方一起回退。

## WP-16：凭据流转、Lark 契约、恢复接口（D03/D12/D13）

- 依赖：WP-11/12 的安全边界及 WP-13 的一致性约定。
- 当前类型：调查/设计包；只写文档、离线契约测试与依赖清单，尚不是可直接执行的生产改造包。
- write_scope：本目录的凭据/恢复设计、测试fixture及契约测试；不读真实凭据、不注入 CLI、不登出、不替换 refresh Token。
- 交付：核验 dsh/cloudflared 支持的非 argv 凭据接口；核验每家 CLI 安全认证方式；固定 Lark/Figma 可测试版本；覆盖刷新、撤销、登出及补丁不生效的行为；明确 SQLite 运行检查点与 `(bot_identity, update_id)` 去重的事务边界。
- 验收：每个外部接口有官方文档或本地 CLI 证据；不把环境变量声称为对同用户完全保密；不以保留过期旧 Bearer 代替正常撤销。外部接口未证实标 unknown，不能让施工者猜参数。
- 下一步：主控将确认的接口转换为限定范围实施包；仅遇到新产品/安全取舍、安装或权限扩张才向用户确认。
- 回退：移除本包调查产物即可；无真实状态改变。

## 阶段验收与恢复

阶段 0 = WP-00/01/02 的自动证据 + WP-03 的明确测量状态；WP-03 未执行则阶段 0 只能标 partial，不能把导入峰值当空闲内存。

阶段 1 不以交叉审计通过为前提；各包完成必须有正确契约的自动回归和集成检查，未做的真实业务测试明确列出。完成本阶段不意味着已完成后续架构重构。

集成回归：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider`，预期 exit 0；跳过数与原因单列。检查 `git diff --check` 和允许范围，核对用户修改摘要。

需求映射：协作/署名→WP-00；真实口径/可重复→WP-01/03；关键行为证据→WP-02；风险修复→WP-11..15；未定外部接口→WP-16。所有新增分包/顺序调整记账，不静默改计划。

---

# 新产品切片

切片顺序与“搬完”标准见 [MIGRATION_PLAN.md](MIGRATION_PLAN.md)。新代码只在 `next/` 下；`next/` 以外的旧代码只读，不 import。

## S0 通用合同

- 输入版本：`rewrite/next` 上主控提交 S0 合同后的 commit（派工时写明 SHA）。
- 授权（用户 2026-10-22）：可在 `/Users/wesker/my-own-script-next` 内联网安装 S0 所需的 npm(pnpm)、cargo、uv 依赖；包管理器的用户级缓存（pnpm store、`~/.cargo/registry`、uv cache）允许使用。**不装全局工具**（不 `npm -g`、不 `cargo install`、不 `uv tool install`、不 `brew`）；Tauri CLI 以 `@tauri-apps/cli` 开发依赖方式调用。uv 不自动下载解释器（`UV_PYTHON_DOWNLOADS=never`），打包 spike 例外，且解释器装在 `next/.local/` 下。
- 施工位置：每个施工者一个独立 worktree：`git worktree add --detach .local/worktrees/<包> <SHA>`（`.local/` 已被 git 忽略）。施工者不 commit；主控以限定路径 patch 集成并提交。
- Rust 构建目录共享：`CARGO_TARGET_DIR=/Users/wesker/my-own-script-next/.local/cargo-target`（磁盘仅剩约 23 GiB，避免每个 worktree 各编一份）。
- 禁止：读取真实 Keychain / `~/.config/my-own-script` / 旧 `.venv` 外的用户数据；连接真实 ADO、TG、Lark；启动 `dev_run.sh`；改动 `next/` 以外文件（`.gitignore` 由主控改）；按进程名批量 kill。测试一律假 token。
- 参考材料（只读，git 忽略）：设计稿 `.local/design/hud/Hud-Main.dc.html`（总览常态，`denied` 属性=告警）、`Hud-WorkItem.dc.html`、`Hud-AiSession.dc.html`；rhine-lock 源码 `.local/ref/rhine-lock`（commit a4df68c，AGPL-3.0）。
- rhine-lock 复用规则：复制或改写的文件头部写 `Portions derived from rhine-lock (https://github.com/tmc5csxr9m-cpu/rhine-lock), Copyright (C) its authors, AGPL-3.0-or-later`，并在 `next/THIRD_PARTY.md` 登记文件与来源 commit；不得出现 RHINE LAB / Rhine Lab / Arknights / 莱茵 字样，不得复制原作 ∞ 标志的 SVG/生成脚本/纹理（`gen_logo.py`、`card.png`、`hex.png`），不得引入 `bgm-loop.opus`。Kenney 音效为 CC0，可用但 S0 不需要。
- 交付物：代码 + 本包测试 + `next/<子目录>/README.md`（如何运行、如何测试）+ 施工报告（改动路径、命令与输出摘要、未测、偏差、发现、清理）。
- 升级条件：需要改本合同已定接口、扩大写入范围、安装全局工具、同类失败两次 → 停下交主控。

### S0 已定接口（施工者不得自行更改）

**后端进程**（`next/backend`，包名 `toolbox_backend`，`src/` 布局，下设 `api/ services/ domain/ adapters/` 分层；Python `>=3.14`，FastAPI + uvicorn，uv 锁定）

- 启动：`python -m toolbox_backend [--dev]`。只绑 `127.0.0.1`，端口由后端自行 `bind(("127.0.0.1", 0))` 取得后交给 uvicorn（不先探测再释放端口，避免竞争）。不提供监听其他地址的选项。
- token：每次启动 `secrets.token_urlsafe(32)`；不写文件、不进日志、不进环境变量。
- 握手：服务**已开始接受连接后**，向 stdout 写且只写一行并 flush：`TOOLBOX_READY {"v":1,"port":<int>,"token":"<str>","pid":<int>}`。之后 stdout 不再输出任何内容；日志一律走 stderr，且经脱敏（不得含 token）。
- 生命周期：stdin 收到 EOF 即协调退出（壳崩溃时不留孤儿）；READY 之后 SIGTERM/SIGINT 协调退出，退出码 0（READY 之前的信号可能早于解释器执行 Python 代码，允许被信号终止，但不得挂起或再打印 READY；2026-10-22 主控裁决 S0A-003）；启动失败非 0 退出且不打印 READY 行。
- 安全中间件顺序：Host 校验 → CORS → 鉴权。
  - Host 必须等于 `127.0.0.1:<port>`，否则 400（防 DNS rebinding）；`localhost:<port>` 也拒绝。
  - CORS 允许 origin：`tauri://localhost`、`http://tauri.localhost`；`--dev` 时追加 `http://localhost:1420`、`http://127.0.0.1:1420`。允许头 `Authorization, Content-Type`，不允许 credentials。预检请求不需要 token。
  - 鉴权：所有 HTTP 路由（含 `/health`）要求 `Authorization: Bearer <token>`，用 `secrets.compare_digest`；缺失/错误 401。运行时关闭 `/docs`、`/redoc`、`/openapi.json`。
- HTTP：
  - `GET /health` → `HealthResponse {status: "ok", version: str, pid: int, uptime_s: float, alert: bool}`。
  - `POST /api/system/alert` body `AlertRequest {active: bool, reason: str | null}` → `AlertState {active, reason, changed_at}`；并广播事件 `system.alert`。用于 S0 演示告警态，后续切片的真实告警走同一事件。
- WebSocket `GET /ws/events`：Host 与 Origin 同上校验（Origin 不在允许列表 → 拒绝握手）。连接后首帧必须是 `{"type":"auth","token":"..."}`，5 秒内未收到或 token 错误 → 以 code 4401 关闭。认证成功后服务器发送事件，统一信封：`{"seq": int, "topic": str, "type": str, "ts": "<RFC3339>", "data": {...}}`，`seq` 进程内单调递增：
  - `system.hello`：`data {pid, version, alert: AlertState}`（seq 为当时最新值，客户端以此对齐）；
  - `system.heartbeat`：每 5 秒，`data {uptime_s}`；
  - `system.alert`：`data AlertState`。
  - 慢客户端：每连接有界队列（256），满则断开该连接（code 4408），不阻塞其他连接。
- 契约生成：`uv run python -m toolbox_backend.contracts` 写 `next/contracts/openapi.json` 与 `next/contracts/events.schema.json`（由 Pydantic 事件模型生成），输出确定性（排序键、末尾换行）。后端测试比对仓库内文件与当前生成结果，漂移即失败。

**前端**（`next/desktop`，pnpm）

- Vue 3 `<script setup>` + TS strict + Vite（dev 端口 1420，`strictPort`）；Tailwind v4（`@tailwindcss/vite`）；Reka UI + shadcn-vue（`components.json`，组件拷入 `src/components/ui/`，S0 只拷实际用到的）；lucide-vue-next；Vue Router；Pinia；@tanstack/vue-query；openapi-typescript + openapi-fetch；字体 `@fontsource/montserrat`、`@fontsource/jetbrains-mono`（离线打包，不连 Google Fonts）；Vitest + Vue Test Utils；ESLint flat + Prettier；vue-tsc。目录按 FRONTEND_STACK §4。
- 类型生成：`pnpm contracts:gen` 由 `../contracts/openapi.json` 生成 `src/api/schema.d.ts`（提交入库）；`pnpm contracts:check` 生成后与入库文件比对。
- 连接获取 `src/api/connection.ts`：Tauri 环境调用 command `backend_connection` → `{port, token}`；浏览器开发模式读 `import.meta.env.VITE_TOOLBOX_PORT / VITE_TOOLBOX_TOKEN`（只用于 `pnpm dev:web`，由脚本拉起后端、解析 READY 行后注入，不写文件、不进 URL）。token 不进 localStorage、URL、日志。
- 设计令牌 `src/design/tokens.css`：照搬设计稿 `.hud` 令牌（`--paper/--ink/--inv/--mute/--faint/--card/--tab/--accent-fill`，常量 `--orange #ff7b00`、`--lime #b9e432`），以 `--denied`（0..1，`@property` 注册为 `<number>` 以便过渡）color-mix 混色；文字灰用 `#5f5c57`；微型字号 ≥10px；遵守 `prefers-reduced-motion`。
- HUD 壳（单页 `/` 总览）：左栏（TOOLBOX 品牌字标、能力索引：总览/工单/任务/AI 会话/MCP/VPN/服务/设置，S0 只有总览可用，其余禁用并标 `S2..S8`）、右上时钟（`HH:MM` + `THU · 22 OCT 2026` 格式，每秒更新，组件卸载清定时器）、后端连接状态（connecting / online / reconnecting / offline，显示 pid、心跳延迟；断线指数退避重连 0.5s→最大 10s；收到新连接信息后重新认证）、告警演示开关（调用 `POST /api/system/alert`，告警态由收到的 `system.alert` 事件驱动，不在前端本地直接切换）、告警态 WARNING 框（照设计稿）、∞ 主视觉占位（自绘简单双环/线框占位并标 `PLACEHOLDER`，不得使用原作标志）。
- 关于信息：`next/THIRD_PARTY.md` 与页面底部微型文字注明视觉语言来源 rhine-lock（AGPL-3.0）与字体 OFL。

**桌面壳**（`next/desktop/src-tauri`，Tauri 2）

- `src/backend.rs`（或同等模块）为可在无 GUI 下单测的监督器：拉起命令、读握手（超时 20 秒）、子进程独立进程组（`process_group(0)`）、持有 stdin 管道、stderr 转发到壳日志（不含 token）、意外退出按退避重启（1,2,4…最大 30 秒，稳定 60 秒后重置），状态变化通过 Tauri 事件 `backend://status` 发给页面（只含 `state`、`pid`、`restarts`，不含 token）。
- 后端命令：开发模式默认 `<repo>/next/backend/.venv/bin/python -m toolbox_backend --dev`（cwd=`next/backend`），可用环境变量 `TOOLBOX_BACKEND_CMD` 覆盖；打包形态由 spike 结论决定，S0 不固化。
- Command：`backend_connection` → `{port, token}`；后端未就绪时等待（最长 20 秒）后报错。
- 关窗 = 隐藏；Dock 图标点击 / 托盘“显示窗口”恢复；托盘菜单：后端状态（禁用项，随状态更新）、显示窗口、退出。
- 退出（托盘退出、⌘Q、系统注销）只执行一次协调关闭：关 stdin → 进程组 SIGTERM → 最多等 5 秒 → SIGKILL → wait；退出后该进程组内无残留。
- 单实例：`tauri-plugin-single-instance`，第二次启动聚焦已有窗口后退出。
- 窗口：`titleBarStyle: Overlay`、隐藏标题，左栏顶部留拖拽区。capabilities 最小化（不启用 shell/fs/http 插件给页面）；CSP `connect-src` 只允许 `http://127.0.0.1:*`、`ws://127.0.0.1:*`。
- identifier 暂用 `dev.toolbox.next`，productName `TOOLBOX`（ARCHITECTURE §8 名称未决，S9 前替换）。

## S0-A：后端骨架与契约

- 依赖：S0 合同提交。可与 S0-B/C/D 并行（接口已在上文固定）。
- write_scope：`next/backend/**`、`next/contracts/**`。
- 验收（自动化，假 token）：
  1. 子进程启动 → 20 秒内读到唯一 READY 行，端口非固定、两次启动 token 不同；stdout 之后无输出；stderr 全程不含 token。
  2. 错误 Host（`evil.com`、`localhost:<port>`、`127.0.0.1:<别的端口>`）→ 400；缺 token / 错 token → 401；正确 → `/health` 200 且字段齐全；`/docs`、`/openapi.json` 不可用。
  3. CORS：`tauri://localhost` 预检通过且不需要 token；`https://evil.example` 预检不放行；非 dev 模式下 `http://localhost:1420` 不放行。
  4. WS：非法 Origin 拒绝；不发 auth 帧 5 秒内 4401；错 token 4401；正确 → `system.hello`，`POST /api/system/alert` 后收到 `system.alert`，`seq` 单调；心跳可通过注入更短间隔测试。
  5. stdin 关闭 → 进程 5 秒内退出码 0；SIGTERM → 退出码 0；无残留子进程。
  6. 契约漂移测试通过；`openapi.json` 含 `HealthResponse`、`AlertRequest`、`AlertState`，`events.schema.json` 含三种事件。
- run（在 `next/backend`）：`UV_PYTHON_DOWNLOADS=never uv sync --frozen && UV_PYTHON_DOWNLOADS=never uv run pytest -q`，预期 exit 0；`uv run ruff check .`（若引入 ruff）。
- 回退：删除 `next/backend`、`next/contracts`。

## S0-B：前端 HUD 壳

- 依赖：S0 合同。契约文件以 S0-A 产物为准；并行施工期间先按上文接口编写，`src/api/schema.d.ts` 在主控集成时用正式 `openapi.json` 重新生成（施工者可以按上文接口手写一个临时 `openapi.json` 放在**自己 worktree** 的 `next/contracts/` 供本地生成，集成时不带入）。
- write_scope：`next/desktop/**`（不含 `src-tauri/**`）、`next/THIRD_PARTY.md`。
- 验收：
  1. `pnpm install --frozen-lockfile`、`pnpm typecheck`（vue-tsc）、`pnpm lint`、`pnpm test`（Vitest）、`pnpm build` 全部 exit 0。
  2. Vitest 覆盖：告警事件把根节点 `--denied` 由 0 变 1 并显示 WARNING 框，解除后恢复；时钟格式与卸载清定时器（假定时器）；连接状态机 connecting→online→reconnecting→online（假 WebSocket），重连后重新发送 auth 帧；API 客户端带 Bearer 且 token 不出现在 URL；Tauri / dev env 两种连接来源。
  3. 令牌与设计稿一致（`--paper` 等常态值逐一断言）；文字对比度：`--ink`/`--mute` 在 `--paper` 上 ≥4.5:1（测试里计算）。
  4. 源码与构建产物中不含 `Rhine`、`RHINE`、`Arknights`、`fonts.googleapis.com`。
- run（在 `next/desktop`）：上述 pnpm 命令，预期 exit 0。
- 未测（允许）：真实 Tauri 内渲染、1280×800/1728×1117 视觉走查（主控后续截图或用户验收）。
- 回退：删除 `next/desktop` 中本包文件。

## S0-C：Tauri 薄壳与后端监督

- 依赖：S0 合同。可用测试替身后端（`src-tauri/tests/fixtures/` 下的小脚本，打印同格式 READY 行）完成监督器单测；与真实后端联调在主控集成后进行。
- write_scope：`next/desktop/src-tauri/**`；需要在 `next/desktop/package.json` 增加 `@tauri-apps/cli`、`@tauri-apps/api` 与 `tauri` 脚本时，**只交 diff 给主控合并**（该文件归 S0-B）。
- 验收：
  1. `cargo fmt --check`、`cargo clippy -- -D warnings`、`cargo test` 在 `src-tauri` exit 0（`CARGO_TARGET_DIR` 见通用合同）。
  2. 监督器测试：解析合法/非法/超时 READY 行；替身后端崩溃后按退避重启且 `restarts` 递增；协调关闭对忽略 SIGTERM 的替身在 5 秒后 SIGKILL，结束后进程组内无存活进程（用 `kill(-pgid, 0)` 判定）；关闭 stdin 后正常替身自行退出；token 不出现在日志与 `backend://status` 负载。
  3. `pnpm tauri build --debug --no-bundle` 能编出可执行文件（不签名、不安装）。
- 未测（允许）：托盘交互、关窗常驻、单实例的真实 GUI 行为——列入主控集成后的手动/脚本验证。
- 回退：删除 `src-tauri`，撤销 package.json 增量。

## S0-D：内置 Python 运行时打包 spike

- 依赖：S0 合同；需要 S0-A 的后端可运行（主控在 S0-A 集成后派工）。
- write_scope：`next/spikes/packaging/**`（脚本、说明、结果 JSON）；构建产物放 `next/.local/spike/`（忽略）。不改 `src-tauri` 正式配置，如需 Tauri 包装，用 `--config` 叠加文件放在本目录。
- 内容：对比两种方案把 `toolbox_backend` 及其依赖做成随 `.app` 分发的运行时：
  - A. python-build-standalone（用 `UV_PYTHON_INSTALL_DIR=next/.local/spike/python uv python install 3.14` 获取 aarch64 构建）+ 依赖安装到其 site-packages，裁剪测试/`__pycache__`/idle/tkinter；
  - B. PyInstaller onedir（作为 uv 开发依赖安装在 spike 自己的环境中）。
- 每种方案实测：未压缩目录大小、`tar.zst`/DMG 级压缩后大小（用 `hdiutil create -format ULFO` 或 `ditto -c -k` 二选一并注明）、冷/热启动到 READY 行耗时（各 5 次取中位数）、首个 `/health` 成功耗时、空闲 RSS；记录 macOS/芯片/版本。不签名、不公证、不复制到 `/Applications`。
- 交付：`next/spikes/packaging/README.md`（步骤与结论建议）+ `results-<日期>.json`；主控把数字写进 PROGRESS。
- 回退：删除 spike 目录与 `next/.local/spike/`。

## S0 集成验收（主控）

- 在 `rewrite/next` 集成版本上重跑 S0-A/B/C 的 run 命令；`pnpm contracts:check` 与后端漂移测试同时通过。
- 联调：用真实后端跑 `cargo test` 中的集成用例（或主控脚本）：启动壳的监督器 → 握手 → `/health` → 协调关闭 → 进程组无残留。
- 能运行时用 `pnpm tauri dev` 截图常态/告警两态（主控自查，不替代用户验收）。
- 旧应用测试：`PYTHONDONTWRITEBYTECODE=1 ../my-own-script/.venv/bin/python -m pytest -p no:cacheprovider tests` 不回退（本分支 `next/` 外无改动，作为未误改旧代码的守卫）。
- `git diff --check`；`next/` 外仅 `.gitignore`、本目录文档有改动。

# S0.5：方向 E「液态玻璃 × 游戏 UI · 工具优先」前端改造

依据：[FRONTEND_STACK.md](FRONTEND_STACK.md) §8、§8.1（§7 工业 HUD 已被替代，不再作为实现依据）；设计源码 `design/e-tool-first/`（`tasks` / `work-item` / `ai-session` 三屏，画布格式，只作视觉与结构参考，**不得直接拷贝**其 HTML/脚本，也不得引入其中的 Google Fonts 链接）。用户 2026-10-22 下达。

## S0.5 通用合同

- 输入版本：`rewrite/next` 上提交本合同的 commit（派工时写明 SHA）。
- 授权：可在 `next/desktop` 内联网安装所需 npm 依赖（pnpm，用户级 pnpm store 可用）；**不装全局工具**。可在 `rewrite/next` 本地提交（主控），不 push。
- 施工位置：`git worktree add --detach .local/worktrees/s05 <SHA>`；施工者不 commit，主控以限定路径 patch 集成。
- write_scope：`next/desktop/**`（不含 `src-tauri/**`）、`next/THIRD_PARTY.md`。后端、`next/contracts/**`、Tauri 壳不动。
- 保持不变（不得改行为）：S0 连接与安全——`src/api/connection.ts`、`client.ts`、`events.ts`、`stores/backend.ts` 的语义（token 只在内存、HTTP Bearer、WS 首帧 auth、0.5s→10s 退避重连、15s 无事件判死、告警只由 `system.alert`/`system.hello` 驱动）；`scripts/dev-web.mjs`、`contracts:gen/check` 流水线；相关既有测试必须继续通过（可调整导入路径，不得删弱断言）。
- 禁止：改 `next/` 以外文件；读真实密钥/用户配置；连真实 ADO/TG；在源码与构建产物中出现 `Rhine`/`RHINE`/`Arknights`/`fonts.googleapis.com`（既有禁词测试保留）；为通过检查删除或放宽既有连接/安全测试。
- 升级条件：需要改连接/安全接口、改后端契约、扩大写入范围、同类失败两次 → 停下交主控。

## S0.5-A：令牌、骨架、基础组件与三屏 mock

单包、单施工者（令牌/骨架/组件/页面互相耦合，拆包只会在 `tokens.css` 与壳上冲突）。施工者委派一个测试子 agent 补独立用例。

### 已定决定（施工者不得自行更改）

**设计令牌**（`src/design/tokens.css`，替换 S0 HUD 令牌；删除 `--denied` 及其 `@property`、`hud.css`）

- 背景：珍珠底线性渐变 `#f4f5f8 → #eceef3 → #f2efea`，叠两团柔光（强调色约 .28、`#b9d2ff` 约 .5，大模糊）；`body` 显式背景色 `#eef0f4`。
- 玻璃面板：白色半透明渐变（.78→.52）+ `backdrop-filter: blur(28px) saturate(180%)` + 内描边高光 + 柔阴影；不支持 backdrop-filter 时退回不透明近白。
- 文字：墨 `--ink #14161a`；次要 `--mute #545a68`；分隔线 `--line rgba(20,22,26,.09)`。
- 强调色 `--acc` 默认青柠 `#c6f432`，**只做底色（填充/条/点），不做文字色**；其上的文字用墨色。
- 告警橙 `--warn #ff6a00`：作填充时其上文字用墨色；橙色文字/图标若需要，另定深橙令牌并测在其背景上 ≥4.5:1（`#ff6a00` 在珍珠底上不足）。
- 字体：Oxanium（标题、数字、编号）、Inter（正文，回退 `PingFang SC`, `Hiragino Sans GB`, system-ui）、JetBrains Mono（标签/微型文字）。经 `@fontsource/oxanium`、`@fontsource/inter`（或 `@fontsource-variable/*`）、`@fontsource/jetbrains-mono` 离线打包；移除 `@fontsource/montserrat`。
- 切角：面板 12px、小件 6px（`clip-path` 多边形）；页签/导航/阶段条斜切 5px。
- 密度：正文 13px；表格行 44–46px；按钮与图标按钮 ≥32px；微型标签 ≥10px。

**应用骨架**（`src/app/App.vue` 重写）

- 网格：208px 侧栏 ｜ 主区（工具栏 + 内容）｜ 可收起的右侧检查器 ｜ 全宽底部状态栏。侧栏顶部保留约 28px 拖拽区（`data-tauri-drag-region`，Tauri Overlay 标题栏的真红绿灯在此；**不画假红绿灯**）。
- 侧栏：TOOLBOX 字标（自绘双纽线小图标即可）；编号导航 `01 总览 · 02 任务 · 03 工单 · 04 AI 会话 · 05 MCP · 06 服务 · 07 VPN · 08 设置`，当前项黑底白字、编号用强调色；本轮可用：任务 `/tasks`、工单 `/work-items`、AI 会话 `/ai`，其余禁用并标切片号（总览 S3、设置 S1、MCP S6、服务 S7、VPN S8，与 MIGRATION_PLAN 一致）；`/` 重定向 `/tasks`；底部「Pinned」区放 mock 的置顶/保存查询。
- 状态栏：后端（真实 store 状态：connecting/online/reconnecting/offline + pid）、VPN、TG、MCP（mock）、待处理项计数（mock）。S0 的告警演示开关保留为状态栏里的小按钮（仍只调用 `POST /api/system/alert`）。
- 检查器：每页可提供内容；收起/展开按钮键盘可达，收起后主区占满。

**基础组件**（`src/components/` 下，基于 Reka UI / shadcn-vue 拷入后改样式；只拷实际用到的）

玻璃面板（`cut` 12/6 可选）、斜切 Tabs（Reka Tabs，方向键切换）、按钮（primary 黑底 / accent 青柠底 / ghost）、图标按钮（32×32，必须有 aria-label）、输入框、⌘K 搜索框（⌘K/Ctrl+K 聚焦，Esc 失焦；本轮不实现真实搜索）、黑色块标签、结果印章（`CLEAR`/`FAILED`/`ROLLBACK`）、分段阶段条（阶段：完成/运行中/待定/失败；运行中段带流动斜纹）、分段能量条（0..N 段）、状态点（ok/run/warn/idle；run 脉冲）、告警横幅、内联审批条（左侧警示斜纹，按钮 Y 允许一次 / A 总是允许 / N 拒绝，对应快捷键；输入框聚焦时不响应快捷键；发出 `decide` 事件）。

**页面与 mock**（mock 只放 `src/features/<feature>/mock/`，页面通过一个本地函数/组合式取数，便于后续切片换成接口；不跨 feature 引用内部文件）

- 任务控制台 `features/tasks`：工具栏（标题块、视图 Tabs、⌘K、操作按钮）、任务表（名称、目标、阶段条、状态、耗时、印章）、检查器（选中任务详情、日志）、小型统计（能量条/KPI）。
- 工单 `features/work-items`：列表 ｜ 详情 ｜ AI 分析面板（检查器）。
- AI 会话 `features/ai`：会话列表 ｜ 对话流 + 内联审批条 ｜ 检查器（上下文、工具调用统计）。审批的 Y/A/N 只改 mock 状态，不连后端。
- 文案与数据虚构，可参考设计稿示例；不得出现真实主机、token、人名以外的敏感信息。

**告警**

- 状态只由 store 的 `alert`（`system.alert` 事件）驱动。告警时：主区顶部黑色横幅（显示 `reason`，无 reason 时给默认文案）；任务页 mock 中标记为出错的那一行与检查器转橙；导航“任务”角标变 `!`。工作区保持可交互（无遮罩、不拦截点击/键盘）。
- 删除：`WarningBox.vue`、`InfinityPlaceholder.vue`、`ClockBlock.vue`（及无用的 `lib/clock.ts`）、`features/overview`、HUD 文案与 rhine-lock 页脚字样中已不适用的部分（THIRD_PARTY 同步更新：E 只保留黑色块标签、微型编号、黑橙告警的理念来源）。

**动效**：只用于运行中（阶段条流动纹、状态点脉冲）、待审批（审批条轻微提示）、告警（横幅进入）。`@media (prefers-reduced-motion: reduce)` 下全部关闭。不加其他装饰动画。

### 验收

1. 在 `next/desktop`：`pnpm install --frozen-lockfile`（依赖变化后 lockfile 一并更新）、`pnpm typecheck`、`pnpm lint`、`pnpm test`、`pnpm build`、`pnpm contracts:check` 全部 exit 0。
2. 新组件各有单测（渲染、变体、键盘交互：Tabs 方向键、⌘K 聚焦、审批条 Y/A/N 及输入框聚焦时不触发、检查器收起）。
3. 三页渲染测试：常态；告警态（经假 `system.alert` 事件进入 store）出现横幅、出错行与检查器带告警标记、页面按钮仍可点击；审批条快捷键改变 mock 状态。
4. 令牌测试：关键令牌值断言；对比度计算 `--ink`、`--mute` 在珍珠底与玻璃面板（取不透明近似）上 ≥4.5:1，墨色在 `--acc`、`--warn` 填充上 ≥4.5:1；若定义深橙文字令牌，同样断言。
5. 可访问性：可点击目标 ≥32px（按钮/图标按钮/导航项样式断言或渲染尺寸约定）；所有图标按钮有 aria-label；Tab 可遍历导航、工具栏、表格行（行可聚焦、Enter 选中）、审批条。
6. 连接/安全既有测试全部通过；禁词测试通过。
7. `next/desktop/README.md` 更新（目录、组件清单、mock 位置、怎么换接口）；`next/THIRD_PARTY.md` 登记 Oxanium、Inter（SIL OFL 1.1）与移除的字体/文件。

- 未测（允许，主控集成后处理）：Tauri 内渲染、截图对照。
- 回退：从输入 SHA 恢复 `next/desktop`（不含 src-tauri）与 `next/THIRD_PARTY.md`。

## S0.5 集成验收（主控）

- 集成版本重跑上述 6 条 pnpm 命令；`git diff --check`；`next/desktop` 与文档以外无改动。
- `pnpm dev:web`（真实本地新后端、假环境）截图三屏常态 + 任务告警，与设计稿对照，差异写进 PROGRESS。
- 交叉审计异步派发，不阻塞。

# S1：设置与凭据

依据：[MIGRATION_PLAN.md](MIGRATION_PLAN.md) S1 行与 §4 WP-13 处置；[ARCHITECTURE.md](ARCHITECTURE.md) §3、§5；本文件 WP-13 的迁移判定规则；PROGRESS 中 S0、S0.5 的遗留发现。状态：用户 2026-10-22 确认合同与两项待决（见末节「S1 已决」），开始派工。

用户已定（不再讨论）：

1. 从旧配置导入是**一次性**的：预览 → 用户确认 → 执行一次；此后不同步、永不回写旧配置。
2. Keychain：旧条目只作导入来源（只读），新应用写自己的服务名，永不修改/删除旧条目。
3. 设置页本轮范围：导入（预览 + 确认执行）、ADO 连接（library/project 增删改、PAT 录入/替换、测试连接）、凭据状态（存在与否、来源，永不显示值）、常规（数据目录、版本）。TG/VPN/MCP/AI CLI 配置留给 S4/S8/S6/S5。

## S1 旧应用事实核实（主控，只读代码，`main` @ `885d186`）

- 配置目录 `~/.config/my-own-script/`（`app_ado/store.py`，`APP_ID="my-own-script"`）。YAML（无 PyYAML 时退回 JSON），**无 schema 版本**，直接 `write_text` 非原子写；`load_*` 读取时会回写迁移结果（D05）。
- 本切片导入源（配置类）：
  - `ui_settings.yaml` → `UiSettings`：`libraries[{id,name,base_url}]`、`projects[{id,library_id,collection,project}]`、`local_repos[{id,name,path}]`、`active_library_id`、`active_project_id`、`telegram_*`（chat_id、whitelist、control_enabled、notify_include_details、acl_groups、acl_members）、`work_items_{team,board,project_id,local_repo_id}`、`ai{...}`。模型未设 `extra=allow`，旧应用一保存就丢未知键，但原始文件里仍可能有。项目条目存在历史别名：id←`project_id`，library_id←`repo_id`，collection←`collection_name`，project←`name`/`project_name`（`models.project_entry_*`）。
  - `tasks.yaml` → `TaskSettings{tasks[DynamicTaskConfig], flows[FlowTaskConfig]}`（均 `extra=allow`）；`task_migrate.migrate_task_settings` 在 `tasks` 为空时从 `flows` 生成（D04 根源）；`store.migrate_acl_task_ids` 把 ACL 中的旧 flow id 映射为新任务 UUID（依赖 `legacy_flow_id`）。
  - `lark_settings.yaml`、`figma_settings.yaml`：非密设置（app_id、domain、tools、scope、端口等）。
- 不导入（运行状态/缓存，归各自切片且多数与所有权切换相关）：`tg_offset*.json`、`tg_control_state*.json`、`tg_control*.log`、`task_history.jsonl`、`services/`、`lark_login_state.json`、`lark_mcp_min_node.json`、`node/`、`vpn_chrome_profile/`、`work_item_view/`、`work_item_media/`、`cc_*`、`ccpocket/`。（主控只列了目录文件名，未读内容。）
- Keychain：`keyring`，service 恒为 `my-own-script`，account：
  - `azuredevops_pat:<library_id>`（ADO PAT，`app_ado/secrets.py`）
  - `telegram_bot_token`、`ai_bot_token:<ai_id>`、`harmony_vpn:{workspace,residency,email,password}`、`harmony_vpn:totp_secret`、`harmony_vpn:totp_filter`、`dsh_web_password`、`dsh_web_tunnel_token`、`dsh_web_tunnel_domain`、`figma_api_token`（`app_figma/secrets.py`）、`lark_app_secret:<app_id>`（`app_lark/secrets.py`）。
  - 另有 lark-mcp 自己的 service `lark-mcp` / account `encryption-key`（keytar 写，旧应用只读），属于轮换凭据体系，S1 不碰。
- library/project 管理（`ui/dialogs.py`、`ui/code_config_tab.py`）：新建 id `lib:<uuid4>` / `proj:<uuid4>`；名称不能为空，library 名唯一，base_url 去尾 `/`；project 名全局唯一（不分 library/collection）；删 library 级联删其 projects，**不删 Keychain 中的 PAT**、不检查任务引用；PAT 只写不读回 UI。
- 连通性：`httpx_ado.get_projects` → `GET {base_url}/{collection}/_apis/projects?api-version=7.0`，`Authorization: Basic base64(":"+PAT)`，`follow_redirects=False`，超时 10s/连接 5s。“获取 Collections”在旧应用是未实现的桩。

## S1 数据模型与访问边界（主控已定，施工者不得自行更改）

### 架构五问

1. **产生的数据**：新 store 文件 `config.json`（下述 schema v1）；新 Keychain service 下的 PAT 条目；导入时一份旧配置原文快照；`settings.changed` 事件。
2. **数据流**：页面 →（Bearer HTTP）→ `api/settings` 路由 → `services/settings`（唯一写入所有者）→ `adapters/config_store`（文件+锁）/ `adapters/credentials`（Keychain）/ `adapters/ado_http`（测试连接）。导入：`adapters/legacy_config`（只读旧 YAML）+ `adapters/credentials` 的只读旧条目源 → 服务层组装 → 一次写入。后续 MCP stdio 进程经同一 `config_store` 读写（S6 接入）。
3. **谁能访问**：单用户本机应用，唯一主体是持本次启动 token 的壳/页面（S0 鉴权）。没有多用户/IDOR 问题；资源边界改为“凭据值永不出后端”“PAT 只发往其所属 library 的 origin”。
4. **并发**：同一后端内多请求、多窗口，以及未来 MCP 进程同时写同一文件 → 进程内 `asyncio.Lock` + 跨进程 `fcntl.flock` + 乐观并发（`revision`）。
5. **失败与清理**：见下文「一致性与失败残留」逐步列出。

### 位置与标识

- 新应用存储标识 `APP_STORE_ID = "toolbox-next"`（用户 2026-10-22 确认；与 Tauri bundle id 解耦，S9 改名不迁移；下文 `<store-id>` 即此值）。
- 数据目录：默认 `~/Library/Application Support/<store-id>/`；可由命令行 `--data-dir` 或环境变量 `TOOLBOX_DATA_DIR` 覆盖（测试与 dev:web 必用）。目录 0700，文件 0600。
- 旧配置来源目录：默认 `~/.config/my-own-script/`；`TOOLBOX_LEGACY_CONFIG_DIR` 覆盖。后端对它**只打开读**（`open(..., "rb")`），不 mkdir、不写、不改权限、不跟随指向目录外的符号链接（`resolve()` 后须仍在该目录下）。
- 新 Keychain service：`<store-id>`；旧 service：`my-own-script`（只读）。account 命名：`ado_pat:<library_id>`。

### store schema v1（`<data-dir>/config.json`）

```text
{
  "schema_version": 1,
  "revision": <int, 每次成功写 +1，从 1 起>,
  "updated_at": "<RFC3339>",
  "ado": {
    "libraries": [{"id","name","base_url"}],
    "projects":  [{"id","library_id","collection","project"}],
    "local_repos": [{"id","name","path"}],
    "active_library_id": str|null, "active_project_id": str|null
  },
  "tasks": {"items": [DynamicTask...], "legacy_flows": [原样对象...]},
  "imported": {"telegram": {...}, "work_items": {...}, "ai": {...}, "lark": {...}, "figma": {...}, "extra": {...}},
  "import": {"state": "none|in_progress|completed|declined|failed", "source_dir", "fingerprint", "started_at", "finished_at",
             "summary": {...}, "error": str|null, "written_credentials": [account...]},
  "credentials": {"<account>": {"kind": "ado_pat", "ref": "<library_id>", "source": "imported|manual",
                                "updated_at", "state": "active|pending_delete"}}
}
```

- `ado`、`import`、`credentials` 由 S1 完整类型化与校验。`tasks.items` 按旧 `DynamicTaskConfig` 字段类型化且保留未知字段（S3 才提供编辑）；`imported.*` 是旧配置中非 S1 范围的段，**原样保留**（只校验为 JSON 对象），由 S4/S5/S6 等切片通过 schema 迁移类型化；`imported.extra` 收纳旧文件中所有未知顶层键。
- 凭据**值**永不进入该文件；`credentials` 只是元数据索引（便于显示来源、发现孤立条目）。
- id：导入的 id 原样保留（任务/ACL 引用依赖它），须匹配 `^[A-Za-z0-9:_.\-]{1,128}$`，不匹配则预览列为阻断错误；新建一律 `lib:<uuid4>` / `proj:<uuid4>`。
- 校验（新建与导入相同）：`name` 去空白后 1–100 字符，library 名唯一；`base_url` 只允许 `http`/`https`，必须有 host，不得含 userinfo/query/fragment，去尾 `/`，≤2048；`collection`、`project` 1–256，不含 `/`、`\`、控制字符（会拼进 URL 路径，按段 percent-encode）；project 唯一键为 `(library_id, collection, project)`（比旧应用的全局同名更准确）；`project.library_id` 必须存在；`active_*` 必须指向存在的条目或为 null。

### store 读写规则（D04/D05，原 WP-13）

- **唯一写入所有者**：`services/settings` 通过 `config_store.update(expected_revision, mutate_fn)` 写；其他代码只读快照。读取永不写盘、永不迁移。
- 写入：取进程内锁 → `flock(<data-dir>/config.lock, LOCK_EX)`（等待上限 5s，超时返回“存储忙”）→ 重新读盘 → 比较 `revision`（不等即冲突，不写）→ 在副本上应用变更 → 完整校验 → 写同目录临时文件（0600）→ `flush`+`fsync` → `os.replace` → `fsync` 目录 → revision+1 → 释放锁 → 广播 `settings.changed {revision}`。文件 IO 在线程中执行，不阻塞事件循环。
- 启动：文件不存在 → 视为空 store（`revision 0`，`import.state none`），首次写时创建。`schema_version` 低于当前 → 加锁迁移，先把原件复制为 `config.json.bak-v<旧版本>-<时间戳>` 再替换；高于当前（更新版本写的）或 JSON/校验损坏 → **不覆盖原件**，store 进入只读错误态，所有写接口返回 `store_unavailable`，设置页显示原因与文件位置；不自动重置。
- 导入时旧任务的判定（WP-13 规则，**在任何模型默认值注入前对原始 YAML 映射判定键存在性**）：
  - 原始 `tasks` 键缺失且 `flows` 为非空列表 → 按旧 `migrate_task_settings` 的 flows→tasks 规则生成（新 UUID，写 `legacy_flow_id`），`summary.tasks_rule="migrated_from_flows"`；
  - 原始 `tasks` 键存在（含 `[]`）→ 保留其意图，**不从 flows 补回**，只做旧应用的轻量规范化（全 0 时补 `sort_order`、空 `build_branch` 按最后 merge target/update branch 推断），`kept_tasks`；
  - 两者都缺失 → 空任务，`empty`；
  - `tasks: null` 或非列表、`flows` 非列表、元素非对象 → 预览报阻断错误，不回退成空；
  - 任何情况下 `flows` 原样存入 `tasks.legacy_flows`；随后对 `imported.telegram.acl_groups[].task_ids` 做旧 flow id → 新 UUID 映射（同旧 `migrate_acl_task_ids`）。
- 测试必须覆盖：旧 flows、新 tasks、空 tasks、null/错误类型、旧 ACL 映射、重复执行导入被拒、写入中途崩溃（替换前/后注入异常）原件完好、损坏文件只读态、两个写者冲突（同进程两协程 + 两个子进程各持锁写，后者以旧 revision 写被拒）、更高 schema 版本只读态、迁移前备份存在。

### 导入流程

- 状态机：`none → in_progress → completed`；`none → declined`；`in_progress → failed → in_progress`（重试）。`completed`/`declined` 为终态，接口不提供重新导入（用户已定一次性）。
- **前提**：`import.state ∈ {none, failed}` 且 store 中 `ado.libraries`、`ado.projects`、`tasks.items` 都为空（首次运行）；否则预览/执行返回 `import_not_allowed` 并说明原因。用户可选择“跳过导入”→ `declined`。
- 预览（只读，无任何写入）：读取 4 个 YAML 原文 → `fingerprint = sha256(各文件名 + 原文字节)`（缺失文件计入“缺失”）→ 解析与校验 → 对每个 library 用旧 service 读 `azuredevops_pat:<id>` 判定 `found|missing|unreadable`（值读入内存仅判空，立即丢弃，不返回、不缓存）→ 返回摘要：源目录、文件存在/解析错误、将导入的 libraries（id/name/base_url/PAT 状态）、projects、`tasks_rule` 与任务数、保留段名称、警告（如 http 明文 base_url、别名字段被规范化、跳过的未知元素）与阻断错误列表。YAML 用 `yaml.safe_load`（新增依赖 PyYAML），单文件上限 1 MiB，超限为阻断错误。
- 执行（请求携带预览得到的 `fingerprint`）：
  1. 加锁，重读源文件并重算指纹；不一致 → `import_source_changed`（须重新预览），不写任何东西。
  2. store 写：`import.state=in_progress`、`started_at`、`fingerprint`、计划写入的 account 列表。
  3. 逐个 library：从旧 service 读 PAT → 写新 service `ado_pat:<id>`（覆盖写，幂等）→ 记入 `written_credentials`。读不到的跳过并在摘要标 `missing`。
  4. 一次 store 写：`ado`、`tasks`、`imported`、`credentials`（source=imported）、`import.state=completed`、`summary`、`finished_at`，同时把源文件原文复制到 `<data-dir>/import/legacy-<时间戳>/`（只含这 4 个 YAML，0600）。
  - 第 3 步任一失败 → store 写 `import.state=failed` + 脱敏错误；已写入的新 PAT 条目保留并列在 `written_credentials`（重试时被同值覆盖，或用户“放弃导入”时由服务删除这些新条目后置 `declined`）。配置数据只在第 4 步一次性写入，不存在“半导入”的配置。
  - 第 4 步失败 → 同上进入 `failed`，配置保持空。
- 任何路径都不对旧目录和旧 Keychain 条目做写/删。

### 凭据（Keychain 适配器）

- 接口（`adapters/credentials.py`）：`CredentialStore`（新 service：`get/set/delete`）与 `LegacyCredentialSource`（旧 service：只有 `get`）。生产实现基于 `keyring`（新增依赖），**只在生产启动路径构造**；测试与 `--dev` 下可通过 `TOOLBOX_CREDENTIALS=memory` 使用内存实现（非 `--dev` 时设置该变量 → 启动失败）。
- PAT 只写：`PUT /api/ado/libraries/{id}/pat`；值用 `SecretStr`，长度 1–1024、无空白/控制字符。永不读回、永不出现在响应/日志/事件/异常文本中；写入后把该值登记到脱敏器的已知密钥集合（进程内）。
- 凭据状态：`present` 由一次 Keychain 查询判定（值立即丢弃）；`source`/`updated_at` 来自索引；Keychain 有值但索引缺 → `source: unknown`；索引有但 ref 已不存在或 `pending_delete` → `orphan`（可删除）。Keychain 访问失败 → `unreadable`，不报成“不存在”。
- 删除 library：先 store 写（删 library 及其 projects、清理 `active_*`、索引项置 `pending_delete`），再删新 service 条目，成功后 store 写移除索引项；Keychain 删除失败则保留 `pending_delete` 并在响应中给警告，凭据页可重试。若有 `tasks.items` 引用该 library 下的任一 project → 拒绝删除（409，列出任务名）；删 project 同理。

### ADO 测试连接（出站 HTTP 边界）

- 只对已保存 library 的 `base_url` origin 发请求：`GET {base_url}/{collection}/_apis/projects?api-version=7.0&$top=1`，Basic 认证同旧应用；`follow_redirects=False`（3xx 视为失败并报告“被重定向到 <origin>”，不跟随、不转发 PAT）；超时 10s/连接 5s；响应体最多读 1 MiB；结果只返回 `{ok, http_status, category: ok|unauthorized|forbidden|not_found|redirect|tls|timeout|network|bad_response, message}`，message 经脱敏，不含响应原文、不含 PAT。
- 可在请求体带未保存的候选 PAT 测试（同样只发往该 library origin，不保存）；不带则用已存 PAT，无 PAT → `category: no_credential`，不发请求。
- 修改 library 的 `base_url` 导致 origin 变化且已存 PAT 时：请求必须带新 PAT 或显式 `keep_pat: true`，否则 409 `pat_origin_change`（防止 PAT 被静默发往新主机）。
- 获取远端项目列表（新增项目时选择用）：`GET /api/ado/libraries/{id}/remote-projects?collection=...` 同上边界，返回 `[{name}]`（最多 500 条）。collection 列表不做（旧应用也是桩）。
- 适配器使用可注入的 `httpx` transport；测试一律 `MockTransport`，并用 socket 守卫让任何非 127.0.0.1 连接直接失败。

### HTTP 接口（全部在 S0 Bearer/Host/CORS 之后；契约由 Pydantic 模型生成）

| 方法 路径 | 说明 |
| --- | --- |
| `GET /api/settings` | `{revision, schema_version, store_state: ok|readonly_error, store_error?, data_dir, legacy_config_dir, app_version, import: {state, summary?, finished_at?}}` |
| `POST /api/settings/import/preview` | 返回预览（POST 是因为会读 Keychain，可能触发系统授权弹窗） |
| `POST /api/settings/import/execute` | `{fingerprint}` → 导入结果或 `import_source_changed`/`import_not_allowed` |
| `POST /api/settings/import/decline` | 跳过导入；`failed` 状态下同时删除 `written_credentials` 中的新条目 |
| `GET /api/ado` | libraries（含 `credential: {present, source}`）、projects、local_repos、active_* |
| `POST /api/ado/libraries`、`PATCH /api/ado/libraries/{id}`、`DELETE /api/ado/libraries/{id}` | 变更请求体/查询带 `revision`；新建可同时带 `pat` |
| `PUT /api/ado/libraries/{id}/pat`、`DELETE /api/ado/libraries/{id}/pat` | PAT 只写/删除 |
| `POST /api/ado/libraries/{id}/test` | `{collection, pat?}` → 测试结果 |
| `GET /api/ado/libraries/{id}/remote-projects` | `?collection=` |
| `POST /api/ado/projects`、`PATCH /api/ado/projects/{id}`、`DELETE /api/ado/projects/{id}` | 同上带 `revision` |
| `PUT /api/ado/active` | `{revision, library_id, project_id}` |
| `GET /api/credentials` | 凭据状态列表（kind、ref、ref_name、present、source、state、updated_at；**无值字段**） |
| `DELETE /api/credentials/{account}` | 只允许删除 `orphan`/`pending_delete` 项 |

- 错误统一 `{"detail": {"code": "...", "message": "..."}}`：`revision_conflict`(409，附当前 revision)、`validation_error`(422，不回显输入)、`not_found`(404)、`in_use`(409)、`pat_origin_change`(409)、`store_unavailable`(503)、`store_busy`(503)、`import_*`(409)、`credential_backend_error`(502)。
- 事件：新增 `settings.changed {revision}`（topic `settings`），加入 `events.schema.json`。
- 安全基础设施（并入的遗留项）：
  - **S0A-007**：新增 ASGI 中间件限制请求体（默认 64 KiB，`Settings.max_body_bytes` 可注入）：`Content-Length` 超限或流式累计超限 → 413，不读完整体；顺序 Host → CORS → Auth → BodyLimit。
  - **S0A-006**：WS 握手**必须**带 Origin 且在允许列表，无 Origin 拒绝（相应调整 S0 测试，测试客户端显式带 Origin）。
  - CORS `allow_methods` 增加 `PUT, PATCH, DELETE`。

### 安全核对表（施工与验收都按此）

| 风险 | 处置 |
| --- | --- |
| 未认证访问 | 全部新路由走 S0 中间件；测试逐个路由断言无 token 401 |
| 越权/IDOR | 单主体；以“凭据值不出后端、PAT 只发往所属 origin”替代 |
| 注入 | 无 SQL/shell；collection/project 按段编码进 URL 路径并拒绝 `/`、`\`、控制字符 |
| 路径穿越 | 只读固定文件名；旧目录 `resolve()` 后校验；数据目录内文件名固定，不接受用户路径（`local_repos.path` 只存储不访问） |
| SSRF | 出站仅限已保存 library 的 base_url origin；scheme 白名单；不跟随重定向；回应不回显原文 |
| 日志泄密 | 不记录请求体；422 不回显输入；PAT 登记脱敏器；Keychain/httpx 异常经 `redact_exception` 后再记录或返回 |
| 硬编码密钥 | 无；测试用明显的假值 |
| 请求体大小 | 64 KiB 上限（413） |
| 本地文件权限 | 数据目录 0700、文件 0600；快照同样 0600 |

## S1 通用合同

- 输入版本：本合同提交后的 `rewrite/next` commit（派工时写明 SHA）。
- 授权：后端新依赖 `pyyaml`、`keyring` 由主控在输入 SHA 中预先加入（施工者无需联网）；前端如需 pnpm 依赖可在 `next/desktop` 内安装；用户级缓存可用；不装全局工具；不装 Playwright 浏览器（e2e 推迟，列入未测）。
- 施工位置：`git worktree add --detach .local/worktrees/<包> <SHA>`；施工者不 commit，主控按限定路径 patch 集成并提交。
- **测试隔离（硬性）**：数据目录、旧配置目录一律 `tmp_path`；凭据只用 fake/内存实现，`conftest.py` 自动夹具把 `keyring` 后端设为“任何调用即抛错并记录”的守卫后端（子进程设 `PYTHON_KEYRING_BACKEND` 指向同等守卫），并在会话结束断言守卫记录为空——仅改 HOME 不足以隔离 Keychain；HTTP 只用 `MockTransport`，socket 守卫拦截非回环连接。不读真实 `~/.config/my-own-script`、真实 Keychain，不连真实 ADO/TG。
- `pnpm dev:web` 联调：脚本必须给后端设 `TOOLBOX_DATA_DIR`（临时目录）、`TOOLBOX_LEGACY_CONFIG_DIR`（仓库内假旧配置 fixture）、`TOOLBOX_CREDENTIALS=memory`（预置假 PAT），不得落到真实目录与 Keychain。
- 禁止：改 `next/` 以外文件；在任何响应/日志/事件/快照/测试快照中出现 PAT 值；对旧目录或旧 Keychain service 写/删；为通过检查删除或放宽既有连接/安全测试（S0A-006 的 Origin 变更除外，须改为显式带 Origin 而非删除用例）。
- 升级条件：需要改本合同已定的 schema、接口、错误码或安全边界；扩大写入范围；同类失败两次 → 停下交主控。
- 模型：后端施工 GPT 6.1 Sol / medium（codex），其测试子 agent GPT 6 Luna / high；前端施工 Sonnet 5.5 / medium（Claude），其测试子 agent Haiku 5.5 / medium。不可用记 unavailable，不静默替换。交叉审计异步，不阻塞。

## S1-A：后端 store、导入、凭据与 ADO 设置接口

- 依赖：本合同。可与 S1-C 并行。
- write_scope：`next/backend/**`、`next/contracts/**`。
- 内容：上文「数据模型与访问边界」全部后端部分 + S0A-006、S0A-007、CORS 方法；`--data-dir` 参数；`TOOLBOX_*` 环境变量；`next/backend/README.md` 更新；在 `next/backend/tests/fixtures/legacy/` 放假旧配置（覆盖：旧 flows、`tasks: []`、别名项目字段、未知键、http base_url），供测试与 dev:web 共用。
- 验收（自动化）：
  1. `UV_PYTHON_DOWNLOADS=never uv sync --frozen`、`uv run pytest -q`、`uv run ruff check .`、`uv run python -m toolbox_backend.contracts --check` exit 0。
  2. store：「store 读写规则」末尾列出的全部场景。
  3. 导入：预览零写入（数据目录、旧目录 mtime/内容 SHA 前后一致，fake 凭据只有 get 调用）；执行后数据正确、源目录与 fake 旧凭据未被写；指纹变化被拒；非首次被拒；第 3、4 步注入失败 → `failed`、配置为空、重试成功；`decline` 删除已写新条目；`completed` 后再执行被拒。
  4. 凭据：任何接口响应、stderr 日志、事件、`config.json`、导入快照中都搜不到假 PAT（测试对全部产物做字符串搜索）；状态 `present/missing/unreadable/orphan` 四种；删除 library 的 Keychain 失败路径留下 `pending_delete` 并可重试。
  5. ADO：校验规则（非法 scheme/userinfo/query/重复名/悬空 library_id/路径分隔符）；`revision` 冲突 409；被引用拒删 409；origin 变更 409；测试连接各分类（含 3xx 不跟随且 PAT 只出现在发往原 origin 的请求里、超 1 MiB 截断、无 PAT 不发请求）。
  6. 安全：每个新路由无 token 401；64 KiB+1 → 413（含无 Content-Length 的分块上传）；WS 无 Origin 拒绝；`PATCH/DELETE` 预检通过。
  7. 守卫：会话结束时 keyring 守卫、socket 守卫无违规记录。
- 回退：恢复 `next/backend`、`next/contracts` 到输入 SHA。

### S1-A 主控裁决（2026-10-22，施工首轮交回 partial 后）

1. **S0 契约测试的精确集合**（`tests/test_contracts.py:30/:41`）：S0 断言“恰好两条路径/三种事件”是当时合同的快照，不是不变量。改为“S0 的路径与事件仍存在且字段不变”+“S1 新路径与 `settings.changed` 存在”。这是合同演进，不算放宽。
2. **`tests/independent/test_fault_http.py:261`（拒绝 PUT/PATCH/DELETE 预检）与 `:201`（超限请求）**：S1 合同明确改变了这两处语义。改为断言允许方法恰好为 `GET, POST, PUT, PATCH, DELETE, OPTIONS`（其他如 `TRACE`/`CONNECT` 仍拒绝，非法 origin 仍拒绝）；超限请求断言 413 且不是 500。
3. **schema 迁移**：v1 是首个版本，不存在低版本数据。实现可注入的迁移注册表（`{from_version: step_fn}`，生产为空）与“迁移前备份 `config.json.bak-v<旧>-<时间戳>` → 加锁替换”的流程；测试注册一个合成的 v0→v1 步骤验证备份与替换，以及无对应步骤的低版本 → 只读错误态。
4. **指纹不一致时创建了数据目录/`config.lock`**：接受。合同中“不写任何东西”指 `config.json`、导入快照与新 Keychain 条目；数据目录与锁文件属于基础设施，可提前创建（0700/0600）。测试断言上述三类无变化即可。
5. **远端项目列表失败**：不用 422。参数非法 → 422 `validation_error`；请求已发出但失败 → 502 `ado_request_failed`，`detail` 额外带 `category`（与测试连接同一分类集合）与脱敏 `message`；无 PAT → 409 `no_credential`。
6. **沙箱内无法 bind 端口**：codex 沙箱限制，不是代码问题。施工者在沙箱内跑不依赖端口的子集；依赖真实端口的回归由主控在沙箱外运行并把结果回传。主控已在沙箱外跑首轮全量：268 passed，失败仅上述 1、2 两类共 6 条。
7. README 必须更新（合同交付物）。

## S1-C：S0/S0.5 前端遗留修复（先于 S1-B）

- 依赖：本合同；与 S1-A 并行（不碰设置页、不碰 `src/api/schema.d.ts`）。
- write_scope：`next/desktop/**`（不含 `src-tauri/**`）。
- 内容：
  - **CR-S05-001**：补回测试——未取得连接时点击告警开关 → 零请求 + 显示“后端未连接”（需让测试启动夹具可不调用 `runtime.start()`）。
  - **CR-S05-002**：状态栏告警开关点击目标 ≥32px（可保持视觉尺寸，扩大命中区）；尺寸测试纳入 Switch。
  - **CR-S05-003**：`AppTabs` 提供 tabpanel（Reka `TabsContent`）与 `aria-controls`/`aria-labelledby` 关联；不需要面板的用法保持可用。
  - **CR-S05-004**：AI 会话对话内容移到 `features/ai/mock/`，页面经 `useAiSessions()` 取。
  - **CR-S05-005**：`sent`、审批记录按会话 id 隔离；切换会话不残留。
  - **S0B-007**：`pnpm test` 在无 `dist/` 的干净检出上通过；dist 禁词检查改为 `pnpm guard:dist`（`build` 之后单独运行），不得删除该检查。
  - **S05-005**（S0 语义复核）：保持现语义——`system.hello` 的 alert 由后端模型生成，非法值只可能来自异常对端，store 保留上一状态是安全退化；主控记 rejected，本包不改。
  - **S0B-008**：S0.5 已删除总览页，界面不再显示 UPTIME；主控核实后记为 obsolete。若施工中任何位置重新显示运行时长，必须随 `system.heartbeat` 刷新。
- 验收：`pnpm install --frozen-lockfile`、`typecheck`、`lint`、`test`（先 `rm -rf dist` 再跑）、`build`、`guard:dist`、`contracts:check` exit 0；上述每项有对应测试。
- 修复后：主控续接 Codex 会话 `01a16310-6d52-7d10-b3c3-e8d1302038c4` 做 s05-cross 第二轮复核（异步）。
- 回退：恢复 `next/desktop` 到输入 SHA。

## S1-B：设置页（第一个接真实接口的页面）

- 依赖：S1-A 与 S1-C 集成后（用正式 `openapi.json` 生成 `schema.d.ts`）。
- write_scope：`next/desktop/**`（不含 `src-tauri/**`）；`scripts/dev-web.mjs` 的隔离环境变量（见通用合同）；以及下述 dev 假凭据预置所需的最小后端改动（`next/backend/src/toolbox_backend/server.py`、`adapters/credentials.py`、对应测试与 README）。
- **dev 假凭据预置**（2026-10-22 主控补充，S1-A 集成后发现内存模式下旧凭据源为空，dev:web 预览无法演示 PAT 状态）：后端新增环境变量 `TOOLBOX_DEV_FAKE_CREDENTIALS=<json 文件路径>`，**仅在 `--dev` 且 `TOOLBOX_CREDENTIALS=memory` 时接受**，否则启动失败；文件格式 `{"legacy": {account: value}, "current": {account: value}}`，分别预置旧/新内存凭据。fixture 放 `next/backend/tests/fixtures/dev-credentials.json`，值必须是明显的假值（如 `fake-pat-…`）。`dev-web.mjs` 设置 `TOOLBOX_DATA_DIR`（每次启动新建临时目录，退出删除）、`TOOLBOX_LEGACY_CONFIG_DIR=next/backend/tests/fixtures/legacy`、`TOOLBOX_CREDENTIALS=memory`、`TOOLBOX_DEV_FAKE_CREDENTIALS`。后端测试覆盖：非 dev 或非 memory 时设置该变量 → 启动失败。
- 结构（方向 E，沿用 S0.5 组件）：导航“08 设置”启用 → `/settings`；工具栏页签 `导入 · ADO 连接 · 凭据 · 常规`；主区表格/列表；检查器显示所选 library/project 详情与 PAT 表单。
  - 导入：`none`/`failed` 时显示“预览导入”，预览结果分块列出（文件、libraries + PAT 状态、projects、任务规则与数量、保留段、警告、阻断错误）；无阻断错误时“确认导入”（二次确认文案说明一次性、不回写旧配置）；“跳过导入”；`import_source_changed` 提示重新预览。`completed`/`declined` 显示只读摘要。
  - ADO 连接：libraries 与 projects 列表、增/改/删（删除二次确认；`in_use` 列出引用任务）；PAT 输入为密码框、从不预填，保存后立即清空；`pat_origin_change` 时提示“PAT 将发往新地址”并提供保留/替换选择；测试连接显示分类结果；新增 project 时可“获取远端项目”。http 明文 base_url 显示警告标签。
  - 凭据：表格显示 kind、所属、存在、来源、状态；孤立项可删除；**界面上没有任何显示凭据值的位置**。
  - 常规：数据目录、旧配置目录、应用版本、schema 版本、store 状态（只读错误态显示原因）。
- **CR-S05-003 收尾**（s05-cross round2：partially_fixed）：页签必须与真实内容建立可访问关联。工单详情页签与设置页页签用 AppTabs 插槽面板承载真实内容；筛选型用法（任务视图、工单看板列、AI 筛选）给 AppTabs 增加 `panelId` 属性——不渲染内部空面板，各 trigger 的 `aria-controls` 指向页面上承载列表的容器，该容器设 `role="tabpanel"`、`id=panelId`、`aria-labelledby` 为当前 trigger。改写 `tests/unit/s1c.test.ts:98`、`tests/independent/s1c-ui.test.ts:74` 中固化“空隐藏面板”的断言为页面级断言：当前页签 `aria-controls` 解析到的元素可见且包含当前真实内容。
- 数据：`@tanstack/vue-query` + 生成客户端；变更请求携带当前 `revision`，`revision_conflict` 时刷新并提示；收到 `settings.changed` 使查询失效。PAT 只存在于表单组件局部状态，提交后清空；不进 Pinia、query 缓存、localStorage、URL、console。
- 验收：
  1. 六条 pnpm 命令 + `guard:dist` exit 0。
  2. 组件/页面测试（假 fetch，按 openapi 形状）：导入四种状态与阻断/指纹变化；library/project 增改删、校验错误展示、409 三类；PAT 提交后输入为空且请求体之外的任何 DOM/存储/console 中无该值；测试连接各分类；凭据页无值字段；`settings.changed` 触发重新取数；页签键盘可达。
  3. 主控 `pnpm dev:web`（隔离环境）截图四个页签常态 + 只读错误态，写入 PROGRESS。
- 回退：恢复 `next/desktop` 到 S1-B 输入 SHA。

## S1-D：S1-A 交叉审计修复（CR-S1A-001..006）

- 依据：PROGRESS「S1-A 异步交叉审计」中的发现（主控已逐条核实代码属实）。
- 依赖：S1-B 集成之后（S1-B 也在改 `tests/test_s1_settings.py`、`server.py`、`adapters/credentials.py`，避免同一文件两写者）。
- write_scope：`next/backend/**`、`next/contracts/**`（如契约因错误码变化而漂移，主控集成时重新生成前端 `schema.d.ts`）。
- 已定修法：
  1. **CR-S1A-001**：`connection` 在 store 锁内只从同一快照取 `(library, PAT)`，释放锁后再发出站请求；出站请求加总时长截止（10 秒，`iter_bytes` 循环内检查 deadline，超时归 `timeout`）。导入 `execute`：先在锁外读取旧凭据到内存，锁内重算指纹（不一致即拒）后只写内存中的值；预览同样在锁外读旧凭据。进程内 `asyncio.Lock` 等待加上限（与 flock 同为 5 秒，超时 `store_busy`）。
  2. **CR-S1A-002**：`decline` 只要求 `import.state ∈ {none, failed}`，不要求 store 为空；另外 `_statuses` 把 `import.written_credentials` 中未进入索引的条目列为 `orphan`，可删除。
  3. **CR-S1A-003**：PAT 最小长度 8（校验层，`pat_value`）；`register_secret` 忽略短于 8 的值；`config_store._write` 的 `contains_secret` 闸门保留，但只对已登记（≥8）的值生效。
  4. **CR-S1A-004**：`segment` 拒绝 `.`、`..`；拼接后的 URL 路径必须以 base_url 路径为前缀，否则不发请求（`network`/“请求地址越界”）。
  5. **CR-S1A-005**：新建 library 带 PAT 时 Keychain 写入失败 → 回滚该 library（同一操作内再提交一次删除），响应 502；`_put_pat` 在 Keychain 写入成功后再提交元数据；`patch_library` 在提交新 base_url 失败时恢复旧 PAT（写入前先在内存保存旧值），恢复失败则删除新条目并标 `pending_delete`。
  6. **CR-S1A-006**：日志断言改为对原始 `record.getMessage()`/`caplog.text` 断言不含 PAT；新增 `--dev` + memory 子进程用例：写入 PAT、做一次测试连接（指向不可达 127.0.0.1 端口），断言 stderr 不含 PAT。
- 每条附回归测试（修前失败、修后通过）。验收命令同 S1-A。
- 修复后续接 S1-A 审计者做第二轮复核（异步）。

## S1-E：后端审计收尾（CR-S1A-007、008）

- 依赖：S1-D 集成（`9c94613`）。可与 S1-F 并行（文件不重叠）。
- write_scope：`next/backend/**`、`next/contracts/**`。
- 已定修法：
  1. **CR-S1A-007**：`patch_library` 提交新 base_url 抛错后，先重读磁盘配置再决定 Keychain 处置：磁盘上该 library 的 base_url 已是新值 → 保留新 PAT（若本次写了新 PAT）；仍是旧值 → 恢复旧 PAT（原先无值则删除）；重读失败或 library 不存在 → 删除该条目并尽力标 `pending_delete`，**任何情况下不把旧 PAT 恢复到可能已是新 origin 的条目上**。
  2. **CR-S1A-008**：出站读取改为逐原始块（`iter_raw()` 或不指定 `chunk_size`）检查 deadline 与 1 MiB 上限；回归用小块滴流（如每 0.5 秒 1 字节）断言约 10 秒内以 `timeout` 结束、超限以 `bad_response` 结束。
- 每项回归先在修前失败；验收命令同 S1-A（端口用例由主控沙箱外运行）。

## S1-F：设置页审计收尾（CR-S1B-001..004 + UX 小项）

- 依赖：S1-B 集成（`21957f6`）。可与 S1-E 并行。
- write_scope：`next/desktop/**`（不含 `src-tauri/**`）。
- 已定修法：
  1. **CR-S1B-001**：编辑开始（选中条目或新建）时记录**基线**（字段值 + 当时的 revision）。patch 只包含用户相对基线改动过的字段，请求携带**基线 revision**（不是缓存中的最新值）。收到 `revision_conflict`：刷新数据，保留用户改动过的字段、未改动字段更新为服务器新值，基线 revision 更新为新值，提示“设置已被其他窗口修改，已合并最新内容，请核对后再保存”；不自动重试。外部 `settings.changed` 只更新显示，不改基线（因此后续保存必然 409 → 走上述合并）。library 与 project 同样处理。
  2. **CR-S1B-002**：收到 `pat_origin_change` 时把**完整待提交请求体与目标 origin**冻结为待确认对象；确认（保留/替换）只提交该冻结请求体（再附 `keep_pat`/`pat`）；待确认期间地址与名称输入框禁用，或任何输入变化立即撤销待确认对象（二选一，须测试）；提示文案显示冻结的 origin。
  3. **CR-S1B-003**：任何写请求返回 `store_unavailable`（503）时立即刷新 overview（`store_busy` 只提示稍后重试，不改变可写状态）；在刷新确认 `store_state=ok` 之前 `writable=false`；`act()` 入口在不可写时直接拒绝并提示。
  4. **CR-S1B-004**：写响应含 `warnings` 时显示为警告提示（不显示成功文案），凭据页随即刷新以显示 `pending_delete`。
  5. UX：写操作进行中再次触发 → 提示“操作进行中，请稍候”，不静默；被拒的请求不清空 PAT 输入（只有请求真正发出后才在 `finally` 清空）；PAT 前端校验最小 8 字符（与后端一致），不满足时不发请求并提示。
- 每项有回归测试（先失败后通过）；测试子 agent 只在 `tests/independent/` 下补用例。验收命令同 S1-B。

## S1-G：设置页审计第二轮收尾（CR-S1B-005、CR-S1B-003 剩余）

- 依赖：S1-F 集成（`687948a`）。write_scope：`next/desktop/**`（不含 `src-tauri/**`）。
- 已定修法：
  1. **CR-S1B-005**：LibraryPanel、ProjectPanel 每次开始编辑（选中条目变化或新建）生成新的**编辑会话**（条目 id + 递增序号）。每个写请求发出时捕获当时的会话；响应及其回调（`pat_origin_change` 冻结、`applySaved`/基线前进、冲突合并、结果提示中涉及条目的部分）只在会话仍是当前会话时作用于组件状态，否则丢弃。冻结的确认对象同时记录目标条目 id，确认请求使用冻结的条目 id（不是当前 `props`），且只在会话未变时可确认；切换条目时清除待确认对象。
  2. **CR-S1B-003 剩余**：记录故障发生时刻；只有在故障之后**实际完成**的 overview 请求返回 `store_state=ok`（`dataUpdatedAt` 晚于故障时刻）才解除禁写；离线、刷新未执行、失败或取消均保持禁写。
- 回归：审计复现的两个场景各一条（先失败后通过）：A 保存地址时切换到 B，A 延迟返回 `pat_origin_change` / 成功，B 的请求体、基线、确认目标均不受影响；断线后 503 `store_unavailable`，在没有新的 overview 请求完成前写入口与 `act()` 都拒绝。验收命令同 S1-B。

## S1 集成验收（主控）

- 集成版本重跑 S1-A、S1-B/C 全部命令；`git diff --check`；`next/` 与本目录文档以外无改动；旧应用守卫测试不回退。
- 对照旧能力文档列功能清单（迁移/改进/有意放弃），写入 PROGRESS；资源所有权：S1 不切换任何单例资源（TG/MCP/Lark 刷新仍归旧应用）。
- 未测（允许，列入账本）：真实 Keychain 读旧条目时的系统授权弹窗与“始终允许”行为、真实 ADO 测试连接、Tauri 内渲染、Playwright e2e。
- 交叉审计：S1-A、S1-B 各一轮，异步，跨厂商优先。

## S1 已决（用户 2026-10-22 按建议确认）

1. **新应用存储标识 `<store-id>`**（数据目录名 + 新 Keychain service 名）：建议固定为 `toolbox-next`，与 Tauri bundle id（`dev.toolbox.next`，S9 前会改）解耦，S9 改名不需要迁移凭据和数据目录。备选：直接用 `dev.toolbox.next`，S9 改名时做一次迁移。
2. **本轮导入哪些密钥**：建议只导入 ADO PAT（本轮唯一用到的）；TG Bot Token、AI 专属机器人、VPN/TOTP、dsh、Figma、Lark app secret 由 S4/S5/S6/S7/S8 在启用对应能力时各做一次“该能力的一次性导入”（同样只读旧条目）。理由：最小权限，TOTP 种子与 VPN 密码不提前复制一份；每次只弹该能力的 Keychain 授权。备选：S1 一次性导入全部静态密钥（Lark 轮换凭据除外）。

结论：1 → `toolbox-next`；2 → 本轮只导入 ADO PAT，其他静态密钥由对应切片在启用能力时各做一次只读导入。

# S2：工单（只读浏览 + 媒体代理 + 本地仓库）

依据：[MIGRATION_PLAN.md](MIGRATION_PLAN.md) S2 行与 §4 WP-11 处置；[ARCHITECTURE.md](ARCHITECTURE.md) §3（外部内容由后端代取、HTML 双重清洗）、§5；本文件 WP-11 决策；PROGRESS「下一步规划」与 S1 遗留。状态：**草案，待用户确认**（见末节「S2 待用户拍板」）；确认前不派工。

范围：看板列 → 列表 → 详情（描述 / 评论 / 子项 / 历史 Updates / 附件）全部只读；附件与内联图片经后端代理（D01）；ADO HTML 后端白名单清洗 + 前端 DOMPurify；本地仓库（local_repos）增删改（S1 推迟项）；工单页由 mock 换真实接口；并入 S1 UX 小项。**不含**：TG `/wi`（S4）、MCP 分析按钮 / 复制提示词 / AI 会话（S5）、ADO MCP server（S6）、工单写操作（新建/改状态/评论，见待拍板 1）。

## S2 旧应用事实核实（主控，只读代码，`main` @ `885d186`；未读真实配置/凭据，未连 ADO）

所有调用：`Authorization: Basic base64(":"+PAT)`、`Accept: application/json`、`follow_redirects=False`、超时 15s/连接 5s（附件 30s）；URL = `{base_url}/{collection}/{project}/...`，collection/project 未编码直接拼接（新后端按段编码）。

| 用途 | 端点 | api-version | 说明 |
| --- | --- | --- | --- |
| WIQL | `POST …/{project}/_apis/wit/wiql` body `{query}` | 7.0 | 返回 `workItems[{id,url}]`，旧代码无 `$top` |
| 批量取字段 | `POST …/{project}/_apis/wit/workitemsbatch` body `{ids(≤200/批), errorPolicy:"omit", fields \| $expand:"relations"}` | 7.0 | `fields` 与 `$expand` 互斥（旧代码同） |
| 详情 | `GET …/{project}/_apis/wit/workitems/{id}?$expand=relations` | 7.0 | UI 详情用 relations 版（返回全部字段） |
| 评论 | `GET …/{project}/_apis/wit/workItems/{id}/comments?$top=50` | **7.0-preview.4** | 主键 `id`（兼容 `commentId`）；过滤 `isDeleted`；MCP 在该接口失败时降级到 updates |
| 历史 | `GET …/{project}/_apis/wit/workItems/{id}/updates?$top=50` | 7.0 | 只有 MCP 在用，UI 未展示 |
| 看板列 | `GET …/{project}/{team}/_apis/work/boards/{board}/columns` | 7.0 | 只有 MCP 在用（需 team+board 参数）；按 `stateMappings` 生成 WIQL |
| 子项 | 逐层 `workitemsbatch $expand=relations`，取 `System.LinkTypes.Hierarchy-Forward`，BFS 最深 8 层，再批量取字段 | 7.0 | 无总量上限 |
| 附件/内联图 | `GET <附件 URL>?download=true`，逐跳手动重定向（WP-11：同 origin 继续，跨 origin/降级/userinfo/超 5 跳终止） | — | 全量读入内存，无大小上限、无类型校验（UI 落盘 `~/.config/my-own-script/work_item_view/<id>/`；TG 用魔数判图并跳过 SVG） |
| 新建 | `POST …/{project}/_apis/wit/workitems/${type}`（json-patch，可 `validateOnly`） | 7.0 | 只有 MCP `ado_create_work_item`，默认类型「用户情景」，可挂父项 `Hierarchy-Reverse` |

- **UI 列表**：看板列是写死的 `["新建","待开发","开发中","测试","已关闭"]`（UI 与 TG 相同），按 `[System.BoardColumn] = '<列名>'` 做 WIQL（`list_work_items_by_board_column_value`），`ORDER BY Priority ASC, ChangedDate DESC`，带 relations 取全部字段（只为判断“有无子项”）；**不调用看板列 API**、不使用 team/board 配置。关键词（id/标题）与指派人筛选、分页（5/10/50/100/200）都在客户端。
- 旧 `UiSettings.work_items_board` 实际保存的是**选中的列名**（默认“开发中”），`work_items_team` 在 UI 中未使用；`work_items_project_id` 保存选中项目。S1 已把它们原样导入 `imported.work_items`。
- 列表字段 `DEFAULT_WORK_ITEM_FIELDS`：Id、Title、State、WorkItemType、AssignedTo、CreatedDate、ChangedDate、AreaPath、IterationPath、Tags、BoardColumn、BoardColumnDone、Priority、Severity。身份字段取 `displayName` → `uniqueName` → `name`。
- **HTML 来源**：UI 详情只渲染 `System.Description` 与评论 `text`（QTextBrowser，`setOpenExternalLinks`，无清洗）；图片 URL 来自描述/评论中的 `<img src>`（仅 http/https 绝对地址）及 relations 中 `rel=AttachedFile` 且文件名为图片的项。`ReproSteps`、`AcceptanceCriteria`、`System.History` UI 未展示。详情“在浏览器打开”用的是 API `url`（非网页地址）。
- **CR-NEXT-004 来源**：WP-11 之前的旧代码注释“ADO 常 302 到 CDN 签名 URL”（`c349243` 的 `_attachment_client`）。只是注释，无测试或日志证据；本仓库其他技能资料表明用户的 ADO 为自建 Azure DevOps Server（非 dev.azure.com），自建服务器附件通常由同主机直接返回——**推断，待用户确认**。
- 新后端现状核实：`adapters/ado_http.py` 仅有 S1 的项目列表读取；**`httpx` 只在 dev 依赖组**，生产代码却直接 import（`uv sync --no-dev` 的运行时会缺依赖）——记 CR-S2-PRE-001，主控在合同确认后的输入 SHA 中把 `httpx` 移到运行时依赖。

## S2 数据模型与访问边界（主控已定，施工者不得自行更改）

### 架构五问

1. **产生的数据**：持久化只有 `config.json` 中 `ado.local_repos` 的增删改（S1 store，同一写入规则）。工单数据**不落盘、后端不缓存**；后端只在内存维护“媒体登记表”（见下）。前端在 `localStorage` 只记非敏感的界面选择（项目 id、看板列），读写包 try/catch。
2. **数据流**：页面 →（Bearer）→ `api/work_items` 路由 → `services/work_items`（只读服务）→ 在 store 锁内从同一快照取 `(project, library, PAT)` → 释放锁 → `adapters/ado_read`（通用 ADO 读取客户端）→ ADO；HTML 字段经 `adapters/html_sanitize` 清洗并改写图片后返回。媒体：页面 `fetch` 媒体接口（Bearer）→ 服务查登记表 → 重新取快照校验 origin → `adapters/ado_read.fetch_media` 逐跳请求 → 流式读入（有上限）→ 返回字节。local_repos：页面 → `api/settings` → `services/settings`（唯一写入所有者）→ `config_store`。
3. **谁能访问**：单主体（持本次启动 token 的壳/页面）。资源边界：PAT 只发往**该 project 所属 library** 的 origin 且路径在 base_url 路径前缀下；页面不能提交任意 URL 让后端代取（只能引用后端自己登记的不透明媒体 id）。
4. **并发**：读接口无共享可变状态，除媒体登记表（只在事件循环线程上读写，出站 IO 在 `to_thread`，不持有登记表引用）。出站并发由进程级信号量限制（6）。local_repos 写入沿用 S1 revision 乐观并发。
5. **失败与清理**：只读接口失败不留状态；媒体登记表随进程消失（页面拿到 404 `media_expired` 后重取详情即可）；出站失败返回固定分类。local_repos 为单次 store 提交，无半写入。见「一致性」。

### 缓存（明确不做的与要做的）

- 后端：不缓存工单 JSON、不缓存媒体字节、不写磁盘（旧应用的 `work_item_view/` 落盘缓存不迁移）。媒体响应头 `Cache-Control: private, no-store`。
- 前端：`@tanstack/vue-query`，列表/详情/评论/历史/子项 `staleTime` 30 秒，`refetchOnWindowFocus: false`，工具栏“刷新”按钮强制重取；切换项目时清掉旧项目的查询。媒体 blob 由媒体组件持有，组件卸载或 id 变化时 `URL.revokeObjectURL`；同一详情页内相同 media id 复用一个 blob（页面级 Map，离开详情即全部回收）。
- 失效：`settings.changed` 使 `GET /api/ado` 与所有 `work-items` 查询失效（library/PAT/项目可能变了）。

### 媒体登记表（D01 的落地形式）

- 详情/评论接口在清洗 HTML 与整理 relations 时，对每个候选 URL 判定：
  - 只接受 `http`/`https` 绝对 URL（相对 URL 以该 library `base_url` 解析）；`data:`、`blob:`、`file:`、`javascript:` 等一律丢弃；
  - `origin(url) == origin(library.base_url)` 且请求路径以 base_url 路径为前缀（同 S1-D CR-S1A-004 规则），且 URL 不含 userinfo；
  - 通过 → 登记并得到 `media_id`；不通过 → 不登记，返回 `blocked_origin`（只含 scheme://host:port，不含路径/查询）。
- `media_id = secrets.token_urlsafe(16)`；条目 `{library_id, project_id, url, kind: image|attachment, name, created_at}`；同一 `(project_id, url)` 复用已有 id。TTL 30 分钟（自登记起，不滑动），总量上限 4096，超限按最早登记淘汰。只在内存，不进日志（日志只记 origin）。
- 取媒体时：按条目重新从 store 快照取 library 与 PAT；library 已删除、base_url 的 origin 或路径前缀已变化 → 404 `media_expired`（不发请求）；无 PAT → 409 `no_credential`。
- 页面永远拿不到原始附件 URL；`<img>` 的 `src` 只能是前端自己创建的 `blob:` URL；**token 不进任何 URL**（S0 规则）。

### 出站读取客户端（`adapters/ado_read.py`，S1 `ado_http.py` 的泛化）

- 统一入口：`request_json(library, pat, method, segments, params, json_body)`：路径由已校验的段（collection/project 复用 S1 `segment` 规则，按段 percent-encode；数字 id 由路由校验为 1..2147483647）拼接，拼接后断言同 origin + 路径前缀；`follow_redirects=False`（3xx → `redirect`，只报目标 origin）；`trust_env=False`；连接 5s、**总时长截止 15s**（逐原始块检查，同 S1-E）；响应体上限 **4 MiB**；JSON 解析失败 → `bad_response`；401/403/404 → `unauthorized/forbidden/not_found`；其他非 2xx → `bad_response`。PAT 进入前 `register_secret`。
- `fetch_media(library, pat, url, kind)`：首跳校验同上；带 `?download=true`（与旧应用一致，已有查询参数时追加）；**逐跳手动重定向**：最多 5 跳，每跳 `urljoin` 后重新校验 origin+路径前缀；跨 origin（含 https→http 降级、userinfo）→ 立即终止，`blocked_origin`，**不对新 origin 发任何请求**（待拍板 2 若选 B 则在此处改为“只对明示受信 origin 发无认证请求”）；超 5 跳 → `redirect`。总时长截止 30s；上限：`image` 10 MiB、`attachment` 25 MiB，以 `Content-Length` 预判 + 流式累计双重限制，超限 → `too_large`。
- 进程级 `asyncio.Semaphore(6)` 限制同时出站请求数；等待超过 15s → `busy`（503）。
- S1 测试连接/远端项目改为调用同一客户端（行为与错误分类不变，S1 既有测试必须继续通过，不得改断言）。

### 媒体响应（`GET /api/work-items/media/{media_id}`）

- 图片（`kind=image`）：**以魔数判定**类型，只接受 PNG / JPEG / GIF / WebP / BMP，`Content-Type` 用判定结果（不信远端头）；SVG、无法识别 → 不作为图片返回，`415 unsupported_media`（页面显示“非图片附件，可下载”）。
- 附件（`kind=attachment`）：`Content-Type: application/octet-stream`，`Content-Disposition: attachment; filename*=UTF-8''<编码后文件名>`（文件名取 relation `attributes.name`，去掉路径分隔与控制字符，≤255）。
- 所有媒体响应附带 `X-Content-Type-Options: nosniff`、`Content-Security-Policy: default-src 'none'; sandbox`、`Cache-Control: private, no-store`。

### HTML 清洗（后端白名单 + 前端 DOMPurify）

- 后端依赖 `nh3`（主控预先加入）。清洗对象：`System.Description`、`Microsoft.VSTS.TCM.ReproSteps`、`Microsoft.VSTS.Common.AcceptanceCriteria`、评论 `text`。单字段原文 > 1 MiB → 不清洗，返回 `{"html": null, "omitted": "too_large"}`。
- 标签白名单：`p br div span b strong i em u s strike sub sup ul ol li blockquote pre code h1 h2 h3 h4 h5 h6 hr table thead tbody tfoot tr th td a img`；其余标签去掉标签保留文本（`script style iframe object embed form input svg math` 连同内容删除）。
- 属性白名单：`a[href]`（仅 `http`/`https`/`mailto`，其余删除 href）；`img[alt]`；`td/th[colspan,rowspan]`（整数 1..100）；以及后端生成的 `img[data-media-id]`、`span[data-blocked-origin]`。**删除全部 `style`、`class`、`id`、`on*`、`src`、`srcset`、`target`**。
- 图片改写：每个 `<img>` 按「媒体登记表」判定：通过 → `<img data-media-id="…" alt="…">`（无 src）；不通过 → `<span data-blocked-origin="https://x:443">[已拦截外部图片]</span>`；`data:` 等 → `<span data-blocked-origin="">[内嵌图片未显示]</span>`。
- 前端：后端输出再经 DOMPurify，配置与上面同一白名单（`ALLOWED_TAGS`/`ALLOWED_ATTR` 显式列出，`ALLOWED_URI_REGEXP` 只放 http/https/mailto，`FORBID_ATTR` 含 style/src/srcset）；渲染后由代码把带 `data-media-id` 的 img 交给媒体加载逻辑设置 `blob:` src；链接点击一律拦截：Tauri 内用 opener 插件在系统浏览器打开，dev:web 下 `window.open(url, '_blank', 'noopener')`，**WebView 本身永不导航**。
- 历史（Updates）里的字段值一律转纯文本（标签剥离、实体解码、空白折叠），单值截断 2000 字符；前端以文本插值渲染，不用 `v-html`。

### 看板列与列表（对齐旧 UI，不引入 team/board 配置）

- 看板列：固定 `["新建","待开发","开发中","测试","已关闭"]`，默认“开发中”（与旧 UI/TG 一致）。`column` 参数必须在该列表中，否则 422（同时杜绝 WIQL 注入）；WIQL 中项目名与列名仍按 `'`→`''` 转义。
- 列表 WIQL：`SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '<project>' AND [System.BoardColumn] = '<column>' ORDER BY [Microsoft.VSTS.Common.Priority] ASC, [System.ChangedDate] DESC`，`$top=500`；再按 200/批 `workitemsbatch` 取 `DEFAULT_WORK_ITEM_FIELDS`（**不带 relations**；“有无子项”在详情里判断）。返回 `truncated = (WIQL 返回 500 条)`；batch 中被 omit 的 id 静默跳过并计数 `omitted`。只请求当前列，不为其他列算数量。
- 关键词/指派人筛选与分页在前端（≤500 条）；分页规格 10/50/100（默认 50）。

### HTTP 接口（全部在 S0 Host/CORS/Bearer/BodyLimit 之后；`project_id` 必须是 store 中存在的 project）

| 方法 路径 | 返回 |
| --- | --- |
| `GET /api/work-items/columns` | `{columns: [str], default: "开发中"}` |
| `GET /api/work-items?project_id=&column=` | `{items: [WorkItemSummary], truncated: bool, omitted: int}` |
| `GET /api/work-items/{id}?project_id=` | `WorkItemDetail` |
| `GET /api/work-items/{id}/comments?project_id=` | `{comments: [{id, author, created_date, modified_date, html \| null, omitted?}], truncated}`（`$top=100`，api-version `7.0-preview.4`，过滤已删除） |
| `GET /api/work-items/{id}/updates?project_id=` | `{updates: [{id, rev, revised_by, revised_date, fields: [{name, old, new}], relations_added: int, relations_removed: int}], truncated}`（`$top=100`；值为纯文本） |
| `GET /api/work-items/{id}/children?project_id=` | `{items: [WorkItemSummary & {parent_id, depth}], truncated}`（BFS 最深 8 层、总数 ≤500、已访问去重） |
| `GET /api/work-items/media/{media_id}` | 字节（见「媒体响应」） |
| `POST /api/ado/local-repos`、`PATCH /api/ado/local-repos/{id}`、`DELETE /api/ado/local-repos/{id}` | S1 `MutationResponse`，请求带 `revision` |

- `WorkItemSummary`：`id, title, type, state, assigned_to, board_column, priority, severity, tags: [str], area_path, iteration_path, created_date, changed_date`（`System.Tags` 按 `;` 拆分去空白）。
- `WorkItemDetail`：Summary + `rev`、`web_url`（`{base_url}/{collection}/{project}/_workitems/edit/{id}`，按段编码）、`html: {description, repro_steps, acceptance_criteria}`（每项 `{html: str|null, omitted?: "too_large"}` 或 null）、`parent_id`、`child_ids: [int]`、`attachments: [{name, size: int|null, is_image, media_id: str|null, blocked_origin: str|null}]`（来自 `AttachedFile`，`size` 取 `attributes.resourceSize`）、`links: [{kind: "pull_request"|"commit"|"hyperlink"|"other", label, url: str|null}]`（`ArtifactLink` 的 `vstfs:///Git/PullRequestId/...` 解析为 PR 编号文本，不生成可点击地址；`Hyperlink` 仅 http/https 才给 url）。不返回原始 `fields`/`relations`。
- 错误沿用 S1 形状 `{"detail": {"code", "message"}}`：`validation_error` 422；`not_found` 404（project 不存在，或 ADO 404）；`media_expired` 404；`unsupported_media` 415；`no_credential` 409；`ado_request_failed` 502（`detail.category ∈ {unauthorized, forbidden, redirect, blocked_origin, tls, timeout, network, bad_response, too_large}` + 固定脱敏文案，不回显远端原文/URL 路径）；`busy` 503；`store_unavailable` 503（store 只读错误态下读接口仍可用，只有 local_repos 写返回 503）。
- 不新增事件。

### local_repos（S1 推迟项）

- 新建 id `repo:<uuid4>`；`name` 规则同 library（1–100、唯一）；`path`：绝对路径、≤1024、无控制字符、不含 `..` 段，存规范化字符串（不 `resolve` 符号链接）。校验只用于新建/修改请求模型；**存量（S1 导入的）条目不因新规则失效**（存储模型保持宽松，GET 对不合规的存量条目给 `warnings`）。
- `GET /api/ado` 中每个 local_repo 增加 `exists: bool`（仅 `os.path.isdir`，不列目录、不读内容、不跟随到其他位置执行任何操作）。
- 删除不检查引用（S2 内没有类型化引用；`imported.work_items.local_repo_id` 是未类型化的导入段，不改）。

### 安全核对表

| 风险 | 处置 |
| --- | --- |
| 未认证访问 | 全部新路由（含媒体）走 S0 中间件；测试逐个断言无 token 401 |
| 越权/IDOR | 单主体；媒体 id 不可猜（128 bit）、只引用后端登记项；取媒体时重新校验 library origin |
| 注入 | 无 SQL/shell；WIQL 只接受固定列名白名单 + 单引号转义；路径段编码 + 前缀断言 |
| SSRF | 页面不能提交 URL；出站仅限所属 library origin + 路径前缀；重定向逐跳校验、跨源终止；scheme 白名单 |
| XSS | 后端 nh3 白名单 + 前端 DOMPurify；无 style/src/on*；SVG 不作为图片；媒体响应 nosniff + sandbox CSP；链接不在 WebView 内导航 |
| 日志泄密 | PAT 登记脱敏器；日志只记 origin、分类、耗时，不记 URL 路径/查询与响应原文 |
| 资源耗尽 | JSON 4 MiB、图片 10 MiB、附件 25 MiB；总时长截止；并发信号量 6；登记表 4096 条 |
| 路径穿越 | 后端不写文件；`local_repos.path` 只做 `isdir`；附件文件名只进 `Content-Disposition` 且已清理 |

### 一致性

- 工单接口只读，失败不留状态，重试安全。
- 媒体：登记表丢失（重启/过期/淘汰）→ 404 `media_expired`，前端提示“图片已过期”并提供“刷新详情”，不自动无限重试。
- local_repos：单次 `config_store.update`，与 S1 写入规则一致；无外部副作用。
- 详情与评论分别请求：评论失败不影响详情显示（页面分块展示错误）。

## S2 通用合同

- 输入版本：合同确认后主控提交（含依赖预置）的 `rewrite/next` commit（派工时写明 SHA）。
- 依赖由主控预先加入（施工者不联网）：后端 `nh3`，`httpx` 移入运行时依赖（CR-S2-PRE-001）；前端 `dompurify`、`@tauri-apps/plugin-opener`；Rust `tauri-plugin-opener`（`cargo fetch` 预取）。
- 施工位置：`git worktree add --detach .local/worktrees/<包> <SHA>`；施工者不 commit，主控以限定路径 binary patch（`git apply --check` 后）集成并重跑全部检查后提交。删除 worktree 前问用户。
- **测试隔离（硬性，沿用 S1）**：数据目录/旧配置目录 `tmp_path`；keyring 守卫与 socket 守卫沿用 `next/backend/tests/conftest.py`；ADO 一律 `httpx.MockTransport`（用例覆盖跨源重定向时断言跨源 host 收到零请求）；前端假 fetch 按 openapi 形状；不读真实密钥/配置，不连真实 ADO/TG。`pnpm dev:web` 联调需要一个**本地假 ADO**：后端 `--dev` 下新增 `TOOLBOX_DEV_FAKE_ADO=<fixture 目录>`（仅 `--dev` 且 `TOOLBOX_CREDENTIALS=memory` 时接受，否则启动失败），把出站 transport 换成读 fixture 的 MockTransport（含 1 张同源图片、1 个跨源图片、1 个附件、子项、评论、历史），不监听任何端口。
- 禁止：改 `next/` 以外文件；在响应/日志/事件/快照中出现 PAT；按进程名 kill（只按 pid 回收自己启动的进程）；裸 `git stash`（stash 栈与其他 worktree 共享）；在仓库内留施工/测试报告文件（报告写在最终回复里，主控存到 git 忽略的 `.local/dispatch/`）；为通过检查删除或放宽既有测试。
- 修复类改动一律“先写会失败的回归，再修”，报告附修前失败证据。
- 升级条件：需要改本合同已定的接口、错误码、限额或安全边界；扩大写入范围；同类失败两次 → 停下交主控。
- 模型：后端施工 GPT 6.1 Sol / medium（codex exec，sandbox workspace-write；沙箱不能 bind 端口，端口用例由主控沙箱外跑），测试子 agent GPT 6 Luna / high；前端施工 Sonnet 5.5 / medium（Claude 原生子 agent），测试子 agent Haiku 5.5 / medium。测试者必须**新增独立用例**（只复跑施工者测试不算独立测试）。型号不可用记 unavailable，不静默替换。交叉审计异步跨厂商（GPT 施工 → Opus 审；Claude 施工 → codex Sol high 只读审），修复后续接原审计会话复核。

## S2-A：后端工单读取、媒体代理、HTML 清洗、local_repos

- 依赖：本合同确认 + 主控依赖预置提交。
- write_scope：`next/backend/**`、`next/contracts/**`。
- 内容：上文「数据模型与访问边界」全部后端部分；S1 `ado_http` 迁到 `ado_read` 公共客户端（S1 测试不改断言）；`TOOLBOX_DEV_FAKE_ADO` 与 fixture（`next/backend/tests/fixtures/fake-ado/`，全为虚构数据）；README 更新。
- 验收（自动化）：
  1. `uv sync --frozen`、`pytest -q`、`ruff check .`、`contracts --check` exit 0（端口用例主控沙箱外跑）。
  2. 出站边界：每个接口的 URL/方法/api-version/查询参数与本合同表格一致（MockTransport 断言）；路径段编码与前缀越界拒绝；3xx 不跟随（JSON）；总时长截止（小块滴流）；4 MiB 上限；并发 >6 时排队、超时 `busy`。
  3. 媒体：同源图片 200 且 Content-Type 来自魔数；SVG/未知 → 415；同源重定向链 ≤5 跳成功、第 6 跳 `redirect`；跨源/降级/userinfo 重定向 → `blocked_origin` 且跨源 host 零请求、PAT 只出现在发往原 origin 的请求；超限 `too_large`（有/无 Content-Length 两种）；未登记/过期/淘汰 id → 404；library 删除或 base_url 改 origin 后旧 id → 404 且零请求；无 PAT → 409；响应头三项齐全；附件文件名清理。
  4. 清洗：XSS 语料（`<script>`、`onerror`、`javascript:` href、`style` 注入、`<svg onload>`、`<iframe>`、嵌套/畸形标签、实体编码的 `javascript:`、`srcset`）全部被去除；白名单标签与属性保留；图片改写三种结果；>1 MiB 字段 `omitted`。
  5. 数据整形：列表 truncated/omitted、标签拆分、身份字段回退；详情 relations → parent/child/attachments/links；评论过滤已删除与 `commentId` 兼容；历史纯文本与截断；子项 BFS 深度/上限/环去重。
  6. local_repos：校验规则、revision 冲突 409、存量不合规条目不阻断读取、`exists` 字段、store 只读态 503。
  7. 安全：每个新路由无 token 401；任何响应/日志/事件/config.json 中搜不到假 PAT；守卫无违规；`TOOLBOX_DEV_FAKE_ADO` 在非 dev / 非 memory 时启动失败。
- 回退：恢复 `next/backend`、`next/contracts` 到输入 SHA。

## S2-B：工单页接真实接口

- 依赖：S2-A 集成（主控用正式 `openapi.json` 生成 `schema.d.ts` 后派工）。可与 S2-C 并行（文件不重叠）。
- write_scope：`next/desktop/src/features/work-items/**`、`next/desktop/src/components/`（只新增工单需要的通用组件，如安全 HTML 渲染/媒体组件；不改既有组件行为）、`next/desktop/tests/**`（新增文件）、`next/desktop/src-tauri/`（**仅**为 opener 插件：`Cargo.toml` 依赖行、`src/lib.rs` 插件注册、`capabilities/*.json` 的 `opener:allow-open-url` 且 scope 仅 `http://*`、`https://*`，`tauri.conf.json` 的 `img-src` 增加 `blob:`），`next/desktop/README.md`。
- 结构：工具栏（项目选择器——来自 `GET /api/ado` 的 projects，显示“库 / 项目”；看板列 AppTabs；关键词与指派人筛选；刷新）；列表（id、类型、标题、指派、状态、优先级、变更时间；行可聚焦、Enter 打开；分页 10/50/100；`truncated` 时提示“只显示前 500 条”）；详情（页签：描述 / 评论 / 子项 / 历史 / 附件；元信息与标签；“在浏览器打开”`web_url`）；检查器保留 AI 分析面板位置但整体禁用并标 `S5`，不再含 mock 动作。
- 空/错误态：无项目 → 引导到设置；`no_credential` → “该代码库未配置 PAT”+ 跳设置；502 各分类固定文案；评论接口 `not_found` → “该服务器不支持评论接口，可查看「历史」”；`media_expired` → 占位 +“刷新详情”；`blocked_origin` → 占位显示被拦截的 origin；`unsupported_media` → “非图片，可下载”。
- 删除 `features/work-items/mock/` 中被真实接口替代的数据；`localStorage` 只存 `{project_id, column}`。
- 验收：
  1. `pnpm install --frozen-lockfile`、`typecheck`、`lint`、`rm -rf dist && pnpm test`、`build`、`guard:dist`、`contracts:check` exit 0；`src-tauri` 下 `cargo fmt --check`、`clippy -D warnings`、`cargo test` exit 0。
  2. 组件/页面测试（假 fetch）：项目/列切换带正确参数；筛选与分页；详情五个页签；各错误态；`settings.changed` 使查询失效；页签与行键盘可达。
  3. 安全：XSS 语料经后端形状输入 → DOM 中无 script/on*/style/javascript:；img 只有 `blob:` src；媒体请求带 Bearer、token 不在任何 URL/DOM/存储；blob 在卸载/切换时 revoke（断言 `revokeObjectURL` 调用）；点击链接不改变 `location`、调用 opener（Tauri）或 `window.open`（dev）。
  4. 主控 `pnpm dev:web`（假 ADO fixture）截图列表 / 详情（含同源图与被拦截占位）/ 子项 / 历史，写入 PROGRESS。
- 未测（允许）：Tauri 内 opener 与 blob 图片的实际渲染、真实 ADO。
- 回退：恢复上述路径到输入 SHA。

## S2-C：设置页「本地仓库」+ S1 UX 小项

- 依赖：S2-A 集成。可与 S2-B 并行。
- write_scope：`next/desktop/src/features/settings/**`、`next/desktop/tests/**`（新增文件；改既有断言须在报告中逐条说明理由）。
- 内容：
  1. 设置页新增页签「本地仓库」：列表（名称、路径、存在与否、存量不合规警告）、新增/修改/删除（删除二次确认）；沿用 S1-F/S1-G 的编辑会话 + 基线 revision 规则；路径为文本输入（不引入文件选择对话框）。
  2. **UX：A→B→A 显示旧草稿**——每次开始编辑会话都从当前服务器数据初始化草稿，不跨会话保留草稿。
  3. **UX：非 patch 写入后多一次 409 合并提示**——数据刷新（本窗口写入成功或 `settings.changed`）时，若正在编辑的条目在服务器上的字段值与基线完全相同，静默把基线 revision 前移到新 revision；字段不同时才走 S1-F 的冲突合并提示。须测试：本窗口切换“当前项目”后保存 library 不再出现合并提示；其他窗口改了同一条目时仍出现。
- 验收：S1-B 的 pnpm 命令全部 exit 0；上述每项有回归（UX 两项先失败后通过）。
- 回退：恢复上述路径到输入 SHA。

## S2 集成验收（主控）

- 集成版本重跑 S2-A/B/C 全部命令；`git diff --check`；`next/` 与本目录文档以外无改动；旧应用守卫测试不回退。
- 对照旧能力文档 `docs/capabilities/work-items.md` 列功能清单（迁移/改进/有意放弃/推迟），写入 PROGRESS。
- 资源所有权：S2 不切换任何单例资源（旧应用 MCP/TG 继续使用自己的配置与 PAT）。
- 未测（允许，列入账本）：真实 ADO（含 CR-NEXT-004 跨源重定向实况）、真实 Keychain、Tauri 内渲染与 opener、Playwright e2e。
- 交叉审计：S2-A（Opus）、S2-B/C（codex Sol high）各一轮，异步。

## S2 待用户拍板

1. **UI 是否提供“新建工单”**。建议：**S2 不做**，S2 保持纯只读（便于真实验收、无远端副作用）；建单能力随 S6 的 ADO MCP 工具迁移，届时再评估是否加 UI 表单。备选：S2 加简单表单（类型默认「用户情景」、标题、描述纯文本、可选父项），提交前先 `validateOnly` 预检，再确认提交；会引入第一个 ADO 写操作，需补写操作的幂等与失败处理。
2. **CR-NEXT-004：附件/内联图片是否 302 到跨源 CDN**。需要你在旧应用或浏览器里确认一次：打开一个带截图的工单，看图片是否能正常显示（旧应用 WP-11 后跨源会被拦截）；或在浏览器开发者工具里看附件请求是否被重定向到另一个域名。建议：**A 同源规则（默认）**——跨源一律拦截并显示占位，先上线；若确认存在跨源 CDN，再追加小包：B 每个 library 可配置“媒体受信 origin”列表（仅 https、精确 origin），重定向到列表内 origin 时**去掉 Authorization 头**发起无认证请求，其他跨源仍拦截。
