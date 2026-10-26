<!-- 归档自 WORK_PACKAGES.md 第 15–134 行（2026-10-26，提交 b5eca58 时的内容，仅相对链接改为指向原位置）。索引见 ../README.md -->

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
