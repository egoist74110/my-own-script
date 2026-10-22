# 工作包（阶段 0/1 与新产品切片）

- plan_id: modernization-20261021
- revision: 3（2026-10-22 追加 S0；同日追加 S0.5 方向 E 前端改造）
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
