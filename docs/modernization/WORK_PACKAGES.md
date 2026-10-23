# 工作包（阶段 0/1 与新产品切片）

- plan_id: modernization-20261021
- revision: 8（2026-10-23 追加 S4 Telegram 合同草案与待决项；此前 7：R1 方向 B 换皮合同）
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

依据：[MIGRATION_PLAN.md](MIGRATION_PLAN.md) S2 行与 §4 WP-11 处置；[ARCHITECTURE.md](ARCHITECTURE.md) §3（外部内容由后端代取、HTML 双重清洗）、§5；本文件 WP-11 决策；PROGRESS「下一步规划」与 S1 遗留。状态：用户 2026-10-22 确认合同及两项待决（见末节「S2 已决」），开始派工。

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

## S2 已决（用户 2026-10-22 按建议确认）

结论：1 → S2 不做新建工单（纯只读，建单随 S6 MCP 迁移再评估）；2 → 先按同源规则 A 上线，跨源一律拦截显示占位；用户稍后在真实工单确认 CR-NEXT-004，若属实再追加方案 B 小包。

以下为当时的提问原文：


1. **UI 是否提供“新建工单”**。建议：**S2 不做**，S2 保持纯只读（便于真实验收、无远端副作用）；建单能力随 S6 的 ADO MCP 工具迁移，届时再评估是否加 UI 表单。备选：S2 加简单表单（类型默认「用户情景」、标题、描述纯文本、可选父项），提交前先 `validateOnly` 预检，再确认提交；会引入第一个 ADO 写操作，需补写操作的幂等与失败处理。
2. **CR-NEXT-004：附件/内联图片是否 302 到跨源 CDN**。需要你在旧应用或浏览器里确认一次：打开一个带截图的工单，看图片是否能正常显示（旧应用 WP-11 后跨源会被拦截）；或在浏览器开发者工具里看附件请求是否被重定向到另一个域名。建议：**A 同源规则（默认）**——跨源一律拦截并显示占位，先上线；若确认存在跨源 CDN，再追加小包：B 每个 library 可配置“媒体受信 origin”列表（仅 https、精确 origin），重定向到列表内 origin 时**去掉 Authorization 头**发起无认证请求，其他跨源仍拦截。

## S2-D：S2-A 交叉审计修复（CR-S2A-001..004 + 两项 info）

- 依据：PROGRESS「S2-A 异步交叉审计」（主控已复现 001–003，004 经代码核实）。
- 依赖：S2-A 集成（`bd90107`）。与 S2-B/S2-C 并行（只改后端，文件不重叠）。
- write_scope：`next/backend/**`、`next/contracts/**`。
- 已定修法：
  1. **CR-S2A-001**：`within()` 在现有解码路径判断之外，再要求 `httpx.URL(url).raw_path` 以 base_url 的**原始**路径前缀（`raw_path.rstrip(b"/") + b"/"`）开头，并拒绝原始路径中出现 `%2F`、`%5C`、`%2E`（大小写不敏感）。`build_url` 自己编码的段（空格、中文等）不受影响——必须有用例证明含空格/中文的 collection、project 仍可请求。
  2. **CR-S2A-002**：远端畸形数据一律 502 `bad_response`，不得 500：`children()` 中 `summary()` 的 `AdoFailure` 经 `failure()` 转换；`updates()` 校验 `relations.added/removed` 为 list，否则 bad_response；`_json` 的 redact 把孤立代理字符替换为 U+FFFD（键与值都处理）。回归覆盖审计的四个请求。
  3. **CR-S2A-003**：两遍 `nh3.clean` 都传 `generic_attributes=set()`；回归断言 `lang`、`title`、`dir` 被删除。
  4. **CR-S2A-004**：HTML 清洗与候选 URL 收集放进 `asyncio.to_thread`（线程中只用不可变输入与纯函数，不触碰登记表）；回到事件循环后再统一登记并替换占位，**登记表仍只在事件循环线程上读写**。单个响应（一次详情或一次评论列表）最多登记 200 个媒体（图片与附件合计），超出的图片改为 `<span data-blocked-origin="">[图片过多未显示]</span>`、附件 `media_id=null`。回归：201 张图片只登记 200；清洗期间事件循环可调度其他协程（例如并发的 `/health` 在清洗完成前返回）。
  5. **I-2**：`outbound()` 取消路径中等待工作线程时再次 `shield`，保证线程结束前不释放许可；回归模拟二次取消。
  6. **I-4（部分）**：PATCH local_repo 时只有请求里带了 `name` 才做重名检查（存量重名条目可以只改路径）。空 PATCH 推进 revision、`isdir` 的网络挂载延迟保持现状。
- 不处理：I-1（总时长按跳计算，与 S1-E 同法，合同已接受）、I-3（S1 文案变化，分类不变）。
- 每项回归先在修前失败（报告附失败摘要）；验收命令同 S2-A（端口用例由主控沙箱外运行）。
- 修复后续接 S2-A 审计者第二轮复核（异步）。

### S2-D 主控裁决（2026-10-22，施工首轮交回 partial 后）

- **CR-S2A-003 修法替换**：预置 nh3 0.3.7 的 `clean` 没有 `generic_attributes` 参数（主控核实签名）。改为在两遍共用的 `attribute_filter` 中按“标签 → 显式属性白名单”判定：属性不在该标签的白名单（首遍为 `ATTRS` + `img[src]`，末遍为 `ATTRS` + `img[data-media-id]`、`span[data-blocked-origin]`）中一律返回 `None`；白名单式，不是只拉黑 `lang`/`title`。依赖不变。回归 `test_sanitizer_drops_generic_attributes` 保持不改。

## S2-E：S2-B/S2-C 交叉审计修复（CR-S2C-001、CR-S2B-001..003）

- 依据：PROGRESS「S2-B/S2-C 异步交叉审计」（主控已对照代码核实四项）。依赖：S2 集成（`6264c6c`）。
- 拆两半并行（文件不重叠），各自 worktree，均为 `next/desktop`：
  - **S2-E1（设置页）** write_scope：`src/features/settings/**`、`tests/**`（只新增文件）。
  - **S2-E2（工单页）** write_scope：`src/features/work-items/**`、`src/components/media.ts`、`src/components/SafeHtml.vue`、`tests/**`（只新增文件）。
- 已定修法：
  1. **CR-S2C-001**（major）：`editSession` 刷新落定（settling）路径中，若存在用户已修改的字段（草稿 ≠ 基线）且服务器该字段也与基线不同 → **不 adopt**，基线字段与 revision 保持不变，使下一次保存得到 409 并走 S1-F 冲突合并提示；只有用户修改过的字段在服务器上都未变时才 adopt（替换未改字段、前移基线）。`reconcile()` 的“逐字段相同才前移”规则不变。回归：审计探针（刷新期间开始编辑、改名称、刷新返回他人同字段修改 → `revisionOpt()` 仍为旧 revision，保存出现合并提示）；library、project、本地仓库各一例。
  2. **CR-S2B-001**（major）：`settings.changed` 时先 `await qc.cancelQueries({queryKey: WI_KEY})` 再 `invalidateQueries`；所有工单查询函数把 vue-query 的 `signal` 传给 fetch（取消即中止请求）。回归：首次请求在途时项目来源变化 + `settings.changed` → 发出第二次请求，最终显示新来源数据。
  3. **CR-S2B-002**（minor）：“刷新详情”先失效并等待当前详情（及已打开的评论）重取完成，再清除失败的媒体条目；“已过期”计数只统计当前 DOM/附件仍引用的失败 id。回归：旧 id 过期 → 刷新后换新 id 且成功 → 过期提示消失、旧 id 只请求一次刷新前的那次。
  4. **CR-S2B-003**（minor）：凡有 `media_id` 的附件都显示“下载”按钮（图片附件额外显示缩略图）；回归：`is_image:true` 的附件有下载按钮且可下载。
- 每项先写会失败的回归（报告附修前失败摘要）再修；验收命令同 S2-B（`pnpm install --frozen-lockfile`、typecheck、lint、`rm -rf dist && pnpm test`、build、guard:dist、contracts:check）。
- 修复后续接 codex 审计会话 `01a163e0-93a8-7621-b72f-980852f7b7ec` 做第二轮复核（异步）。

# S3：任务执行（用户已确认，2026-10-23）

状态：**用户2026-10-23回复“均按你推荐的来”，六项全部采用推荐方案，允许按本合同派工**。实际包状态与证据以PROGRESS为准。
输入调查基线：新版 `rewrite/next @ 5c0d4c2`，旧版 `main @ 885d186`。旧应用目录只读；本轮未读真实配置/凭据、未连接真实 ADO、未执行 git 写操作调查。
依据：ARCHITECTURE §4/§5、MIGRATION_PLAN S3/§4、D06/D07/D12（含原 WP-15）；S1 已导入的 `tasks.items` 和 S2 的公共 ADO 客户端。
本合同覆盖任务查看、编辑与执行、运行历史及增量日志；不含 TG 通知/命令/ACL 编辑（S4）、AI 会话（S5）、ADO 定义编辑、通用调度器或插件框架。

## S3 旧应用事实核实（主控亲自只读核对）

以下位置相对旧目录 `/Users/wesker/my-own-script`；是静态代码事实，**不代表真实服务器已验证**。

### Git、执行顺序与日志

- `app_ado/ui/tasks_tab.py:1198` `_run`：每任务运行检查；方法注释声称全局 single-flight，但实际 `_is_task_running(task_id)` 只拦同任务，不能据注释推定仓库互斥。运行注册表/stop_event/日志消费者由页面持有。
- `:1489–1624`：`subprocess.run(argv, cwd=local_path, capture_output=True, text=True, stdin=DEVNULL, timeout=300)`，环境为整个 `os.environ` 加 `GIT_TERMINAL_PROMPT=0`。先 `git rev-parse --is-inside-work-tree`、`git status --porcelain`（脏工作区拒绝），再：
  1. 去重收集 update/push/merge 两端/build 分支，`git fetch --prune origin <branches...>`；
  2. 每个 update：`git checkout <branch>` → `git pull --ff-only`（依赖该分支 upstream，并未显式指定 origin）；
  3. 每个 merge：`git checkout <target>` → `git merge origin/<source>`；失败时取 `git diff --name-only --diff-filter=U`，尝试 `git merge --abort`，随后无条件尝试 `git reset --hard HEAD`；
  4. 每个 push：`git push origin <branch>`；最后日志记录当前 `HEAD`，不保证它就是 build_branch 的提交。
- `:1626–1674`：无本地路径时不执行 fetch/update；push 规则报错；有 merge 规则则走 ADO PR。`ado_git_ops.py:26–133`：POST `/_apis/git/repositories/{repo}/pullrequests` → GET `/{pr}` 取 `lastMergeSourceCommit.commitId` → PATCH `/{pr}`，均 `7.0`；PATCH 为 `status=completed`，deleteSourceBranch/squashMerge/transitionWorkItems 均 false；只固定等 0.5 秒，没有合并完成轮询。**这是一项 Code 写权限能力，S3 是否迁移见待决 4。**
- `tasks_tab.py:1717` 起每个启用 target 串行构建/发布，失败即停；设置 agent_queue_id 时即使 build_kind=pipeline 也走 Build API。普通路径与只发布跳过禁用 target，旧回滚循环未检查 enabled。
- 日志来源：本地 git stdout/stderr（命令完成后才追加）、应用步骤消息、构建状态与结果、Release 环境状态变化；没有拉取 ADO 原始构建控制台日志。`queue.Queue` → Qt 定时 flush → TaskCard 与共享 `_active_log_dialog`（`:120–126`、`:2035–2070`），存在跨任务共享窗口引用。`task_history.py:12–55` 只追加最终摘要到旧配置目录 `task_history.jsonl`，无运行检查点；S3 不读/导入这份真实历史。
- `models.py:102–117,175–226`：DynamicTaskConfig 字段为 id/enabled/sort_order/tg_command/tg_desc/name/project_id/local_repo_path/repo_id/repo_name/git_flow/agent_queue_id/agent_queue_name/targets；GitFlow 为 build_branch/update_branches/merges/push_branches；目标含 build_kind/build_id/release_id/stage ids 与显示名。`task_migrate.py:63–155` 空 tasks 会从 flows 再生成；S1 已解决此问题，S3 **不得重新触发 legacy_flows 迁移**。

### ADO 端点与行为（前缀均为 `{library.base_url}/{collection}/{project}`）

| 能力 / 旧代码位置 | 方法、后缀与参数 | api-version / 旧行为 |
| --- | --- | --- |
| YAML 触发/详情/最近实例，`ado_build_http.py:72–146,301–333` | POST `/_apis/pipelines/{definition}/runs`，body `resources.repositories.self.refName=refs/heads/{branch}`；GET 同路径（`$top=5`）；GET `.../runs/{run}` | `7.0`；触发不固定 commit；列表不解析 branch，详情只取 refName、不取 version |
| Classic/队列覆盖触发，`:193–227` | POST `/_apis/build/builds`，body `definition.id,sourceBranch`、可选 `queue.id` | `7.0`；不传 sourceVersion |
| Build 详情/列表，`:230–255,336–375` | GET `/_apis/build/builds/{id}`；GET `/_apis/build/builds?definitions=&branchName=refs/heads/...&$top=5&queryOrder=queueTimeDescending` | `7.0`；返回模型不保留 commit |
| 复用，`:258–298` | YAML 列表 → 运行中详情；Classic 按 definition+branch 查列表 | 只判断运行状态与分支，**不核对 commit**；YAML 详情失败且 branch 未知仍返回该实例（D06） |
| 构建停止，`:400–445` | POST `/_apis/pipelines/{definition}/runs/{run}/cancel`；404 时 PATCH `/_apis/build/builds/{run}`，body `status=cancelling`；Classic 直接 PATCH Build | `7.0`；旧代码把复用也标 build_started，可能取消他人的构建；Pipeline run id 直接当 build id 回退 |
| 只发布的构建选择，`ado_build_query.py:32–78` | GET `/_apis/build/builds?definitions=&branchName=&$top=1&queryOrder=finishTimeDescending&statusFilter=completed&resultFilter=succeeded` | `7.0`；选分支最新成功构建，不校验 commit |
| Release 定义/创建，`ado_release_http.py:94–186` | GET `/_apis/release/definitions/{definition}`；POST `/_apis/release/releases`，body `definitionId,description,artifacts`（**只取第一个 artifact 模板**的 alias/type/definitionReference，instanceReference.id/name=build id） | 默认 `6.0`；调用方 catch 任意异常后重试 `7.0`（`tasks_tab.py:1900–1917` 等），写请求结果不明时有重复创建风险 |
| Release 列表/详情，`ado_release_http.py:189–250` | GET `/_apis/release/releases?definitionId=&$top=6&queryOrder=descending`；GET `.../releases/{release}` | 默认 `6.0`，调用方异常后改 `7.0` 重读 |
| 推进/重部署环境，`:274–300` | PATCH `/_apis/release/releases/{release}/environments/{env}`，body `status=inProgress,comment` | `6.0-preview.6`；状态迁移错误抛出；不是撤回或删除 Release |

- 主路径构建轮询 `tasks_tab.py:1759–1886`：4 秒间隔（8×0.5s stop 检查），30 分钟截止；YAML 仅 succeeded/success 放行，Classic 还接受 partiallySucceeded。Release `:1923–2004`：10 秒间隔、60 分钟截止，先 definitionEnvironmentId 匹配，找不到才按名称；选中的 notStarted 环境 PATCH 一次。仅检查“已找到的环境均结束”，不会保证全部配置的 stage 都存在。
- 只发布 `_deploy_only`（`:1034–1148`）：每启用 target 取最新成功构建，创建新 Release，4 秒轮询、60 分钟截止；不改 git、不触发构建。
- 回滚 `_rollback_impl`（`:594–835`）：最近 6 个 Release 按列表下标选 offset 1..5（不限成功/失败，不是“上一个成功版本”），对历史 Release 所选环境重新 PATCH inProgress，4 秒轮询、60 分钟截止；不 git revert、不新建 Release。目标按 name 查找的旧方式可能重名串用。
- 停止 `:434–463` 仅设置 stop_event；git 阻塞命令执行期间不响应，最多等 300 秒。等待构建时 best-effort 发取消即退出，不核实远端已停止；Release 开始后停止只终止本地监控，明确不回滚。S3 不沿用“停止监控就显示已取消”。

## S3 数据模型与访问边界（主控技术裁决与用户已决）

已加载 `/Users/wesker/.ai-prompt/skills/` 下 backend-architecture-review、backend-security-review、data-consistency-review、backend-business-safety 四个 SKILL.md。本节为实现前五问、安全计划与一致性合同；实现完成还须按这些技能复核。

### 架构五问

1. **产生什么数据**：配置仍由 S1 `config.json` 保存 tasks.items 与 revision；新的 SQLite 保存 runs、steps/checkpoints、effects、run_events 与数据库版本（字段见下）。不存 PAT、认证头、完整环境或任意远端 JSON。运行快照只含显式白名单执行字段，未知字段继续保留在配置但不解释、不复制到执行快照。
2. **数据流**：Vue → S0 Bearer 路由 → TasksService（配置协调）/RunService（唯一状态转换与取消所有者）→ ConfigStore / RunStore → GitAdapter 或 ADO task adapter → S2 `ado_read` 共用出站实现。ADO 输入来自同一已验证 task/project/library 快照，凭据调用前按快照的 library 来源重新取；不得把后来改变 origin 的 PAT 发往旧 origin。回传结构化 DTO/脱敏文本 → SQLite 提交 → WS 增量 → 页面。页面关闭不终止执行。
3. **谁能访问**：S3 仍为持本次启动 token 的单一本机主体；所有新 HTTP/WS 经过 S0 Host/CORS/Bearer/首帧认证。没有另加低权限身份；未认证 401，已认证但引用不属于任务项目/definition/环境的资源拒绝，不能靠改 run_id 指向任意远端。S4 将在应用服务前加 ACL，S3 不接收客户端伪造的 requester/owner 权限。
4. **并发冲突**：同任务至多一个 queued/running/cancelling/unknown run（SQLite 部分唯一索引）；双击用幂等键。按规范化仓库真实路径及 git common-dir 加进程锁+跨进程 flock（同仓库多个 worktree 也串行），锁放新数据目录而非仓库；不同路径/符号链接不能绕过。远端发布再按 `(library来源, collection, project, release_definition_id)` 加运行预约，防两个任务交错发往同一定义。一个数据目录只允许运行一个 RunService（后端生存期 flock）；HTTP 不等待长操作。
5. **失败/清理**：先提交意图，再发每一个外部副作用，最后提交回执；SQLite 事务不跨 HTTP/git。半途失败保留已完成步骤与残留，停止后续 target，不自动撤回已 push/已部署内容；结果不明记 unknown 并只读核实。唯一生命周期 wrapper 在所有退出分支释放锁/预约、回收所属子进程、关闭管道/客户端/DB；unknown 的资源预约留在 DB 防重复，不能依赖页面回调清理。

### 配置与任务编辑（已确认完整增删改）

- 保持 config schema v1；tasks.items 是唯一来源，legacy_flows 原样保留，清空任务后永不复活。新 id `task:<uuid4>`；既有 id 永不因改名/排序改变。编辑走 SettingsService 的单次 ConfigStore.update（revision 冲突 409），不得出现第二个配置写入器。
- GET 展示全部已导入任务（包括不可执行的存量条目）并附 warnings/validation；严格校验仅作用于新增/改动字段及执行预检，不因一个旧条目无效使整页打不开。未知任务字段 round-trip 保留，不接受任意额外字段作为执行参数。targets 按数组序号绑定执行快照，不按 name 关联。
- 表单覆盖旧 DynamicTaskConfig 的执行字段：显示名/说明/启用/排序/tg_command，项目、本地路径、repo id/name、build_branch、更新/合并/推送有序规则、agent queue、targets（启用、构建种类和 definition、Release definition、stage ids/names）。id 只读；显示名辅助，不作为身份。S3 提供文本/已存列表选择，远端 definition/repo/branch 下拉发现器暂不迁移（非执行必需，页面明示输入说明）。
- tg_command 为空或匹配 `[a-z0-9_]{1,32}`，非空唯一；排序按 sort_order 再 id，提供上移/下移，后端原子提交有序 id 列表，拒绝缺失/重复 id。名称/说明≤200/2000；每任务 targets≤20，每类 git 规则≤50、stage≤50；body 沿用 64 KiB。存量超限只读警告，执行需先修正。
- id 与路径段沿用 S1 校验；ADO definition/queue/stage id 为 1..2147483647；repo id 只接受 UUID 或 S1 安全路径段。branch≤255，用 `git check-ref-format --branch` 等效规则，并拒绝前导 `-`、控制字符、refspec/修订表达式；规范化为 refs/heads，禁止表达式进入 argv。
- 新增/修改本地路径必须绝对、存在、是非 bare 工作树、不是旧/新应用源码目录及其子目录；运行时 resolve 并检查 repo root/common-dir，避免在本工具源码运行任务。执行只使用已保存路径，start body 不接受 cwd/URL/argv。临时测试仓库为显式注入的允许路径。
- 存在活动/unknown run 时同任务编辑/删除返回 409 `task_active`；运行快照不随配置刷新改变。活动运行涉及的 project/library 变更或删除也返回 `resource_active`（含在途设置写与 start 的竞争；由共用服务协调锁串行化）。其他任务照常可编辑。
- 删除若被 `imported.telegram.acl_groups[].task_ids` 引用：409 `task_referenced`，显示引用组名，不偷偷删除/扩大授权、不改旧 UUID。S3 可禁用任务；解除 ACL 引用留 S4。历史快照不级联删除。若用户选“只读+执行”，这些变更路由/UI 不开放，S3-A 保留读取/预检；其余执行合同不变。

### SQLite WAL 与日志 schema（D12）

- 位置 `<data-dir>/runs.sqlite3`（默认 `~/Library/Application Support/toolbox-next/runs.sqlite3`），同目录 WAL/SHM/运行器锁与 `locks/<sha256>.lock`。目录 0700，文件 0600，拒绝 DB/锁路径符号链接；创建 umask 077。`PRAGMA journal_mode=WAL`、foreign_keys=ON、synchronous=FULL、busy_timeout=5000；IO 在线程执行，不阻塞事件循环。短事务；SQL 参数化。RunStore 持有连接并在 shutdown 关闭。
- DB schema 独立于 config schema：`PRAGMA user_version=1`，首次建表事务化；未知高版本/损坏/迁移失败进入运行库只读错误态，不重置、不删除 WAL。读历史可读则展示，start/cancel 写失败返回 503 `run_store_unavailable`，设置/工单仍可用。不提供 S3 自动历史清理/删除功能。

| 表 | 字段与约束 |
| --- | --- |
| `runs` | `run_id TEXT PK`（UUID）、`task_id`（保留历史，不 FK 到 config）、`operation`（sync_build_release/deploy_only/rollback）、`status`（统一七态）、`phase`、`reason_code`、`created_at/started_at/updated_at/finished_at`（UTC）、`config_revision`、`task_snapshot_json`（白名单）、`request_id UNIQUE`（UUID）、`request_hash`、`cancel_requested_at`、`stop_reason`（user/timeout/shutdown）、`deadline_at`、`last_seq INTEGER DEFAULT 0`、`log_bytes INTEGER DEFAULT 0`、`state_version`（CAS）、`recovery_state`（none/pending/reconciled/manual_required）、`summary`（脱敏≤2000） |
| `run_steps` | `(run_id, step_no) PK/FK`、`kind`、`target_index`、`status`（pending/running/succeeded/failed/skipped/unknown）、`started_at/finished_at`、`checkpoint_json`（类型化 schema，含 git 原始分支/refs、锁键、预期 commit、definition、所选 stage 集、阶段截止、远端 id/结果/部署尝试号） |
| `run_effects` | `effect_id PK`、`run_id/step_no FK`、`kind`（git_push/build_create/build_cancel/release_create/env_deploy）、`intent_key UNIQUE`、`intent_json`（仅受限请求字段）、`state`（intent/confirmed/rejected/unknown）、`remote_id`、`owned`（创建归属证据，不由前端指定）、`intent_at/confirmed_at`、`error_category`；同一次远端尝试只对应一个 effect |
| `run_events` | `(run_id, seq) PK/FK`、`ts`、`type`（state/log/checkpoint）、`level`、`data_json`；seq 从 1 严格递增、跨重启不重置；日志以纯文本存储，单条≤8 KiB |

- 每次状态/检查点/effect 变更、事件追加与 runs.last_seq+state_version，在**同一 SQLite 事务**提交；提交后才广播。事务失败不发事件、不继续写远端。DB 出错后无法记录最新状态时，UI 显示运行库不可用并禁写；下次从最后持久化 intent 恢复，不谎称失败已落盘。
- 活动唯一索引：`task_id WHERE status IN ('queued','running','cancelling','unknown')`；发布资源预约表 `run_reservations(resource_key PK, run_id FK)` 与 run 创建同事务提交（Git common-dir 预检解析后登记锁键）。最终确认结束时同事务删除预约；unknown 保留。运行库的预约与配置变更协调不能只靠 UI 禁用。
- 日志追加不清空，按 run 隔离；保留至用户未来主动清理。每 run 原始日志预算 20 MiB，达到后仅追加一次截断事件、继续状态/检查点事件，始终排空子进程输出不造成背压死锁；恢复继续使用同一预算计数（写入 runs 的 `log_bytes`）。前端只保留可视分页，不在 DOM 累积全部历史。
- 所有文本在入库前脱敏（已知凭据、Authorization、URL userinfo），移除危险终端控制序列；stdout/stderr 用有界跨块缓冲，覆盖“PAT 分成多块”和超长无换行输出。消息/历史/事件/进程 stderr 都不能出现假 PAT、Basic 编码认证串或本机 Bearer；不记录完整出站 URL/响应体/子进程 env。

### 长操作接口、事件与幂等

| HTTP / WS | 固定语义 |
| --- | --- |
| `GET /api/tasks`、`GET /api/tasks/{task_id}` | `{revision, items}` / `{revision,item}`；任务 DTO 附 warnings、validation、active_run_id；不回传 imported.telegram 或凭据 |
| `POST /api/tasks`、`PATCH/DELETE /api/tasks/{task_id}`、`PUT /api/tasks/order` | 完整编辑分支才开放；请求带 revision，返回 S1 MutationResponse；PATCH 只应用显式字段，未知字段不能被表单覆盖 |
| `POST /api/tasks/{task_id}/preflight` | `{operation, revision, rollback_offset?}` → `{plan_id,expires_at,revision,task_summary,steps,targets,warnings}`；只读外部查询与本地 git 检查，**不 fetch/push/创建远端资源**；计划内冻结 definition/stage，以及只发布的 build/回滚的 Release 选择，最多保留 128 项、TTL 5 分钟、仅内存。主路径最终 commit 在 git 阶段完成后计算并持久化，不虚构预检已知合并后的 commit |
| `POST /api/tasks/{task_id}/runs`（start） | `{plan_id,request_id,ack_old_app_idle:true}` → 202 `{run_id}`；重用 request_id 且 hash 一致返回同一 run（先查持久化幂等记录，计划过期也可回读）；同 key 不同请求 409 `idempotency_conflict`。新 key 需计划有效、revision 未变且后端再次校验任务/来源；不能只靠前端确认 |
| `GET /api/runs/{run_id}`（get）、`GET /api/runs?task_id=&status=&cursor=&limit=`（list） | 当前快照与 last_seq；列表默认 50、最多100，按 created_at/run_id 游标；status 为七态白名单；未知 id 404 |
| `POST /api/runs/{run_id}/cancel`（cancel） | 202 当前快照，幂等落盘 cancel 意图；终态重复调用返回200原结果；unknown 可记录取消愿望但不能未经归属核实发远端取消 |
| `GET /api/runs/{run_id}/events?after_seq=&limit=` | 严格 seq 升序，limit默认200/最多1000，`{items,next_seq,has_more}`；无新事件返回空列表 |
| 既有 `/ws/events`（subscribe） | 新增认证后客户端消息 `{type:'subscribe',topic:'run',run_id,after_seq}` / `{type:'unsubscribe',topic:'run',run_id}`；不订阅不可接收该 run 日志。回放从持久化事件分页，完成后发 `run.subscribed {run_id,last_seq}`；注册实时队列先于读取回放水位，按 seq 去重，避免回放/实时交界丢事件。不得把全量日志塞进 hello |

- WS 沿用全进程 envelope.seq（重启可重置），新 `run.event.data={run_id,run_seq,type,payload}` 的 run_seq 才是持久游标；不得混用。每连接最多订阅8个 run，回放最多1000事件/批，慢客户端沿用队列256/4408。重连先 GET 快照/HTTP 补齐，再从最后连续 run_seq 订阅；先注册再补齐，乱序缓存/去重，发现缺口再补，不靠“收到的最大 seq”跳过缺失事件。
- 错误沿用 S1 detail 结构。422 `validation_error`；404 `not_found`；409 `revision_conflict/task_active/resource_active/task_referenced/idempotency_conflict/plan_expired/plan_changed/no_credential/unsafe_repository/unsupported_task`；503 `busy/run_store_unavailable/store_unavailable`；ADO 502 `ado_request_failed` 且沿用既有固定 category，不扩充公共 ADO 分类。已经受理的执行失败写入 run（如 `git_failed/build_failed/release_failed/interrupted/timeout/remote_unknown`），不改为迟到的 HTTP500。
- start 排队后由后端执行；全局最多4个执行 worker，queued≤100，超限503 busy。等仓库锁/预约最多5分钟（可取消），到期 failed/busy 且无外部副作用。前端断线/路由切换只退订，不 cancel。
- 状态转换仅由RunService以state_version比较更新：queued→running/cancelled/failed；running→cancelling/succeeded/failed/unknown；cancelling→cancelled/failed/unknown（若取消与整计划成功竞态，核实后可succeeded并保留取消请求）；unknown→unknown或核实后的succeeded/failed/cancelled。succeeded/failed/cancelled为不可变终态；unknown不是终态。恢复流程不从unknown自动转running执行剩余写步骤。

### Git 子进程、互斥与副作用顺序（D07）

- 只运行固定 git 可执行文件与 argv 数组，`shell=False`、stdin=DEVNULL、独立进程组。显式环境白名单（PATH、受控 HOME、语言、必要 SSH_AUTH_SOCK；不继承应用 token/PAT、代理、GIT_*、PYTHON*、LD_*/DYLD_*）。固定 GIT_TERMINAL_PROMPT=0、禁止 askpass，禁用 system/global Git 配置、hooks、外部 diff/编辑器/签名交互及递归 submodule；身份从仓库已有 user.name/email 获取，缺失给可操作错误，不替用户写全局配置。
- S3 本地真实 git 推荐只支持已配置 origin 的 SSH + 现有 SSH agent/known_hosts；不读取 Keychain 给 git 注入 PAT、不在 argv/URL/env 传凭据、不保存密码。SSH 使用 BatchMode、严格 host key 校验、有限连接时间，受控配置不接受仓库任意 sshCommand/ProxyCommand。若用户 origin 使用 HTTPS 或 SSH 别名/自定义代理，首版返回 unsupported_task 并说明（待决4一并确认兼容边界）；不静默改 remote。实现前白名单支持用户的具体 SSH 地址形式，测试只用虚构形式。
- 验证 origin 以及所有 pushurl（多 pushurl 拒绝）、url.insteadOf 重写和相关仓库配置；拒绝 userinfo 密码、ext/helper 协议及未受信命令型配置。执行前报告目标 host/仓库摘要，不打印含凭据原始 remote。file 本地远端只在测试依赖注入允许，生产禁用；测试不得用临时 HOME 冒充 Keychain/socket 隔离。
- 在实际仓库 root/common-dir 上拿锁后**重新**检查干净工作区、无 merge/rebase/cherry-pick 状态、分支/remote。先记原分支/HEAD/各变更 ref。fetch → 显式更新 → merge → push；更新使用 `checkout <branch>` + `merge --ff-only refs/remotes/origin/<branch>`，不沿用隐含 upstream 的 pull。fetch 后核实每个远端 ref；合并保持旧语义，source 为已 fetch 的 origin/source。禁止 force push、reset --hard、clean、自动 stash；冲突仅对本 run 开始的 merge 执行 merge --abort，失败保留现场并写清残留。
- 每次 git 命令最长300秒，git 阶段总长15分钟；取消/超时由唯一进程所有者 TERM 进程组→最多5秒→KILL→wait，持续排空stdout/stderr。只能回收自身记录的 pid/pgid，禁止按进程名 kill；重启后不按落盘旧 pid 直接 kill（防 pid 复用）。崩溃孤儿不得在释放仓库锁后继续写：工作子进程/监督器必须持有对应 flock 到退出，EOF/父进程丢失触发回收；S3-A 用假进程与临时仓库验证后端强杀场景。
- 不自动反向改写成功的本地 commit/ref 或远端 push；结束时尽力恢复原 checkout（不 reset 分支），无法恢复则 failed 并给 repo_needs_attention。清理失败不能伪装成功。外部工具/旧应用/用户手工 git 不持本锁，预检提示旧应用空闲并在每个写边界重检，不能承诺跨应用互斥。
- Git 完成后单独解析 **build_branch ref 的精确 commit**（不是当前 HEAD）；所有触发前核对 origin 对应分支 commit 与预期一致，未推送的本地提交不得冒充远端构建。分支已移动则 plan_changed/failed，要求重新确认；不重新选择最新提交。

### ADO 写操作、构建身份与发布安全（D06）

- 扩展 `adapters/ado_read.py` 的既有 HTTP 底座；task adapter 只负责端点/DTO/执行语义，不另建裸 httpx 客户端。S1/S2 继续走同一实现；必要时将 `services/work_items.py:OUTBOUND/outbound` 提取公共模块并随调用者切换，**全进程仍只有6个出站许可**。同 origin+解码及原始路径前缀、路径段编码、trust_env=False、不跟随重定向、连接5秒/JSON总15秒/4MiB/排队15秒/脱敏和固定错误分类全部继承。
- Build/Pipeline API 固定7.0；Release 读取先6.0，**只在明确版本不支持的400/404时**允许探测7.0，并在 preflight 冻结可用版本。401/403/timeout/network 不当版本错误。所有写操作均只用已选定版本，不能 catch-all 换版本重发。
- 复用必须读取可信详情，核对 `(library来源, collection, project, repo_id, definition_id, refs/heads/branch, commit)` 全部一致，状态为真实可等待的 queued/running（排除canceling/cancelling/completed）；任意字段缺失、详情失败、不匹配即不复用。queue override 还须 queue 一致。候选最多20个、详情串行有界；复用 `owned=false`，仅等待，绝不能取消。
- 新触发固定 commit：Pipeline body `resources.repositories.self={refName,version:<commit>}`；Build body `definition.id,sourceBranch,sourceVersion` 和可选 queue.id。远端回执/后续 Build 详情须再核对身份。Pipeline run 与 Build id 不假定相同：通过明确的关联信息核实 Build 记录，不能以数值相同作为证据；无法证明时 unknown，不创建 Release、不 fallback 取消。
- `owned=true` 只能来自本 run 已提交的创建 intent + 确认响应（或可唯一核实的关联标记）。Release description 使用非敏感标记 `toolbox-next run=<uuid> effect=<uuid>`；Build 支持的关联字段在适配器契约内验证，服务器若无可靠标记不能声称“恰好一次”。发生 timeout/断连/坏响应/落盘失败后只读对账，找不到或多个候选保持 unknown，**不得自动再次 POST**。
- 构建仅 succeeded/success 进入发布（推荐收紧 Classic partiallySucceeded，待决5）。Release 创建前读取并验证 artifact 与 build definition/project 的绑定：首版只支持一个 Build artifact，alias/type/definitionReference 必须一致；多 artifact/未知类型阻断 unsupported_task，不能静默拿第一个。
- 所有目标/定义/stage 在执行第一个写操作前预检；仅 enabled target 执行，按数组顺序串行、失败即停。stage 用 definitionEnvironmentId 精确匹配，必须**全部**存在且唯一；只有旧配置没有 id 时可用唯一名称解析并冻结为 id，名称重名/部分命中拒绝，不能悄悄只监控子集。
- 创建 Release 可能依定义自动部署其他环境。推荐创建时把定义中**全部环境列为手动**（manualEnvironments，适配器须按冻结版本核实支持），然后只对所选环境 PATCH。不修改 Release definition/审批/门禁；不能保证未选环境不会自动部署时阻断 `unsupported_task`，不默认为成功。此兼容取舍见待决6。
- 推进环境前持久化 effect 与当前 deployment attempt 基线；PATCH 后轮询新 attempt/部署记录，不能把旧 succeeded 状态当本次成功。请求结果不明先GET；未出现新 attempt 不等于允许重发。每个所选环境最多发一次部署写请求；等待审批/门禁保持 running，取消不绕过它们。
- 只发布（若确认纳入）：preflight 按7.0最新成功构建查询，核实 definition/branch/commit/仓库；冻结每 target 的具体 build id+commit，确认页明确“发布此制品，不构建当前分支”。执行时再核实该 build（不换最新）。这里的显式制品选择与主路径“运行中构建复用”不同；不要求它等于此刻 branch HEAD。
- 回滚（若确认纳入）：按每启用 target 最近6个Release预览 offset1..5，显示所选 id、制品 commit、创建时间、当前结果，冻结具体 release/env id（不同 target 不按 name 关联）。不假定历史条目成功；明确提示“重部署此历史 Release”，不 git revert、不创建新 Release；部署前再次核对 definition/stage 与部署基线。
- 无本地路径但无 git 规则时，可经7.0 Git refs只读查询 `/_apis/git/repositories/{repo}/refs?filter=heads/<branch>` 得精确 commit 后构建；须精确 refName 匹配。无本地路径且有 update/merge/push 规则时按待决4推荐阻断，不能静默跳过 update。

### 每个副作用的顺序、失败残留与恢复

| 写边界（此前必须提交 effect intent） | 成功后下一步失败的残留 | 结果不明/恢复规则 |
| --- | --- | --- |
| 本地 fetch/更新/merge（run_steps先记refs） | 本地 refs/merge commit 可已改变，保留旧/新 commit与残留说明；只 abort 本run活动merge，禁止硬重置 | 重启只读 status/ref；不自动重做 merge/push；有未收尾本地状态时 failed/interrupted+人工处理，不把纯本地失败叫 unknown |
| `git push origin <branch>`（逐分支记预期提交及原远端ref） | 前面分支可能已push，后面失败不逆向force push；构建/发布停止 | ls-remote核对每个ref；等于预期可确认写入结果（不能据此证明独占归属），被他人推进/不可查询则unknown；不得自动重push |
| POST 创建构建 | push已存在/构建可继续运行；记录 remote id、身份、owned；后续失败不撤回push | 有id只GET；无id有限查候选与关联标记，唯一证明才能绑定；否则unknown；绝不自动再次触发 |
| PATCH/POST 取消本run构建 | 已发送不等于已取消，只有确认completed才收尾 | 可重复读取；只有明确归属且远端仍运行时才允许有界取消流程；无归属/复用零取消写请求 |
| POST 创建Release | 构建已成功、Release可能已创建甚至开始部署；不得删Release/重POST/换版本重试 | id或description关联唯一核实；未确认时unknown；后续环境启动必须等待可靠回执落盘 |
| PATCH 启动所选环境（含只发布） | 先前环境可能已部署；后续失败保留结果、不自动回滚 | 查询新部署attempt；断连/崩溃不重PATCH，unknown直到全部相关远端状态已核实 |
| 回滚 PATCH 历史环境 | 历史Release环境可能已重新部署；后续target失败不自动“回滚回滚” | 与新部署同规则，必须区分本次attempt和旧终态 |

- ConfigStore 与 SQLite 不做伪跨库事务：编辑只改 config；start 在服务协调锁下取得已验证快照，然后SQLite单事务写run/steps/预约/首事件，成功后才排队，不更改config。config保存失败不创建run；DB失败不触发副作用。进程重启时快照可独立读，不靠任务仍在配置中存在。
- 新后端启动：queued且没有写意图的记录转 cancelled/reason=backend_restart；running/cancelling及含不明effect者转 unknown，标 recovery pending、发持久事件。启动只读核实，不自动push/trigger/deploy，也不自动执行剩余target。
- 有远端 id：按冻结来源和当前有效同来源凭据重新查询；凭据缺失/来源变更/404均保持unknown并提示人工核实（不能把404当已取消）。确认所有本次尝试终态且整个计划完成才能 succeeded；已确认失败则failed；确认停止且无残留运行才cancelled；仅当前build成功但尚未执行后续Release则failed/interrupted，允许新计划从制品“只发布”，不自动续写。最终状态必须覆盖所有已创建/观察的远端效果。
- unknown每30秒只读对账，最多持续15分钟；仍无法核实标 manual_required，停止后台重试，预约保留。提供 `POST /api/runs/{id}/reconcile` 202 仅重新查询（不重发写操作、无body任意远端id）；重复调用合并。UI可打开经校验的ADO链接核实，但S3不提供“强制当成功/失败”解除预约按钮。
- 取消：queued立即cancelled并释放预约；git阶段回收所属进程并清理后cancelled（push不明除外）；自建构建取消写+最多60秒轮询确认；复用构建只退出执行链且保留unknown/remote_running，后续只读对账，**不发取消**；Release/回滚已部署时停止后续写、保留unknown并只读观察，明示“远端部署可能继续，停止不会回滚”。若实际完成，保留cancel_requested/stop_reason并报告实际效果，不能无条件显示cancelled。
- 默认构建截止30分钟，Release/回滚每target60分钟；轮询间隔构建4秒、Release5秒，使用可取消async等待和monotonic截止，绝不持有出站许可sleep。git总15分钟、worker/锁排队5分钟；全run截止为排队+git+目标预算之和，冻结入快照；重启按持久UTC截止换算剩余时间，不能重置预算。明确终态才能failed/timeout，否则unknown/timeout+继续只读对账；超时不意味着远端停止。
- 明确退出沿用S0协调关闭：拒新start、落盘shutdown/取消意图、回收本地进程、关闭轮询，远端未确认保留unknown；不因退出无限等远端。页面刷新/隐藏窗口不触发shutdown。所有终止路径均执行同一个finally释放本地资源；DB预约仅在确认终态后释放。

### 安全核对（每条新路由/操作验收）

| 风险 | 合同与测试证据要求 |
| --- | --- |
| 未认证/越权 | 每条HTTP无token401、WS首帧规则；单主体权限说明；任务/项目/定义/stage归属校验，伪造remote id零写请求；S4 ACL不在S3伪实现 |
| 注入/路径 | 参数化SQL；固定argv与branch校验；不接受客户端cwd/命令/URL；repo真实路径/common-dir锁、控制字符/前导选项/符号链接绕过测试 |
| SSRF/凭据绑定 | 复用S2原始路径边界与并发6，不跟随3xx；来源变化拒绝；响应中URL不可信、仅校验同源网页链接可打开；PAT只进后端HTTP认证头 |
| 泄密/XSS | DB/WAL、日志、WS、HTTP、stderr、DOM/storage/argv/env中均搜不到假PAT/Basic/Bearer；输出纯文本，不v-html、不执行ANSI；git remote凭据URL拒绝 |
| 重复副作用 | 幂等键、任务唯一、发布预约、效果意图/回执、写超时不重POST；每个临界点故障注入并断言远端写次数 |
| 资源/生命周期 | 有界worker/队列/HTTP/输出/日志、锁超时；取消二次到达、崩溃孤儿、DB失败、慢订阅者均不泄漏许可/管道/pid/连接；unknown不释放远端预约 |

## S3 通用合同与模型分工

- **派工门禁**：用户确认本合同及待决项；主控更新已决/分包，提交输入SHA、预置依赖并生成契约后才派工。用户已确认并解除门禁，实际施工/测试/审计状态以PROGRESS最新记录为准。
- 主控 requested GPT 6.1 Sol/high，实际型号/档位无提供方元数据则unknown；后端施工 codex exec GPT 6.1 Sol/medium、sandbox workspace-write，不联网；测试子agent GPT 6 Luna/high（新增独立用例）；端口用例由主控沙箱外跑。
- 前端施工 Gemini，Antigravity CLI `agy`：确认后先 `agy models` 核验，偏好实际列出的Gemini 3.x Pro/Flash高档，无指定型号记unavailable、不换厂商。每轮一个 `agy --print --dangerously-skip-permissions`，按隔离需要加 `--sandbox`，不使用JSON/流式；首轮按cwd从 `~/.gemini/antigravity-cli/cache/last_conversations.json` 取conversation_id，续用 `--conversation <id>`，禁用 `--continue`。lark MCP启动卡超时记blocked并告用户，不擅改全局配置。前端独立测试由Gemini新增独立用例或主控另派GPT 6 Luna/high。
- 所有代码审计交Claude Code CLI Sonnet 5.5/medium，仅Read/Grep/Glob与限定只读git/测试命令，禁止Edit/Write；先核实CLI help与本机runtime已验证参数，不猜型号可用性。JSON回执记录session_id/modelUsage，修复后 `--resume <session_id>` 续接同会话、保留发现编号；429/额度不足记pending/unavailable，不换模型冒充审计。异步不阻塞其他包，不要求审到零问题。
- 审计者只读、不再派发；探针仅放其临时目录并结束前删除，不 `git archive` 导出整仓；原始输出/会话/元数据由主控留git忽略的`.local/dispatch/`、`.local/reviews/`，账本列实际通道/会话/型号证据。
- 每包worktree `.local/worktrees/<包>`，从明确输入SHA detached创建；主控集成限定write_scope的binary patch，先核对用户脏文件和新文件不存在，再 `git apply --check`、应用、重跑集成检查后本地commit，不push。施工者不commit；删除worktree前问用户。
- 测试必须临时数据目录+假凭据+MockTransport+临时git仓库（`git init --bare`当远端），沿用后端conftest的keyring/socket守卫；Git子进程另以协议/remote/环境守卫断言只访问临时bare，不依赖Python socket守卫拦git。禁止读真实配置/Keychain、连接真实ADO/TG、push真实远端或触发真实构建/发布。
- `pnpm dev:web`现有假ADO模式扩展任务fixture；开发任务只运行假ADO与由夹具创建的临时git目录，不能导入用户真实路径执行；非dev/非memory接受假开关必须启动失败。fixture seed/清理归启动器所有，只回收其pid与临时目录。
- 派工明确禁止：按进程名kill、裸git stash、删除/放宽既有测试、仓库内留报告文件、改旧应用代码/配置/凭据；同类失败两次或需变更本合同接口/状态/写范围/权限/限额即停下交主控。
- 每个修复先写会失败的回归，主控亲自复现修前失败（可临时反向应用限定补丁，禁止stash），恢复后再验收。独立测试必须新增需求/故障用例，不能只复跑施工者测试。
- 后端优先标准库sqlite3/asyncio/subprocess/fcntl，不为本切片新装执行框架；确需依赖由主控预置锁文件后再派工。仓库pre-commit自动递增app_version.py是既有行为，单列记录。

## S3-A：运行内核、SQLite、任务配置与 Git

- 依赖：合同已确认、待决写入、依赖预置SHA。
- write_scope：`next/backend/**`、`next/contracts/**`。API/模型由本包先落定；主控统一生成前端schema。测试子agent仅 `next/backend/tests/independent/s3a/`。
- 结果：任务读取/条件CRUD/预检、RunStore/RunService七态、幂等/预约/恢复、持久增量事件、git适配器与生命周期；远端adapter以可注入假实现验收，**不开放不完整真实执行链**（在S3-B接入之前start返回unsupported_task）。不新建临时第二套前端手写类型。
- 自动验收：后端`.venv/bin/python -m pytest -q`、`.venv/bin/ruff check .`、`.venv/bin/python -m toolbox_backend.contracts --check` exit0；沙箱不能bind的用例报告not_run，主控沙箱外跑完整集合。覆盖：
  1. CRUD/revision/未知字段/ACL引用/活动编辑竞态；幂等双击/同key异body/任务唯一/预约竞争；坏DB/高版本/事务中断/权限/重启不重放写。
  2. 临时bare+两个clone的fetch/ff/merge/push顺序、远端ref/构建分支commit、错误upstream、脏目录、冲突abort、部分push、非ff拒绝、别名/common-dir互斥、不改原应用路径。
  3. queued/git执行中/写边界cancel与二次cancel、超时、假进程后代TERM/KILL/wait、强杀后锁仍持到子进程退出、关闭stderr/stdout与许可归还；不按旧pid误杀。
  4. DB事务+事件原子性、跨重启run_seq、回放/实时交界、断线补齐、重复/乱序、队列4408、日志预算/跨块脱敏/无换行洪水。
- 回退：代码恢复本包write_scope至输入SHA；不删除已存在DB/config，不降级未知DB版本。含真实写的运行数据不能当源码一起回滚。

## S3-B：ADO 构建、发布、只发布/回滚与只读对账

- 依赖：S3-A集成；按已决1/4/5/6裁定执行分支。与S3-C是否并行由主控在契约已冻结后决定。
- write_scope：`next/backend/**`、`next/contracts/**`；测试子agent仅`next/backend/tests/independent/s3b/`。修改公共ADO底座须保持S1/S2既有测试不弱化。
- 结果：接入完整执行链后才开放start；所有本合同写边界落盘、身份/归属核实、停止、超时/重启对账；只支持确认的能力，未支持分支给明确阻断，不静默忽略配置。
- 验收命令同S3-A；MockTransport逐项断言上表端点/api-version/body/查询。独立测试覆盖全链与每个失败残留，重点：
  1. definition/branch/commit/项目任一不同或缺失均不复用；详情失败不接管；queue不符不复用；新触发固定commit；自动构建owned=false且取消零写；取消fallback先核关联，禁止猜Build id。
  2. 每次POST/PATCH送达后故意丢响应、DB回执提交失败、重启、重复start/cancel/reconcile；断言无重复构建/Release/部署；unknown保留预约；同名target/部分stage/旧succeeded与新attempt分离。
  3. Release版本GET协商与写请求不重试；多artifact/绑定不符阻断；未选环境不自动部署的请求合同；所选环境全覆盖；禁用target在三操作中均不执行。
  4. 只发布冻结build；回滚冻结历史Release、offset越界/不足、历史已变；不git写/不新触发build；全部终态/审批中/取消失败/网络失败及credential来源变化。
  5. 共享出站总并发6（S1/S2/S3混合请求）、小块滴流限额截止、3xx与原始路径越界零跨界请求；任何公开/落盘输出不含假密钥。
- 回退同S3-A，停止新start；已创建远端资源只读核实，不因回退重发/删除。

## S3-C：任务页换真实接口（Gemini）

- **暂停（用户 2026-10-23）→ 改为依赖 R1**：方向 E 视觉不再沿用。S3-C 在 R1 集成后派工，视觉与结构以 `design/b-native/B-Tasks.dc.html` 和 R1 组件为准（下文「按设计E既有组件」作废）；R1 留下的任务页占位由 S3-C 替换。S3-A/S3-B 后端不受影响。
- 依赖：S3-B正式契约与fake fixture集成；主控生成`schema.d.ts`后派。若并行只可按已冻结接口，不能靠mock假定新字段。
- write_scope：`next/desktop/src/features/tasks/**`、`next/desktop/src/api/events.ts`与`src/app/backend-runtime.ts`（仅新增run消息/订阅回调和认证后send支持，保持旧调用兼容）、`next/desktop/src/components/SidebarNav.vue`（仅任务角标改真实状态）、`next/desktop/tests/**`（新增文件）、`next/desktop/scripts/dev-web.mjs`（仅任务假fixture生命周期）、`next/desktop/README.md`；schema由主控生成。共享路径变化先交主控，不批量改其他feature。
- 结果：任务列表/搜索/启用筛选、详情与执行计划确认、条件CRUD与排序、运行历史/阶段/停止/unknown说明、日志分页与增量补齐；按 B-Tasks 设计稿与 R1 组件（StatusPill、Sheet、Banner、ListRow 等），步骤列表/日志面板在 S3-C 内新增。选择态可localStorage仅存task_id；配置草稿/运行日志不持久到浏览器，token永不进URL/DOM/storage。
- 每次start确认展示任务、仓库/分支、目标definition/stage、精确制品（只发布/回滚）、不可撤回的已执行副作用，以及“请确认旧应用没有在跑同一任务”必选框；后端要求ack。queued/running/cancelling/unknown由服务驱动，不凭按钮点击乐观写成功；unknown可只读核实与打开校验链接。
- 切换任务/刷新/断线时取消在途查询且防旧响应覆盖；先订阅再补齐，按连续run_seq去重；选中运行改变先退订旧run；页面卸载清理监听/abort/订阅，不取消后端任务。无任务/配置无效/无凭据/只读库/冲突/繁忙/远端可能继续均有可操作中文提示。
- 自动验收：`pnpm install --frozen-lockfile`、`pnpm typecheck`、`pnpm lint`、`pnpm test`、`pnpm build`、`pnpm guard:dist`、`pnpm contracts:check`全部exit0；独立测试位于`tests/independent/s3c-*`。覆盖CRUD/冲突与ACL阻断、preflight失效、二次确认/取消、双击幂等、后台继续、unknown/取消真实语义、重连缺口/乱序/重复/后端重启、并发run日志隔离、键盘焦点、无假执行数据/PAT。
- 删除任务feature中已替换mock；侧栏未迁移的其他feature mock不扩范围。主控假环境联调留截图：任务、编辑、计划确认、运行日志、停止/unknown、历史。真实Tauri/ADO验收另列。
- 回退：限定上述路径至输入SHA；不能把假页面状态当真实run结果。

### S3-C 主控裁决：既有 mock 测试迁移（2026-10-23）

- Gemini只读侦查及主控原文抽查确认，四个既有文件固化了S0.5 mock：`tests/unit/pages.test.ts`、`tests/independent/e-alert.test.ts`、`tests/unit/s1c.test.ts`、`tests/independent/settings-independent.test.ts`。S3-C测试write_scope另允许修改这四文件中的**任务相关用例**，其他feature用例不改；无需保留产品里的假任务来迁就测试。
- 原断言的安全/键盘/单选/阻止冒泡/告警非模态可交互/ARIA面板关联语义全部保留。原固定任务可迁到按正式DTO构造的假API夹具；新建需实际打开表单、提交、等待服务响应后再断言列表变化，不能继续断言本地push假数据。
- 全局告警不能把真实run凭空改为failed；失败样式由假服务提供真实形状的failed状态/事件驱动，另外保留system.hello/system.alert驱动横幅与导航告警的验证。虚构的周KPI断言替换为真实运行历史断言（不得在产品中保留虚构统计）。每处既有断言的改动须在交付逐条说明替代覆盖，禁止删用例、放宽安全断言或用skip换通过。
- 新增独立S3-C用例仍为硬要求，上述迁移不冒充独立测试。正式API输出类型由S3-B冻结后生成，不在这次侦查中手写模型。

## S3 集成验收（主控）

- 后端完整pytest/ruff/contracts；前端frozen install/typecheck/lint/test/build/guard:dist/contracts:check；Rust `cargo fmt --check`、`cargo clippy --offline -- -D warnings`、`cargo test --offline`；旧应用守卫测试（在重写目录隔离运行，禁止引用真实配置）不回退；`git diff --check`与限定改动路径检查。当前572/755是S2历史基线，不冒充S3结果。
- 主控亲自核对每个副作用间隙的残留与检查点、未知结果恢复、取消归属、子进程/锁/连接关闭，并应用四技能完成复核；实现后补resource-lifecycle-audit，声明production-ready前补production-readiness-review。
- 运行假fixture端到端：任务编辑→同步→构建→发布→历史；只发布/回滚（若纳入）；重启后unknown→只读对账；断网重连日志补齐；数据库写失败/远端请求结果丢失。全用临时bare+MockTransport，扫描假PAT/Basic/Bearer不外泄。
- 对照本节旧事实与能力文档，在PROGRESS列迁移/改进/有意推迟清单；每包分别登记实际模型/档位/会话/命令/退出码/测试数/未测/清理；异步Claude审计登记为pending/unavailable/returned，不能冒充通过。

### 真实验收清单（仅用户另行授权后执行；本合同提交不执行）

1. 用户选择专用测试仓库/分支、ADO测试构建与测试环境，确认旧应用同任务空闲；核对SSH agent/host key、PAT最小权限与执行计划，不使用生产目标做首次验收。
2. 真实SSH fetch/merge/push、构建精确commit与queue覆盖、分支自动触发构建复用；核实只取消本任务创建的构建，复用实例停止不会取消。
3. 自建服务器Build/Pipeline/Release版本、Pipeline↔Build关联、单artifact绑定、manualEnvironments控制与审批/门禁、新部署attempt识别；不支持时检查阻断说明。
4. 只发布具体制品、回滚具体历史Release（若纳入）；部分target失败时已部署内容的提示，不自动补偿。
5. 用户可控地重启后端，检查unknown/只读重新核实/无重复写；真实Tauri重连与日志/历史、关窗后台执行、明确退出的本地进程回收。
6. 真实Keychain授权/拒绝、无凭据/权限不足与来源变更；真实环境未测逐项记账，不阻塞已通过离线验收的后续工作。

## S3 主控裁决与用户确认的选项

技术已定：SQLite位置/schema与事务意图、七态/只读恢复、不自动重放写、D06精确身份/创建归属、D07仓库锁、S2 HTTP底座复用、假环境测试和模型分工均按上文。下表保留当时选项以便追溯；**用户已全部选择推荐，备选均不实施**。

| 编号 | 需要拍板 | 推荐 | 备选与影响 |
| --- | --- | --- | --- |
| 1 | 首版是否有只发布和回滚 | **都纳入S3**，保留旧三操作，统一复用运行内核与安全边界 | 首版仅同步→构建→发布；只发布/回滚登记S3后续包，相关端点/按钮不开放 |
| 2 | 任务编辑范围 | **提供完整增删改/排序**，未知字段保留；ACL引用任务禁止删除，禁用可用 | 只读+执行；需用户继续在旧端编辑并人工迁移，不增加自动二次导入 |
| 3 | 新旧同任务并行保护 | **每次执行计划确认必选“旧应用没有在跑同一任务”**，新端内部锁与预约照做，不做跨应用锁 | 跨应用强锁会要求改旧应用，与本轮旧端只读冲突；若需要应另立包 |
| 4 | 无本地路径的远程PR合并与git认证范围 | **S3暂缓远程PR写，只支持本地SSH agent同步；无git规则时可只读查commit后构建**；HTTPS/SSH别名代理暂不自动适配，明确阻断 | 若这些是日常必需，扩S3-B前先补PR创建/完成的意图与恢复合同，或补独立HTTPS凭据通道；涉及Code写权限/认证边界须明确确认 |
| 5 | Classic partiallySucceeded能否进入发布 | **首版仅完全成功放行**，避免带失败制品发布；历史配置不增加默认放行开关 | 沿用旧Classic允许部分成功；需在确认页显著标出，新增明确allow_partial_success字段与回归，不影响YAML规则 |
| 6 | Release定义自动启动未选环境 | **只允许所选环境部署**：创建时全部转手动再显式推进所选项；服务器不能保证时阻断 | 保留旧“定义可能自动发其他环境”；确认页必须列出所有可能自动部署环境，扩大实际执行范围，不能声称只发所选stage |

## S3 已决

- 用户2026-10-23原答复：**“均按你推荐的来”**，确认六项：1 主路径/只发布/回滚均纳入；2 完整任务增删改/排序，ACL引用禁止删除；3 每次确认旧应用空闲，不做跨应用锁；4 暂缓远程PR写、本地同步仅标准SSH agent，HTTPS/别名代理暂阻断；5 部分成功不得发布；6 仅部署所选环境，无法保证则阻断。
- 本确认解除派工门禁；不授权真实远端push/构建/发布、读取真实配置/凭据或删除worktree，真实验收按专门清单另行授权。合同中“若纳入/待决”均由以上已决收敛，施工者不得选择备选路径。
- 依赖预置：后端SQLite/git/锁使用Python标准库，不新增运行时依赖；主控在施工worktree用现有uv.lock离线同步工具环境。实际运行时核验和会话证据记PROGRESS。

# R1：方向 B「macOS 原生」换皮（S3-C 前置）

依据：[FRONTEND_STACK.md](FRONTEND_STACK.md) §9（用户 2026-10-23 选定 B，C 作深色参考；§7/§8 作废）；设计源码 `design/b-native/`（画板：工单浅色/深色、任务、设置、AI 会话、组件清单）。设计稿只作视觉与结构参考，**不得直接拷贝**其 HTML/脚本。用户 2026-10-23 下达。

目标：只换视觉与布局骨架，**不改任何业务行为**（数据流、接口调用、校验、编辑会话、安全边界、键盘可达性都保持）。换完后工单页、设置页在 1440×900 下与设计稿一致，空/读取中/出错状态都有设计。

## R1 通用合同

- 输入版本：`rewrite/next` 上提交本合同的 commit（派工时写明 SHA）。
- 授权：可在 `next/desktop` 内用 pnpm 移除依赖、更新 lockfile（用户级 pnpm store 可用）；本包**不新增 npm 依赖**（需要时停下交主控）。不装全局工具。主控可在 `rewrite/next` 本地提交，不 push。
- 施工位置：`git worktree add --detach .local/worktrees/r1 <SHA>`；施工者不 commit，主控以限定路径 patch 集成。
- write_scope：`next/desktop/src/**`（不含 `src/api/**`、`src/stores/backend.ts`、`src/app/backend-runtime.ts`）、`next/desktop/tests/**`、`next/desktop/package.json` 与 `pnpm-lock.yaml`（仅移除字体依赖）、`next/desktop/index.html`、`next/desktop/README.md`、`next/THIRD_PARTY.md`。后端、`next/contracts/**`、`src-tauri/**`、`scripts/**` 不动。
- 保持不变：S0 连接与安全语义（token 只在内存、Bearer、WS 首帧 auth、退避重连、心跳判死、告警只由 `system.alert`/`system.hello` 驱动）；S1 设置的编辑会话/保存粒度/校验/确认流程；S2 工单的查询、分页、选择持久化（`toolbox.work-items.selection`）、HTML 清洗、媒体代理与过期刷新、外链拦截；AI 页审批 Y/A/N 行为。
- 测试改动规则：方向 E 专属的**视觉断言**（令牌数值、切角/斜切、印章、能量条、阶段条、底部状态栏、编号导航、任务 mock 行）可以按 B 等价改写或删除；**行为/安全/连接/可访问性/设置/工单断言不得删除或放宽**，只能改定位方式（选择器、文案）。每个被改的既有测试文件在交付报告中列出改动理由。
- 禁止：改 `next/` 以外文件；读真实密钥/用户配置；连真实 ADO/TG；源码与构建产物出现 `Rhine`/`RHINE`/`Arknights`/`fonts.googleapis.com`；为通过检查删除或放宽上面列出的行为测试；画假窗口按钮。
- 升级条件：需要改连接/安全接口、后端契约、写入范围或新增依赖；某个既有行为测试无法在不放宽的前提下迁移；同类失败两次 → 停下交主控。
- 分工：单包、单施工者（令牌、骨架、组件、页面互相耦合）。施工 Claude Code 原生子 agent，requested sonnet / medium；施工者委派测试子 agent（requested haiku / medium，independent=true）新增独立用例于 `tests/independent/r1-*.test.ts`。交叉审计异步，跨厂商：codex exec requested gpt-6.1-sol / high，只读。actual 无提供方回执记 unknown。

## R1 已定决定（施工者不得自行更改）

**令牌**（`src/design/tokens.css` 重写；`ui.css`、`app.css` 随之改写）

- 浅色：窗口 `#FFFFFF`、侧栏 `#EEEDF1`、检查器/分组底 `#F7F7F9`、设置内容底 `#F5F5F7`、分隔线 `#E5E5EA`、正文 `#1D1D1F`、次要文字 `#6E6E73`、禁用文字 `#A1A1A6`、控件底 `#EDEDF0`、悬停 `#F2F2F5`、选中未聚焦 `#E3E2E8`、强调 `#0A63D6`（其上白字）、强调文字 `#0A55B8`、链接 `#0058D0`。
- 深色（`@media (prefers-color-scheme: dark)`，跟随系统，本包不做手动切换）：窗口 `#121315`、侧栏 `#0E0F11`、列表 `#141517`、检查器 `#17181B`、分隔线 `#23252A`、控件底 `#1F2125`、选中控件 `#3A3D44`、正文 `#ECEDEF`、次要文字 `#8B8E98`、禁用文字 `#6F727C`、强调 `#C6F432`（其上文字 `#14161A`，绿色不作文字色）、链接 `#D4F56A`、选中行 `#262A1C`。
- 运行状态八色（底 / 文字 / 圆点，浅色）：排队 `#F0F0F3/#3A3A3F/#8E8E93`、运行中 `#E6F0FD/#0A4FAD/#0A63D6`、停止中 `#FFF0E0/#8A3F00/#E07B00`、成功 `#E5F5EA/#16692F/#1F9D45`、失败 `#FDECEA/#A1211A/#D93025`、已取消 `#F0F0F3/#4A4A4F/#8E8E93`、需核实 `#FFF3DC/#7A4100/#D98A00`、已停用 `#F0F0F3/#6E6E73/#C7C7CC`；深色版由施工者按同一色相给出，并满足对比度测试。
- 提示横幅：信息 `#F2F6FD`、警告 `#FFF6E5`、错误 `#FDECEA`，各配深色文字与 1px 内描边（取值见组件清单画板）。
- 字体：系统字体 `-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', 'Helvetica Neue', sans-serif`；等宽 `'SF Mono', ui-monospace, Menlo, monospace`，只用于编号、提交、路径、命令、日志。**移除** `@fontsource/oxanium`、`@fontsource/inter`、`@fontsource/jetbrains-mono` 依赖及 `main.ts` 中的导入。
- 字号：详情标题 22/700、页面标题 15/700、长文正文 14（行高 1.65）、界面正文 13、次要 12、侧栏分组标题 11/600。
- 尺寸：圆角 控件 6 · 行 7 · 分组 10 · 窗口 12；间距 4/8/12/16/20/28；控件高 28；所有顶栏 52 高；侧栏 232、列表栏 320–380、检查器 280。
- 删除：切角/斜切（`clip-path`、`--cut-*`、`--skew`）、玻璃（`backdrop-filter`）、`--acc`/`--warn` 旧令牌及一切 Oxanium 用法。

**应用骨架**（`src/app/App.vue` 重写）

- 网格：通高侧栏 ｜ 页面区（每页自己的列表栏/详情/可开关检查器）。**去掉底部状态栏**。
- 侧栏顶部 52px 为拖拽区（`data-tauri-drag-region`；真窗口按钮由 Tauri Overlay 标题栏提供，不画假的）；各页顶栏空白处同样可拖拽，控件除外。
- 侧栏分组：「工作」任务/工单/AI 会话；「基础设施」MCP/服务/VPN（禁用，无切片号角标，`title` 说明“尚未提供”）；底部 设置 + 连接状态行。不做「已保存查询」区（无真实数据不放 mock）。侧栏不显示计数角标（S3-C 再接任务真实状态）。
- 连接状态行（侧栏底部，按钮）：只显示后端真实状态（connecting/online/reconnecting/offline）。点开为弹出层：后端状态、pid、心跳延迟，以及 S0 的告警演示开关（仍只调用 `POST /api/system/alert`）。VPN/TG/MCP 在各自切片前不显示。
- 检查器：页面顶栏右侧的切换按钮（`aria-pressed`），开合状态可存 localStorage `toolbox.ui.inspector`（仅布尔值）。

**组件**（`src/components/`；旧组件删除或改名，不留双份）

| 旧（E） | 新（B） |
| --- | --- |
| GlassPanel | Pane（纯色面，无玻璃/切角） |
| AppTabs | SegmentedControl（Reka Tabs，方向键行为不变；横向用于看板列与详情页签，页签可带计数） |
| AppButton primary/accent/ghost | Button：primary（强调底）/ default / destructive（红字）/ plain |
| IconButton | ToolbarButton（无底色，按下态，必须有 aria-label） |
| TextInput / SearchBox | TextField / SearchField（⌘K/Ctrl+K 聚焦、Esc 失焦保持） |
| BlockTag | Tag（中性小标签，无编号块） |
| StatusDot | StatusDot（改色） |
| AlertBanner | Banner（info/warn/error，贴在所属区域内，不遮挡） |
| ApprovalBar | ApprovalBar（改样式，Y/A/N 与输入框聚焦时不触发保持） |
| InspectorPanel | Inspector |
| SidebarNav | Sidebar（分组） |
| StatusBar | 删除 → ConnectionStatus（侧栏底部 + 弹出层） |
| StampBadge、EnergyBar、StageBar | 删除 |
| — | 新增 StatusPill（八态）、ListRow（两行；悬停、选中聚焦=强调底白字、选中未聚焦=灰底，按列表 `:focus-within` 区分）、EmptyState（图标 + 标题 + 一句说明 + 动作）、Skeleton（骨架行）、Sheet（Reka Dialog，从顶栏下落的确认单，焦点陷阱，Esc 关闭） |

`components/ui/switch` 改样式为系统风格开关。

**页面**

- 工单 `features/work-items`（对照 `B-Native` / `B-Dark`）：列表栏（标题 + “项目 · 看板列 N 项”、刷新、搜索、看板列分段控件、两行条目：标题/日期，`#编号 · 类型 · 指派 · P`，类型圆点）；现有分页（每页条数 + 上下页 + 共 N 条）保留，放在列表栏底部，**不改成滚动加载**。详情顶栏：项目、指派人弹出菜单 + 在浏览器打开 + 检查器开关。详情：类型/编号/父项一行 → 22px 标题 → “指派 · 创建 · 更新 · rN”一行 → 页签（描述/评论/子项/历史/附件，带计数）→ 正文 14px。检查器：状态、优先级、指派、看板列、严重度、区域、迭代、标签，下方 AI 分析（禁用，“即将推出”）。未配置项目、读取中（骨架）、出错（Banner/空状态 + 重试）、截断/跳过提示、图片过期提示全部按新组件。画布上的「筛选」「复制链接」**不做**。
- 设置 `features/settings`（对照 `B-Settings`）：二级分区改为左侧竖向列表（Reka Tabs `orientation="vertical"`，键盘行为等价），彩色小图标 + 计数；内容区 `#F5F5F7` 底、分组白卡片、标签在左控件在右。存储只读、加载失败、提示（含任务/警告列表）改为 Banner；原右侧“说明”检查器取消，说明文字并入各分组标题下的说明。保存/取消/删除确认等按钮沿用现有编辑会话与确认语义，只改位置与样式；HTTP 明文与“PAT 将发往新地址”的警告保留且用 warn Banner。
- AI 会话 `features/ai`（对照 `B-AI`）：仍为 mock；会话列表（Claude/Codex/Antigravity 徽标、待审批/运行中/完成）、对话气泡与工具调用条、内联审批条、输入框、检查器（上下文用量、目录、分支、关联工单、已允许命令）。mock 只改数据形态以配合新布局，仍只在 `features/ai/mock/`。
- 任务 `features/tasks`：删除 S0.5 mock 任务台与 `features/tasks/mock/`，改为 EmptyState 占位（“任务执行正在接入”，说明由 S3 提供，不放假任务/假 KPI）。真实页面由 S3-C 按 `B-Tasks` 实现。
- `/` 仍重定向 `/tasks`。

**告警**：状态仍只由 store 的 `alert` 驱动。告警时页面区顶部出现 warn Banner（显示 `reason`，无则默认文案），侧栏连接状态行变橙；无遮罩、不拦截操作。

**动效与可访问性**：只保留状态点运行中的脉冲与 Sheet 进出；`prefers-reduced-motion: reduce` 下关闭。可点击目标 ≥28px 且行内按钮命中区 ≥28×28；图标按钮均有 aria-label；Tab 可遍历侧栏、顶栏、列表行（Enter 选中）、页签、审批条；焦点环用系统蓝 2px 外描边（深色用强调绿）。

## R1 验收

1. 在 `next/desktop`：`pnpm install --frozen-lockfile`（lockfile 随字体依赖移除更新）、`pnpm typecheck`、`pnpm lint`、`pnpm test`、`pnpm build`、`pnpm guard:dist`、`pnpm contracts:check` 全部 exit 0。
2. 令牌测试：解析 `tokens.css`，断言浅/深两套关键令牌值；对比度：正文/次要文字在窗口、侧栏、检查器、控件底上 ≥4.5:1（两套）；白字在浅色强调上、`#14161A` 在深色强调上 ≥4.5:1；八种状态文字在各自底色上 ≥4.5:1；横幅文字在横幅底上 ≥4.5:1。
3. 守卫测试：`src/**` 与 dist 不含 `clip-path`、`backdrop-filter`、`Oxanium`、`@fontsource`；既有禁词测试保留。
4. 新组件单测：SegmentedControl 方向键与计数、ListRow 选中聚焦/未聚焦、Sheet 焦点陷阱与 Esc、EmptyState 动作、StatusPill 八态文案、ConnectionStatus 四种连接态与告警开关只发 `POST /api/system/alert`、Inspector 开关与 localStorage 只存布尔。
5. 页面测试：工单四态（正常/未配置/读取中/出错）、设置三态（正常/HTTP 警告/只读）、AI 审批 Y/A/N、任务占位不含 mock 任务文本；告警经假 `system.alert` 进入 store 后出现 Banner 且页面按钮可点。
6. 既有 S0/S1/S2 行为、安全、连接、可访问性测试全部通过；改写过的测试文件逐一列出理由。
7. `next/desktop/README.md` 更新（目录、组件清单、令牌、深色模式、任务页占位说明）；`next/THIRD_PARTY.md` 去掉方向 E 与三个字体条目，写明改用系统字体、无第三方视觉来源。

- 未测（允许，主控集成后处理）：Tauri 内渲染、深色模式真机切换、截图对照。
- 回退：从输入 SHA 恢复 `next/desktop`（不含 src-tauri、scripts）与 `next/THIRD_PARTY.md`。

## R1 集成验收（主控）

- 集成版本重跑验收第 1 条全部命令；`git diff --check`；写入范围以外无改动。
- `pnpm dev:web` 下 1440×900 截图对照 `design/b-native/`：工单四态（浅色）+ 正常态（深色，浏览器 `prefers-color-scheme: dark` 模拟）、设置三态、AI 两态、任务占位、告警态；差异逐条写进 PROGRESS，明显偏差退回施工者。
- 交叉审计异步派发（codex gpt-6.1-sol / high，只读），不阻塞 S3-C 派工准备；S3-C 在 R1 集成提交后以其 SHA 为输入。

# S4：Telegram（用户已确认，2026-10-23）

状态：**用户2026-10-23回复“S4 的八项待决均按你推荐的来。”，八项全部采用推荐方案，派工门禁解除**（见「S4 已决」）。实际包状态与证据以 PROGRESS 为准。
输入调查基线：新版 `rewrite/next @ e3e4314`，旧版 `main @ 885d186`（旧目录有用户未提交改动，均不在 Telegram 相关文件内；只读）。本轮未读真实配置/凭据/offset 状态文件、未连接真实 Telegram/ADO。
依据：ARCHITECTURE §4/§5、MIGRATION_PLAN S4/§4、D02（WP-12 已在旧端热修）/D12；S1 已导入的 `imported.telegram`、S2 工单读取与媒体规则、S3 运行内核（RunService/TasksService、`task_referenced`）。
本合同覆盖：主机器人的任务指令（构建发布/只发布/回滚/停止/状态）、ACL 编辑与执行、任务结果通知、`/wi` 工单只读浏览、统一脱敏、更新去重与长轮询生命周期、Bot Token 与所有权切换。**不含**：三个 AI 专属机器人与 `/cc`、`cc:*`、工单「MCP 分析/复制提示词」（S5）；服务面板 `svc:*`（S7）、`/vpn`（S8）、MCP 菜单 `mcp:*`（S6）；webhook 模式；多 Bot 主机器人。

## S4 旧应用事实核实（主控亲自只读核对）

以下位置相对旧目录 `/Users/wesker/my-own-script`；是静态代码事实，**不代表真实 Telegram 已验证**。

### 轮询线程、Token 与所有权

- `app_main.py:174–233`：同一个 `TelegramController` 类起 4 条守护线程：主机器人（`mode="main"`，`on_run/on_deploy_only/on_rollback/on_stop_menu/on_stop_one/on_status` 回调到任务页，`wi_bridge`，`headless_bridge=None`）与 `ai`/`codex_ai`/`antigravity_ai`（`mode="ai"`，各自 `token_fn`）。退出时只 shutdown AI 桥，**从不调用 `tg.stop()`**，线程随进程结束。
- Token：`secrets.py:20–29` 主机器人 Keychain service `my-own-script`（`store.py:10` APP_ID）/ account `telegram_bot_token`；`:34–50` AI 机器人 `ai_bot_token:<ai_id>`（S5）。S1 导入只迁移 ADO PAT，**新端目前没有任何 Bot Token**（`next/backend` 无 bot token 引用）。
- `tg_control.py:1231–1243`：每轮循环读 `ui_settings.telegram_control_enabled`，**4 条线程（含 AI 机器人）共用这一个开关**；Token 取不到时 sleep 2 秒空转。旧 UI（`ui/telegram_card.py:112–117`）输入空 Token 被忽略，**无法在旧 UI 清除 Token**。
- `:1245–1248` 首次轮询前 `deleteWebhook(drop_pending_updates=false)`；`:1554–1557` 任何含 "409"/"Conflict" 的错误都再 `deleteWebhook` 并 sleep 5 秒后继续轮询——两个进程轮询同一 Bot 时会互相抢占、无限循环，**旧端不会自己让出**。
- `:318–332` getUpdates：`timeout=20`、`allowed_updates=[message, callback_query]`、无 `limit`，httpx 默认 `trust_env=True`（读取环境/macOS 系统代理），不跟随重定向。

### 更新去重与失败（D12）

- `:203–218` offset 存旧配置目录 `tg_offset{suffix}.json`（`next_offset`），写失败静默。
- `:1256–1539` 整批 updates 逐条同步处理，**全部处理完才保存 offset**；任一处理器抛异常（含 `send_telegram_message` 回复失败抛出的 RuntimeError）即跳出整批、offset 不前进，下一轮 Telegram 重投整批——已执行的 `/<任务>`、`rb_yes` 等会**再次触发**（只有“同任务正在运行”能挡住）。无 update_id 去重表、无请求幂等键。
- 应用停机期间积压（Telegram 最多保留 24 小时）在下次启动后**照常执行**，不看消息时间。
- 处理器在轮询线程内同步执行（含 ADO 查询、相册上传），慢操作阻塞后续 update。

### ACL 与任务引用

- 配置（`models.py:156–165`）：`telegram_chat_id`（owner）、`telegram_whitelist`、`telegram_control_enabled`、`telegram_notify_include_details`、`telegram_acl_groups: list[dict]`、`telegram_acl_members: list[dict]`。组字段（`ui/acl_dialogs.py:100–121`）：`id=acl_group:<uuid4>`、`name`（唯一）、`can_run`、`can_stop`、`can_status`（默认 True）、`can_rollback`、`task_ids`；`can_run` 时至少勾一个任务。成员（`ui/telegram_acl_mixin.py:126–197`）：`group_id`、`chat_id` 或 `username`（`@xxx`，大小写不敏感，全局唯一）、`label`，**无 id**；删组同时删其成员。
- `tg_control.py:249–282` `_resolve_acl`：**owner 为空时，第一个私聊（chat_id 不以 `-` 开头）机器人的人自动写成 owner 并保存**；`chat_id == owner` → owner；旧白名单（chat_id 或 `@username`）→ 只读组（仅 status）；成员先按 chat_id、再按 `@username` 匹配（username 来自 `message.from`/`callback_query.from`，chat 取 `message.chat`，群里按群 chat_id 匹配即全群共享权限）；其余 `none` 静默忽略。
- `:284–300` `_can`：owner 全通过；status←`can_status`；stop←`can_stop`；run（含只发布 `runmode:deploy`，`:1416–1427`）←`can_run`+task_ids；rollback←`can_rollback`+task_ids。服务/VPN/MCP/工单仅 owner（`tg_work_items_bridge.py:124–125`）。
- `store.py:50–76` 旧 flow id → 任务 UUID 映射；S1 导入已做同样映射（`next/backend/.../adapters/legacy_config.py:192–205`），结果原样存在 `config.imported.telegram`（键去掉 `telegram_` 前缀，`domain/settings.py:201–207` 只校验为 JSON 对象）。新端 `services/tasks.py:223–237` 删除被 `acl_groups[].task_ids` 引用的任务返回 409 `task_referenced`（含组名）。

### 指令与回调

- `tg_control.py:507–852` `_handle`：`/help`、`/start`（inline 顶部菜单 `help_menu:{tasks,sys,svc,dev,wi,mcp,back}`）、`/status`、`/stop`、`/rollback`（多步向导，内存 `_rollback_wizard[chat_id]`，无 TTL）、`/cancelrollback`、`/<tg_command>` 与 `/run <tg_command>`（**一键直接执行，`tasks_tab.py:363` `skip_confirm=True`**）、`/wi [id]`、`/vpn`、`/cc`（主机器人未传 headless 桥，不出现）。
- 回调（`:1261–1505`）：`help_run:<task_id>` → `runmode:build|deploy:<task_id>`；`rb_task:<task_id>` → `rb_off:<n>` → `rb_yes`；`stp:<task_id>`；`wi_*`；`svc:*`；`mcp:*`。**callback_data 直接携带 task_id**，由处理器重新查 ACL；回滚确认 `rb_yes` 只依赖内存向导状态，确认时不再查 ACL。每条回调先 `answerCallbackQuery`；控制面板回复就地 `editMessageText`（`:334–398`）。
- 回滚 offset（`:109–201`）：对每个 target 列最近 6 个 Release（6.0 失败 catch-all 再 7.0），按下标 offset 1..5；S3 已改为预检冻结具体 Release。
- 停止（`tasks_tab.py:412–464`）：非 owner 只能停自己 chat_id 触发的运行（`by_chat_id` 存内存 `_running_tasks`），重启即丢失归属；`status_text`（`:472`）对所有有 status 权限者列出**全部**运行中任务名。

### 通知

- `tasks_tab.py:1296–1372`（主路径；只发布 `:941–1010`、回滚 `:653–720` 同构）：TG 触发只发给触发者 chat，UI 触发发 owner；`telegram_notify_include_details=False` 只发摘要。发送不检查 `telegram_control_enabled`，只要有 Token 就发；失败静默丢弃，无重试/去重。
- 失败摘要 `_brief_reason`（`:1374–1404`，另两份副本在 `:708`、`:998`）取 git `stderr:` 后第一行（≤120 字）放进**摘要**，即使关闭详情也会发出；详情含 Release URL、definition/release id、等待秒数。`tasks_tab.py` 本身**没有调用脱敏**；`send_telegram_message` 只脱敏错误文本，不脱敏正文。

### 脱敏（WP-12 热修结果）

- `redact.py:13–39`：`/bot<digits>:<token>`（含 `%3A`）→ `/bot***`；`Authorization`/`Proxy-Authorization`/`X-*-Token|Secret|Key` 头值（含引号/JSON/repr 与 `Bearer`/`Basic` 前缀）→ `***`；已知 token 字面值及 `quote(safe='')`、`quote(safe='-_')` 变体，长的先替换。`:42–56` 展开 `__cause__/__context__`（≤6 层），首段保持 `str(exc)` 兼容。
- 应用点：`tg_control.py` 日志/状态/回复错误，`notifier_telegram.py:8–60`（HTTP 错误只给状态码/方法/脱敏路径/响应体，`raise ... from None` 丢弃含 URL 的原异常）。**未覆盖**：`tg_work_items_bridge.py:268,333` 把 ADO 异常原文 `{ex}` 回给 TG 用户；任务通知正文。
- 新端现状：`next/backend/.../logging_setup.py:11–27` 只按已登记密钥字面值（含 JSON 转义与 Basic `:value` 的 base64）替换，**没有 bot URL/认证头正则、没有 URL 编码变体**。

### `/wi`（owner-only）

- `tg_work_items_bridge.py`：每 chat 内存状态（项目、版块下标、列表缓存 600 秒 `:48`）；固定版块 `tg_work_items_inline.py:11` `["新建","待开发","开发中","测试","已关闭"]`；列表分页、`wi_o` 详情（标题/状态/类型/指派/优先级/Area/Tags/链接）、`wi_v` 全文按 3900 字分块 + 图片相册（`fetch_image_blobs(..., trusted_base_url=lib.base_url)`，WP-11 同源规则；`sendMediaGroup` 每组≤10）、`wi_r` 关联项；`wi_m/wi_mr/wi_ma/wi_cp` 起 AI 会话与复制 Markdown 提示词（S5）。

## S4 数据模型与访问边界（主控技术裁决；涉及取舍的见「S4 待决」）

已加载 `/Users/wesker/.ai-prompt/skills/` 下 backend-architecture-review、backend-security-review、data-consistency-review、backend-business-safety。本节为实现前五问、安全计划与一致性合同；实现完成须按这些技能及 resource-lifecycle-audit 复核。

### 架构五问

1. **产生什么数据**：config schema v2 新增类型化 `telegram` 段（开关、owner、通知、ACL 组/成员、旧白名单）；Keychain 新 service `toolbox-next` 的 `telegram_bot_token`；新 SQLite `<data-dir>/telegram.sqlite3`（每 Bot 轮询状态、已收 update、待确认动作、通知发件箱）；`runs.sqlite3` 升到 user_version 2，runs 增加触发来源。不存消息正文（发件箱发送成功后清空正文）、不存 Token、不存 Telegram 原始 JSON。
2. **数据流**：Telegram Bot API ←长轮询/发送→ `adapters/telegram_http.py`（唯一 Bot API 客户端）→ `services/telegram.py`（TelegramService：轮询生命周期唯一所有者）→ `TelegramDispatcher`（ACL 解析 → 指令处理）→ 既有 TasksService/RunService（preflight/start/cancel/list）与 WorkItemsService（S2 只读 + 媒体）→ 回复/通知入发件箱 → 发送器。设置页 → S0 Bearer HTTP → TelegramService（配置写入走 ConfigStore.update 单一写入器）。RunService 状态提交后的事件 → 通知器入箱。
3. **谁能访问**：HTTP/WS 仍为持启动 token 的单一本机主体（S0）。Telegram 侧是新的外部主体：每条 update 先经 ACL 解析为 owner / group(组) / none；none 不执行、不回复（只计数）。权限在**每次执行写操作前重新解析**（不能沿用向导开始时的结论）；callback_data 视为不可信输入（可被客户端伪造），只携带服务端随机动作令牌。HTTP 客户端不能伪造 TG 来源：start 的触发来源只由 TelegramService 内部传入。
4. **并发冲突**：每数据目录一个 TelegramService（沿用后端生存期 flock）；每 Bot 至多一个轮询任务，处理器串行消费（单 chat 内顺序保证），慢操作（preflight、/wi 拉取、相册上传）放入有界工作队列（并发 2、队列 64，满时回复“忙”），不阻塞取下一批 update。跨应用（旧端）无法加锁：以 Telegram 409 作为“另一个轮询者”的唯一证据，新端检测到即停止轮询（不抢占）。配置写冲突沿用 revision 409。同一动作令牌原子消费一次；执行幂等键由令牌派生，双击/重投只得到同一 run。
5. **失败/清理**：先在同一事务里登记 update 并推进 offset，再处理（至多一次处理；崩溃丢失的指令由用户重发，不重放写操作）；执行副作用全部委托 S3（其意图/回执/unknown 规则不变）。发送结果不明不重发。关闭时取消长轮询请求、等待在途处理≤5 秒、关闭 httpx 客户端与 DB；所有退出分支释放同一组资源。

### config schema v2（`telegram` 段）

- 迁移 v1→v2（ConfigStore 既有 migrations 机制，启动期显式迁移、原子写、迁移前快照留 `<data-dir>/migrations/config-v1-<时间戳>.json` 0600）：把 `imported.telegram` 规范化写入顶层 `telegram`，并从 `imported` 移除该键（调用方随同切换：`services/tasks.py` 的引用检查改读类型化 ACL）。迁移不读 Keychain、不联网。
- 字段：

```text
telegram: {
  control: {enabled: false, enabled_at: null, bot_id: null},   # 迁移时一律置 false，不继承旧端开关
  owner: {chat_id: str|null, source: "imported"|"bound"|null, bound_at: null},
  notify: {include_details: bool(旧值，默认 false), ui_runs_to_owner: true},
  legacy_whitelist: [str],                                     # 旧白名单原样保留，只授予 status（待决4）
  acl_groups: [{id, name, can_run, can_stop, can_status, can_rollback, task_ids: [task_id], ...未知字段保留}],
  acl_members: [{id: "acl_member:<uuid4>", group_id, chat_id: str|null, username: str|null,
                 user_id: str|null, label: str, ...未知字段保留}]
}
```

- 校验：chat_id/user_id `^-?\d{1,20}$`；username `^@[A-Za-z0-9_]{5,32}$` 归一化小写比较；组名 1..64、唯一；成员 label≤64；chat_id 与 username 至少一个，二者各自全局唯一；组≤50、成员≤500、每组 task_ids≤200；`can_run`/`can_rollback` 为真时保存需至少一个任务（旧规则）。迁移中的旧条目超限/无效/重复：保留并在 GET 中附 warning，不参与授权（无效成员不匹配任何人），不阻止页面打开。task_ids 引用不存在的任务：warning，不授权。
- 迁移为成员补 `id`；组 id 沿用旧值（非 `acl_group:` 前缀的旧 id 也保留，只作为不透明标识）。

### 凭据（Bot Token）

- 新 account `telegram_bot_token`（service `toolbox-next`），沿用 S1 凭据元数据索引（kind=`telegram_bot`，source=imported|manual），值永不出后端、读取即 `register_secret`。
- 来源两条：`PUT /api/telegram/token`（只写，格式 `^\d{5,16}:[A-Za-z0-9_-]{30,64}$`，失败 422 不回显）；`POST /api/telegram/token/import-legacy`（显式按钮，只读旧 service `my-own-script`/`telegram_bot_token`，写入新 service；旧条目不动，缺失 404 `legacy_missing`）。不在启动或 S1 导入流程里自动读取。
- 轮询启用中禁止更换/删除 Token（409 `telegram_active`），须先停用。Token 对应 bot_id（冒号前数字）与 `control.bot_id` 不同时，按新 Bot 处理：轮询状态按 bot_id 隔离，不复用旧 offset。
- AI 专属机器人 Token（`ai_bot_token:*`）S4 不读、不导入、不显示。

### SQLite `telegram.sqlite3`（与 runs 库同目录/同权限规则：0700/0600、拒绝符号链接、WAL、synchronous=FULL、busy_timeout=5000、参数化、IO 在线程）

| 表 | 字段与约束 |
| --- | --- |
| `tg_bots` | `bot_id TEXT PK`、`username`、`next_offset INTEGER`、`baseline_done INTEGER`（首次启用已跳过积压）、`state`、`updated_at` |
| `tg_updates` | `(bot_id, update_id) PK`、`received_at`、`kind`（message/callback/other）、`chat_id`、`user_id`、`command`（仅指令名/回调类别，不存正文与参数）、`status`（received/handled/ignored/expired/failed）、`reason`、`handled_at`；保留 7 天或最近 10000 条，超出在启动时修剪 |
| `tg_actions` | `token TEXT PK`（16 字节随机 base64url）、`bot_id`、`chat_id`、`user_id`、`kind`（run_confirm/deploy_confirm/rollback_pick/rollback_confirm/stop/wi_*/menu）、`payload_json`（服务端参数：task_id、operation、plan_id、offset、work item id 等）、`created_at`、`expires_at`、`consumed_at`、`result_run_id`；每 Bot 活动≤256、每 chat≤16，超出淘汰最旧未消费项 |
| `tg_outbox` | `id PK`、`bot_id`、`chat_id`、`dedup_key UNIQUE`（如 `run:<run_id>:<status>`、`reply:<update_id>:<n>`）、`kind`（reply/notify/media）、`text`（发送后置空）、`reply_markup_json`、`edit_message_id`、`state`（pending/sending/sent/failed/unknown/dropped）、`attempts`、`next_attempt_at`、`created_at`、`sent_at`、`error_category` |
| `tg_meta` | `PRAGMA user_version=1`；未知高版本/损坏 → Telegram 只读错误态（轮询不启动、HTTP 503 `telegram_store_unavailable`），设置与任务页其余功能不受影响 |

- `runs.sqlite3` user_version 1→2：`ALTER TABLE runs ADD COLUMN origin_json TEXT NOT NULL DEFAULT '{"kind":"ui"}'`，单事务；升级后旧后端（回退）按 S3 规则进入运行库只读错误态，不自动降级。`origin_json={kind:"ui"}` 或 `{kind:"telegram", bot_id, chat_id, user_id, username_snapshot, action_token}`，**与 run 同事务写入**；HTTP start body 不接受 origin。RunService 新增内部入参 `origin`（默认 ui），由 TelegramService 调用；对外 RunView 增加只读 `origin.kind`（不回传 chat_id/user_id 以外的字段；UI 显示“由 Telegram 触发”）。

### 长轮询生命周期与 Bot 所有权（D12）

- **启用**：`POST /api/telegram/control/enable {revision, ack_old_bot_stopped:true}`。后端依次：取 Token → `getMe`（得 bot_id/username，401 → `token_invalid`）→ `getWebhookInfo`（已设 webhook → 409 `webhook_set`，响应只给“已设置”布尔，不回显 URL；用户再次带 `delete_webhook:true` 才调用 `deleteWebhook(drop_pending_updates=false)`）→ 写 `control.enabled=true`/`bot_id` → 启动轮询。`ack_old_bot_stopped` 必填，确认页写明切换步骤（见待决1）。导入或迁移**永不**自动启用。
- **首次基线**：某 bot_id 首次启用（`baseline_done=0`）时，先 `getUpdates(offset=-1, timeout=0)` 取最后一条并确认，之前的积压全部标 `expired` 不执行、不回复；之后正常轮询。
- **轮询**：`getUpdates(offset=next_offset, timeout=25, limit=100, allowed_updates=["message","callback_query"])`，httpx 读超时 35 秒、连接 5 秒；每条 update **先**在单事务内 `INSERT OR IGNORE tg_updates` 并把 `next_offset` 推进到 `update_id+1`，提交后再处理；主键冲突（重投）直接跳过。处理异常只把该条标 `failed`（脱敏类别），**不影响同批其余条目和 offset**。
- **过期指令**：`message.date` 早于当前时间 5 分钟（停机积压/时钟偏差容忍）的指令不执行，回复一次“该指令发送于 HH:MM，已过期，请重新发送”（待决7）。回调过期由动作令牌 TTL 判定。
- **错误与状态**：状态机 `disabled → starting → polling ⇄ backoff → conflict | token_invalid | webhook_set | store_unavailable | stopping`。网络错误/超时/5xx 指数退避 1→2→5→10→30→60 秒（±20% 抖动），只更新状态、不发 `system.alert`（连续失败≥10 次在设置页显示警告）。**409 Conflict → 立即停止轮询进入 `conflict`**，不调用 deleteWebhook、不自动重试；设置页显示“另一个程序（可能是旧应用）正在轮询这个 Bot”，提供“重试接管”（单次 getUpdates 探测）。401/404 → `token_invalid` 停止。429 遵守 `retry_after`。
- **停用/关闭**：`control/disable` 或后端 shutdown：置 stopping、取消在途 getUpdates（不等待长轮询结束）、等待在途处理≤5 秒（超时任务被取消，已提交的 S3 run 不受影响）、**主控修订（2026-10-23，S4-B 交回 S2 出站取消冲突）**：不改 S2 共享 `outbound()`（取消后保留许可直到线程结束是其 6 许可语义）；5 秒后仍卡在 S2 只读出站的处理器标记 detached，此后零发送、零 telegram.sqlite3 写、不触碰已关闭资源，结果静默丢弃，许可在线程结束后按 S2 预算（≤15/30 秒）归还，进程退出可能因此延迟至该预算；RunService 关闭不得排在其后；发件箱停止发送（pending 保留，下次启用继续）、关闭 httpx 客户端与 DB。不调用 `close`/`logOut` Bot API。
- **出站客户端**：只访问固定 `https://api.telegram.org/bot<token>/<method>`（file 下载不需要）；不跟随重定向；单请求响应≤1 MiB（getUpdates）、发送响应≤64 KiB；不共享 ADO 的 6 个出站许可（独立：1 个长轮询 + 发送并发 2 + 媒体上传 1）。代理按待决8。日志/异常永不包含请求 URL：适配器把 httpx 异常映射为固定类别（`network/timeout/http_4xx/http_5xx/conflict/unauthorized/rate_limited/bad_response`）+ Telegram `description`（脱敏、≤200 字）。
- **所有权切换步骤**（由用户执行，主控只给步骤；时机见待决1）：①新端设置页“从旧应用导入 Token”（或手动录入）；②让旧端主机器人停止轮询：旧 UI 不能清空 Token，且关闭“启用 Telegram 触发任务”会**同时停掉旧端三个 AI 机器人**，所以推荐用户手动删除旧 Keychain 条目 `my-own-script`/`telegram_bot_token`（旧主线程随后空转、旧端 UI 触发任务不再发 TG 通知；AI 机器人不受影响）；③新端勾选确认并启用；④若出现 conflict，说明旧端仍在轮询，回到②。**回退**：新端停用 → 在旧 UI 重新填入 Token。

### ACL 解析与执行衔接

- 解析顺序（每条 update，按 `chat.id`、`from.id`、`from.username`）：
  1. 私聊（`chat.type=private`）且 `chat.id == owner.chat_id` → owner。owner 只在私聊生效（群里 owner 也按群的成员规则）。
  2. owner 为空：**不自动绑定**；只响应 `/bind <6位码>`（待决3），其余忽略。
  3. 成员按 `chat_id == chat.id` 匹配（私聊即该用户，群即全群共享该成员权限，与旧端一致）；username 成员按待决4规则匹配。
  4. `legacy_whitelist` 命中 → 只读组（仅 status）。
  5. 其余 → none：不回复、不执行，`tg_updates.status=ignored`。
- 权限映射沿用旧 `_can`：run 与只发布 ← `can_run` + task_ids；rollback ← `can_rollback` + task_ids；stop ← `can_stop`，非 owner 只能停 `origin.kind=telegram` 且 `origin.chat_id == 当前 chat.id` 的运行（重启后仍有效）；status ← `can_status`，**非 owner 只看到其组 task_ids 内的任务与自己触发的运行**（改进：旧端列出全部任务名）；`/wi` 仅 owner。
- 指令流程（全部只调用 S3 服务，不另建执行路径）：
  - `/<tg_command>`、`/run <tg_command>`、菜单任务按钮 → 选择“构建发布 / 仅发布” → `RunService.preflight` → 回复计划摘要（任务、仓库/分支、目标 definition/stage、只发布的精确制品、警告）+「确认执行」「取消」（待决2）。确认时：动作令牌原子消费 → **重新解析 ACL 与权限** → `RunService.start(plan_id, request_id=uuid5(TG_NS, token), ack_old_app_idle=true, origin=telegram)` → 回复“已开始（运行 #短 id）”。plan 过期（5 分钟）→ `plan_expired` 回复“计划已过期”并给“重新预检”按钮，不自动重跑。
  - `/rollback` → 选任务 → 选 offset 1..5 → 对该 offset 预检（显示每个 target 冻结的 Release 名/创建时间/当前结果）→ 确认 → start。旧内存向导改为 `tg_actions`。
  - `/stop` → 列出可停运行 → 点选即 `RunService.cancel`（幂等），回复固定提示“停止不会回滚已部署内容；远端可能继续”，unknown 运行只说明“需要核实”。
  - `/status` → 活动与 unknown 运行（按上面可见范围）；`/help`、`/start`、`/menu` → inline 菜单（任务 / 系统操作 / 工单），服务、VPN、MCP、AI 入口在 S4 **不显示**；直接发 `/vpn` 等回复“该功能尚未迁移到新应用”。
  - `409 task_active/resource_active/busy/no_credential/unsupported_task/run_store_unavailable` 等 S3 错误码映射为固定中文短句，不回传 detail 原文。
- **ACL 引用任务删除（解除 S3 的 409）**：见待决5。推荐 `DELETE /api/tasks/{task_id}?detach_acl=true&revision=`：在**同一次** ConfigStore.update 中删除任务并从所有组 task_ids 移除该 id；不带参数仍 409 `task_referenced`（列组名）。移除后 `can_run`/`can_rollback` 为真但 task_ids 为空的组保留（不偷偷改权限位），GET 附 warning“该组已无可运行任务”。不级联删除成员、不扩大任何授权。

### 通知（发件箱）

- 来源：RunService 已提交的状态转换。入箱规则（dedup_key=`run:<run_id>:<status>`，同一状态只入一次）：`running`（开始，可选，见下）、`succeeded`、`failed`、`cancelled`、`unknown`（“结果需要核实”）、`manual_required`。收件人：`origin.kind=telegram` → 触发 chat；`ui` → owner（`notify.ui_runs_to_owner`，owner 未绑定则不发）。只在 `control.enabled` 时入箱（与旧端“有 Token 就发”不同：停用即全停，便于所有权切换）。
- 正文：摘要固定模板“✅/❌/⏹/⚠️ 操作名 · 任务显示名 · 运行 #短 id”，失败附 S3 `reason_code` 的固定中文解释；**不含 git stderr、日志行、URL、remote、definition id**。`include_details=true` 时追加：分支、目标数与名称、已完成步骤、构建号/Release 名，以及经 S2 同源校验的 ADO 网页链接；仍不含日志正文。全部正文入箱前过统一脱敏与“已登记密钥”扫描，命中即替换为固定文本并记 `error_category=redacted`。
- 发送：纯文本（不用 parse_mode，避免任务名/工单标题注入 Markdown）；>4000 字分块。成功 → sent 并清空 text。连接建立失败、429 → 重试（遵守 retry_after，最多 5 次、累计≤10 分钟）；读超时/连接中断/5xx → `unknown`，**不重发**；400/403（chat 不存在、被拉黑）→ failed。重启时 `sending` 视为 unknown，`pending` 继续发。发件箱 pending>500 时丢弃最旧通知（记 dropped）；回复类优先于通知类。
- 重启补发：启动时扫描 `control.enabled_at` 之后进入上述状态、但发件箱无对应 dedup_key 的 run，补入箱（保证状态提交与入箱之间崩溃不漏发；dedup 保证不重复）。启用前的历史运行不补发。

### `/wi`（owner-only，只读）

- 复用 S2 WorkItemsService 与出站底座（共享 6 许可）：项目选择（已存 project）、固定版块（同旧五列）、列表分页 8 条/页、详情、全文（S2 HTML 清洗后转纯文本，3900 字分块）、关联项。每 chat 状态存内存（项目/版块/页），重启丢失可接受；列表缓存 60 秒。
- 图片按待决6：经 S2 媒体登记表与同源/类型/大小规则取图（png/jpeg/gif/webp，单张≤5 MiB，每工单≤10 张，总计≤20 MiB），`sendMediaGroup` 上传；任何一张不合规即跳过并在文末注明“N 张图片未发送”。
- ADO 错误只回固定类别中文（沿用 S2 category），**不回异常原文**（修旧端 `tg_work_items_bridge.py:268,333` 泄露）。`wi_m/wi_mr/wi_ma/wi_cp` 按钮不显示，留 S5。

### 统一脱敏（D02，复用 WP-12 规则）

- 把 `app_ado/redact.py` 的规则改写进新后端公共脱敏器（`logging_setup.py`，保持现有 `register_secret/redact_exception/contains_secret` 接口与调用方不变）：新增 bot URL 正则、认证头正则、已登记密钥的 `quote(safe='')`/`quote(safe='-_')` 变体，长的先替换；异常链展开≤6 层。S1–S3 既有脱敏测试不得放宽，新增回归覆盖 Telegram 情形。
- 应用点：日志、`tg_updates.reason`、`tg_outbox.error_category`/description、HTTP 错误 detail、WS 事件、回复/通知正文、设置页状态。Token 只出现在发往 api.telegram.org 的请求路径中。

### HTTP / WS 接口（全部在 S0 Host/CORS/Bearer/BodyLimit 之后；错误沿用 S1 detail 结构）

| 路由 | 语义 |
| --- | --- |
| `GET /api/telegram` | `{revision, control, bot:{credential:{present,source}, bot_id, username}, owner:{bound, chat_id, source}, notify, poller:{state, last_poll_at, last_error_category, consecutive_failures, since}, acl:{groups, members, legacy_whitelist}, warnings}`；不回传 Token、webhook URL、消息正文 |
| `PUT /api/telegram/token`、`POST /api/telegram/token/import-legacy`、`DELETE /api/telegram/token` | 见“凭据”；启用中 409 `telegram_active` |
| `POST /api/telegram/control/enable`、`POST /api/telegram/control/disable`、`POST /api/telegram/control/retry` | 见“生命周期”；enable 409 `ack_required/webhook_set/no_credential/telegram_store_unavailable`，502 `telegram_request_failed`（固定 category）；retry 仅在 conflict/backoff 时做一次探测 |
| `POST /api/telegram/owner/bind-code`、`DELETE /api/telegram/owner` | 生成一次性 6 位数字码（TTL 10 分钟、仅内存、同时只有一个、错误尝试≥5 次作废）→ owner 私聊发 `/bind <码>` 绑定；解绑需 revision |
| `PATCH /api/telegram/settings` | `{revision, notify?}` |
| `POST/PATCH/DELETE /api/telegram/acl/groups[/{id}]`、`POST/PATCH/DELETE /api/telegram/acl/members[/{id}]`、`PUT /api/telegram/acl/legacy-whitelist` | 均带 revision，返回 S1 MutationResponse；删组同时删其成员（旧语义，需前端二次确认） |
| `POST /api/telegram/test-message` | 向已绑定 owner 发一条固定测试文本；未启用/未绑定 409 |
| `GET /api/telegram/activity?limit=` | 最近处理记录（时间、kind、command、chat_id、status、reason），默认 50/最多 200；无正文 |
| `DELETE /api/tasks/{task_id}?detach_acl=true` | 待决5 |
| WS `telegram.status` | 轮询状态变化时广播 `{state, since, last_error_category}`；不新增订阅主题 |

- 错误码新增：409 `telegram_active/ack_required/webhook_set/legacy_missing/owner_not_bound`，502 `telegram_request_failed`，503 `telegram_store_unavailable`；422 `validation_error` 不回显输入。

### 安全核对表（施工与验收都按此）

| 风险 | 合同与测试证据要求 |
| --- | --- |
| 未授权 TG 用户 | none 角色零回复零副作用；owner 不自动绑定；群内 owner 不生效；伪造 callback_data（任意 task_id/令牌/他人 chat 的令牌）零执行；ACL 在确认时被收回 → 拒绝 |
| 越权停止/查看 | 非 owner 停他人运行被拒（含后端重启后）；status 只列可见范围；`/wi` 非 owner 拒绝 |
| 重复副作用 | 同一 update 重投、整批中途异常、确认按钮双击/多端同时点、后端在“登记 update 后/start 前/start 后回复前”崩溃，断言每种情况 run 数≤1；积压/过期指令不执行 |
| Token 泄漏 | 日志、DB/WAL、HTTP、WS、回复、通知、stderr、前端 DOM/storage 中搜不到假 Token（含 URL 编码变体）与 `/bot<id>:` 片段；httpx 异常含 URL 时仍只输出类别 |
| 注入 | 纯文本发送不用 parse_mode；SQL 参数化；指令参数只做白名单解析（tg_command 正则、work item id 整数、offset 1..5） |
| 双轮询 | 409 立即停止且不 deleteWebhook；webhook 存在不自动删除；导入/迁移不自动启用 |
| 资源/生命周期 | 长轮询取消、工作队列有界、发件箱有界、DB/客户端关闭、动作令牌上限；停用/关闭/异常各路径同一清理；慢 Telegram 不阻塞事件循环与 S3 |
| 数据外发 | `/wi` 图片仅同源且限额；通知默认不含详情；不把 ADO 异常原文发到 TG |

## S4 通用合同与模型分工

- **派工门禁**：用户确认本合同与「S4 待决」；主控写入「S4 已决」、提交输入 SHA 后才派工。
- 模型分工（用户 2026-10-23 已定）：后端施工 codex exec `gpt-6.1-sol` / medium、sandbox workspace-write、不联网；测试 codex `gpt-6-luna` / high（新增独立用例，每包最多一个测试员）；前端施工 agy `gemini-3.8-flash-high`，`--sandbox`，**不用** `--dangerously-skip-permissions`，cwd 缓存会话续接 `--conversation`；**不做交叉审计**。实际型号/档位以本地 rollout/回执为准，无回执记 unknown。
- 每包 worktree `.local/worktrees/s4{a,b,c}`，从明确输入 SHA detached 创建；施工者不 commit；主控限定 write_scope 的 binary patch 集成（`git apply --check`），集成版本重跑全部检查后本地 commit，不 push。worktree 删除前问用户。
- 测试只用临时数据目录、内存凭据、假 Telegram（`httpx.MockTransport` 模拟 getMe/getWebhookInfo/getUpdates/sendMessage/editMessageText/answerCallbackQuery/sendMediaGroup/deleteWebhook，含 409/401/429/超时/坏 JSON）与 S2/S3 既有假 ADO/临时 git；沿用 conftest 的 keyring/socket 守卫；禁止读真实配置/Keychain、连接真实 TG/ADO。
- `pnpm dev:web`：后端新增 `TOOLBOX_DEV_FAKE_TELEGRAM=1`（须 `--dev` + memory 凭据，否则启动失败），进程内假 Bot API，并仅在该模式注册 `POST /api/dev/telegram/inject`（注入模拟消息/回调，生产构建不存在此路由，测试断言 404）与 `GET /api/dev/telegram/sent`（查看假发送记录）。
- 派工明确禁止：按进程名 kill、裸 git stash、删除/放宽既有测试、仓库内留报告文件、改旧应用代码/配置/凭据、调用真实 Bot API；同类失败两次或需改本合同接口/状态/写范围/权限/限额即停下交主控。
- 每个缺陷修复先写会失败的回归，主控在集成树亲自复现修前失败再接受。新增依赖：不需要（httpx/sqlite3/asyncio 已有）；确需依赖停下交主控。

## S4-A：后端基础——配置 v2、Token、轮询生命周期、去重、ACL、通知

- 依赖：合同确认。write_scope：`next/backend/**`、`next/contracts/**`；测试员仅 `next/backend/tests/independent/s4a/`。
- 结果：config v1→v2 迁移与类型化 `telegram`（含 tasks 引用检查切换与 `detach_acl`）；Token 凭据与旧端导入；`telegram_http` 适配器与错误分类；`telegram.sqlite3` 与 runs v2 `origin_json`；TelegramService 生命周期（enable/disable/retry/基线/轮询/退避/409/关闭）；update 登记去重与过期规则；ACL 解析器与 `/bind`；发件箱与通知；统一脱敏；HTTP 设置/ACL/状态/activity 接口与 WS `telegram.status`；dev 假 Telegram 三重门。指令处理只实现 `/help`、`/start`、`/menu`、`/bind`、`/status` 与“未迁移”回复，执行类指令在 S4-B 前回复“暂未开放”。
- 自动验收：后端 `.venv/bin/python -m pytest -q`、`.venv/bin/ruff check .`、`.venv/bin/python -m toolbox_backend.contracts --check` exit 0（端口用例主控沙箱外跑）。覆盖：
  1. 迁移：旧形态 imported.telegram 各种合法/超限/重复/无效/旧 flow id；`control.enabled` 必为 false；迁移失败不写半文件；v2 再启动幂等；runs v1→v2 与未知高版本只读。
  2. 去重：同批 3 条第 2 条处理抛异常 → 1、3 正常且 offset 推进；重投 update 跳过；登记后崩溃不重放；首次基线丢弃积压；过期消息不执行只回复一次。
  3. 生命周期：409 立即 conflict 且零 deleteWebhook；webhook_set 需显式确认；401 → token_invalid；网络退避有上限；disable/shutdown 取消长轮询、在途处理≤5 秒、客户端/DB 关闭（断言无悬挂任务与连接）。
  4. ACL：owner 私聊/群、空 owner 不自动绑定与 `/bind` 码 TTL/尝试次数、chat_id 与 username 成员、旧白名单只读、none 零回复；ACL 编辑 revision 冲突、组删成员级联、detach_acl 原子性与不扩大授权。
  5. 通知：UI/TG 来源路由、include_details 两态正文、不含 stderr/URL/假 Token、dedup 不重复、崩溃补发、429/超时/403 的状态与是否重发。
  6. 脱敏：WP-12 全部用例形态（bot URL、`%3A`、认证头各引号形式、URL 编码 token、异常链）在新脱敏器通过，S1–S3 脱敏测试不变。
- 回退：恢复本包 write_scope 至输入 SHA；已迁移的 config v2 与 runs v2 不自动降级（旧版本进入只读错误态，按迁移快照人工恢复），这一点在 PROGRESS 记录。

## S4-B：后端指令——任务三操作、停止、状态、`/wi`

- 依赖：S4-A 集成（同一 codex 会话 resume 续接）。write_scope 与测试路径同 S4-A（测试员 `tests/independent/s4b/`）。
- 结果：动作令牌（生成/TTL/原子消费/上限）；任务菜单、构建发布/仅发布确认流、回滚 offset 预检与确认、停止、状态可见范围；S3 错误码映射；`/wi` 列表/详情/全文/关联/图片（按待决6）；工作队列有界与“忙”回复；`editMessageText` 就地更新（失败退回新消息）。
- 自动验收命令同 S4-A。覆盖：
  1. 全流程（假 Bot + 假 ADO + 临时 git）：TG 构建发布成功并通知触发者；只发布精确制品；回滚 offset 冻结；UI 触发通知 owner。
  2. 幂等：确认双击、两个 update 带同一令牌、令牌过期、plan 过期、确认前 ACL 被收回、任务被禁用/删除、`task_active`；每种 run 数≤1 且回复固定文案。
  3. 停止：非 owner 停自己/他人、重启后归属仍有效、unknown 运行提示；伪造 callback 零写。
  4. `/wi`：非 owner 拒绝、同源/越界/超限/类型不符图片跳过、ADO 错误不回原文、分块边界、媒体组≤10。
  5. 慢 Telegram/慢 ADO 不阻塞轮询与 S3 事件；队列满回复“忙”；全部输出无假 Token/PAT。
- 回退同 S4-A。

## S4-C：前端——设置页 Telegram 分区与任务删除解除引用（agy）

- 依赖：S4-A 接口冻结（主控生成 `schema.d.ts` 后派）；可与 S4-B 并行（不同路径）。
- write_scope：`next/desktop/src/features/settings/**`（新增 Telegram 分区组件与 api）、`next/desktop/src/features/tasks/**`（仅删除确认 Sheet 的“同时从 N 个权限组移除”选项与运行来源标记）、`next/desktop/tests/**`（新增文件）、`next/desktop/scripts/dev-web.mjs`（仅假 Telegram 开关）、`next/desktop/README.md`；schema 由主控生成。测试员（codex gpt-6-luna/high）仅 `tests/independent/s4c-*`。
- 结果：按 R1 组件与 B-Settings 卡片样式（无独立设计稿，不新增视觉令牌）：Bot 卡片（凭据状态、导入/录入/删除、bot 用户名）；接管卡片（启用开关 + 切换步骤与必选确认、轮询状态胶囊、conflict/webhook/token_invalid 中文说明与“重试接管”）；owner 卡片（绑定码、倒计时、解绑）；通知卡片；权限组/成员编辑（沿用 S1 编辑会话与 revision 冲突处理，删组二次确认列出将删成员）；旧白名单编辑；最近活动列表。Token 输入框提交后清空，永不回显；不 localStorage 任何 TG 数据（选中分区除外）。
- 自动验收：`pnpm install --frozen-lockfile`、`pnpm typecheck`、`pnpm lint`、`pnpm test`、`pnpm build`、`pnpm guard:dist`、`pnpm contracts:check` 全部 exit 0。覆盖：启用需确认、各错误态文案、409 冲突刷新、Token 不进 DOM/storage、ACL 表单校验与任务选项、删除任务两种路径、WS `telegram.status` 更新、键盘可达。
- 主控 dev:web 假环境截图：Bot 未配置/已配置、启用确认、conflict、owner 绑定、权限组编辑、删除任务解除引用、注入假消息后的活动列表与运行来源。

## S4 集成验收（主控）

- 后端完整 pytest/ruff/contracts；前端 frozen install/typecheck/lint/test/build/guard:dist/contracts:check；Rust `cargo fmt --check`、`cargo clippy --offline -- -D warnings`、`cargo test --offline`；根目录旧代码守卫测试不回退；`git diff --check` 与限定路径检查。S3 的 740/903 是历史基线，不冒充 S4 结果。
- 主控亲自核对：update 登记与处理的崩溃点、动作令牌消费与 start 幂等、409 停止、关闭路径资源回收、通知不漏不重；应用四技能 + resource-lifecycle-audit 复核。
- dev:web 端到端（假 Bot + 假 ADO + 临时 git）：启用 → `/help` → 任务确认执行 → 通知 → `/stop` → `/rollback` → `/wi` → 模拟 409 → 停用；全程扫描假 Token/PAT。
- 对照本节旧事实与 `docs/capabilities/telegram-control.md` 在 PROGRESS 列 迁移 / 改进 / 有意推迟（S5–S8）清单。

### 真实验收清单（仅用户另行授权后执行；本合同提交不执行）

1. 用户在 BotFather 建**测试 Bot**，Token 只在新端设置页录入；owner 用 `/bind` 绑定；第二个 Telegram 账号作为组成员；一个测试群。
2. 指令：`/help` 菜单、构建发布/仅发布/回滚确认流（用 S3 专用测试仓库与测试环境）、`/stop` 他人/自己、`/status` 可见范围、`/wi` 文本与图片；none 用户无响应。
3. 去重与恢复：执行中重启后端，确认无重复 run、通知补发一次；停机期间发指令，重启后不执行并提示过期；同一按钮双击。
4. 双轮询：在测试 Bot 上用另一进程（或旧端临时配测试 Bot）同时轮询，确认新端进入 conflict 且不抢占；webhook 已设时的确认流程。
5. 主 Bot 切换（按待决1 的时机，另行授权）：导入旧 Token → 用户删除旧 Keychain 主条目 → 新端启用 → 旧端三个 AI 机器人仍正常 → 回退演练（新端停用、旧 UI 重填 Token）。
6. 真实 Keychain 授权/拒绝、代理环境下连通性（按待决8）；未测逐项记账。

## S4 待决（已决，保留选项以便追溯；备选均不实施）

技术已定（无需拍板）：telegram.sqlite3 与 runs v2 来源字段、update 先登记后处理的至多一次语义、409 让出不抢占、动作令牌与幂等键、发件箱不重发不明结果、纯文本发送、统一脱敏、ACL 确认时重查、非 owner 状态可见范围收窄、`/wi` 不回异常原文、AI 机器人与服务/VPN/MCP 菜单不在 S4。

| 编号 | 需要拍板 | 推荐 | 备选与影响 |
| --- | --- | --- | --- |
| 1 | 主 Bot 何时、如何切到新端 | **S4 用单独的测试 Bot 完成开发与真实验收，主 Bot 暂留旧端；等 S6–S8 把服务/VPN/MCP 菜单迁完后，再按“导入 Token → 删除旧 Keychain 主条目 → 新端启用”一次切换**。旧端三个 AI 机器人不受影响 | A：S4 验收后立即切主 Bot，TG 端暂时失去服务/VPN/MCP 菜单（旧桌面端仍可用）直到 S6–S8；B：新端长期用新 Bot，成员改用新 Bot、群需重新拉入；C：关闭旧端“启用 Telegram 触发任务”——会同时停掉旧端三个 AI 机器人，不推荐 |
| 2 | TG 触发执行是否加确认步骤 | **加**：先预检并展示计划摘要，点“确认执行”才启动（满足 S3 预检/确认语义与 ack），多一次点击 | 保持旧端一键执行：收到指令直接预检+启动；更快，但无法在执行前看到精确制品/目标，ack 由系统代签 |
| 3 | owner 为空时如何绑定 | **不自动绑定**；沿用导入的 owner chat_id；为空时在设置页生成一次性 6 位码，owner 私聊发 `/bind <码>` | 沿用旧端“第一个私聊的人自动成为 owner”：零操作，但谁先找到 Bot 谁就拿到全部权限 |
| 4 | 按 `@username` 配置的成员与旧白名单 | **username 成员只在私聊匹配；首次匹配时记录其 Telegram user_id，之后只按 user_id 匹配**（防用户名被转手）；设置页标明“已绑定/未绑定”。旧白名单保留为只读（仅 status） | A：完全沿用旧端（任何场景按 username 匹配）；B：废弃 username，只认 chat_id（需要成员提供数字 id，已有 username 条目失效） |
| 5 | 删除被 ACL 引用的任务 | **提供“删除并从 N 个权限组移除”**：同一次写入删除任务并移除引用，组权限位不变；不选仍 409 | 保持 S3 现状：必须先去权限组手动取消勾选再删任务 |
| 6 | `/wi` 是否把工单图片转发到 Telegram | **保留**（仅 owner、同源、类型白名单、单张≤5 MiB/每工单≤10 张）；与旧端一致 | 只发文本，并提示“图片请在桌面端查看”：附件不离开 ADO/本机，少一次数据外发 |
| 7 | 停机期间积压的指令 | **超过 5 分钟的指令不执行**，回复一次“已过期，请重新发送”；首次启用丢弃全部积压 | 沿用旧端：重启后照常执行积压指令（可能在无人注意时触发发布） |
| 8 | 访问 api.telegram.org 是否走系统代理 | **沿用旧端：跟随环境变量与 macOS 系统代理**（仅 Telegram 客户端；ADO 仍不走代理），代理地址中的凭据脱敏 | 不走代理（与 ADO 一致）：网络环境需要代理时 Telegram 不可用；或新增显式代理设置项（扩大 S4 范围） |

## S4 已决

- 用户2026-10-23原答复：**“S4 的八项待决均按你推荐的来。”**，确认八项：1 S4 用单独测试 Bot 开发与真实验收，主 Bot 暂留旧端，S6–S8 迁完服务/VPN/MCP 菜单后按“导入 Token → 用户删除旧 Keychain 主条目 → 新端启用”一次切换；2 TG 执行先预检展示计划，点“确认执行”才启动；3 owner 不自动绑定，为空时用一次性 6 位码 `/bind`；4 username 成员仅私聊匹配、首次匹配记录 user_id 后只按 user_id 匹配，旧白名单保留为只读；5 提供“删除并从 N 个权限组移除”原子删除，组权限位不变，不选仍 409；6 `/wi` 保留图片转发（仅 owner、同源、类型白名单、单张≤5 MiB/每工单≤10 张）；7 超过5分钟的指令不执行并回复过期，首次启用丢弃全部积压；8 Telegram 客户端跟随环境变量与 macOS 系统代理（ADO 不走代理），代理凭据脱敏。
- 本确认解除派工门禁；不授权主 Bot 切换、真实 Telegram/ADO 连接、读取真实配置/凭据或删除 worktree，真实验收按清单另行授权。合同中“按待决N”均由以上已决收敛，施工者不得选择备选路径。
- 派工顺序：S4-A（codex gpt-6.1-sol/medium）→ S4-B（同会话续接）；S4-C（agy gemini-3.8-flash-high，`--sandbox`）在 S4-A 接口冻结后可与 S4-B 并行；每包最多一个 codex gpt-6-luna/high 测试员；不做交叉审计。
