# 重构进度与署名账本

plan_id: modernization-20261021。账本允许追加证据和更正状态，不把计划中的动作当已完成。

## 工作区基线

- HEAD：`c349243286d27ae82943a4381951f9f3b041b7d1`。
- 用户既有修改：`app_ado/ui/deploy_target_dialog.py`（5 add / 5 del）、`config/ai_change_policy.yaml`（1 add / 1 del）。本轮不修改这两文件。
- 内容 SHA-256：前者 `ad36f8f36e5d8230f23f5b093e535b7817e85c939dc3572aab98584278355ce7`；后者 `cd1db2fd597a4bc2fb654d0f38439decfdaab54e4f5ca5b2120cc72c21784adc`。集成和交付前复核。
- 正式平台：当前 Apple Silicon Mac；Python 以仓库 `.venv` 实际解释器为准，不信陈旧 pyvenv.cfg。
- 本轮不执行 commit/push/部署、不安装工具、不删除业务或用户数据。

## 工作包状态

| 包 | 施工状态 | 交叉审计 | 证据/限制 |
| --- | --- | --- | --- |
| WP-00 规范与施工包 | passed | round1_returned；round2_timeout | 文档链接核对；首轮 7 项改进已落实，未冒充复审通过 |
| WP-01 基线工具 | passed（采集工具） | round2_timeout | Sol medium 施工、Luna high 独立测试；25 targeted tests |
| WP-02 离线行为表征 | passed（缺陷证据） | round2_timeout | Sol medium 施工、Luna high 独立测试；5 current_behavior tests |
| WP-03 GUI/工作状态测量 | cancelled（2026-10-22） | not_dispatched | 新应用自 S0 建立性能基线 |
| WP-11、WP-12 | passed（2026-10-22 旧应用热修） | not_dispatched | 见文末记录 |
| WP-13..15 风险修复 | moved：WP-13→S1、WP-14→S6、WP-15→S3（用户 2026-10-22 确认） | not_dispatched | 旧应用不再施工 |
| WP-16 外部接口与恢复契约 | planned | not_dispatched | 需先核验接口，禁止猜测施工 |

## 署名记录

| 角色 | requested_model / effort | actual_model / effort | 通道 / 标识 |
| --- | --- | --- | --- |
| 主控/文档/集成 | GPT 6.1 Sol / high | unknown / unknown（当前工具未公开主控运行型号与档位） | 当前 Codex 聊天；runtime_identity=codex |
| WP-01 施工 | gpt-6.1-sol / medium | unknown / unknown；调度参数已被工具接受，无提供方回执 | native subagent `/root/baseline_builder` |
| WP-01 测试 | gpt-6-luna / high | unknown / unknown；以显式调度调用为证据 | native subagent `/root/baseline_builder/baseline_tests` |
| WP-02 施工 | gpt-6.1-sol / medium | unknown / unknown；以显式调度调用为证据 | native subagent `/root/characterization_builder` |
| WP-02 测试 | gpt-6-luna / high | unknown / unknown；以显式调度调用为证据 | native subagent `/root/characterization_builder/characterization_test` |
| 交叉审计 | claude-sonnet-5-5 / medium | claude-sonnet-5-5（CLI modelUsage）；effort 仅命令参数可验证，实际回执未提供 | claude-code；本地 review_id 见下表 |

## 异步审计队列

审计状态与施工状态分开。不要求审到零问题再推进。审查边界须包含 SHA-256/commit，不得将旧审计结果套到后续版本。

| review_id | 审计目标 | 模型/档位 | 状态 | 连续性/结果 |
| --- | --- | --- | --- | --- |
| prep-cross-8910f853 / round1 | 规范、工作包、入口五文件固定快照 | claude-sonnet-5-5 / requested medium | returned | 首轮 rework required（1 major、6 minor）；已核实修订，不阻塞施工 |
| 同 review_id / round2 | 以上修订 + 采集脚本/测试 + 表征测试 | 同模型 / requested medium | timeout | 续接同一会话，180 秒超时，已终止任务所属进程；无第二轮结论，不阻塞其他包 |

## 问题账本

初始业务债务 D01..D16 见 [README.md](README.md)。本次交付产生的审计发现使用 CR-PREP-xxx；每项包含位置、触发条件、证据、影响、负责人及 open/fixed/rejected/deferred/blocked 状态。

| finding_id | 首轮级别 | 问题与核实 | 处置 |
| --- | --- | --- | --- |
| CR-PREP-001 | major | 无标记、显式空 tasks 的迁移判定不明确 | fixed：WP-13 明确按原始键存在性判定，null/错误类型不回退 |
| CR-PREP-002 | minor | 测试合同未充分明确禁止真实读取及隔离方法 | fixed：通用合同补临时配置、fake凭据及意外访问失败；HOME不足以隔离Keychain |
| CR-PREP-003 | minor | worktree 带回方式与脏文件保护不明确 | fixed：主控核对哈希、限定patch，新增文件不覆盖；共享树不stash/reset/checkout |
| CR-PREP-004 | minor | 模型署名证据来源/自测与独立测试不明确 | fixed：新增 evidence_source；无回执 actual=unknown，自测 independent=false |
| CR-PREP-005 | minor | GPT 审计档位缺省 | fixed：审计池明确 Sol high、Claude medium |
| CR-PREP-006 | minor | 多包转正同一表征文件的所有权冲突 | fixed：主控独占转换，施工者交付各包新回归，集成时一起验证 |
| CR-PREP-007 | minor | 不可信图片与跨源跳转行为不明确 | fixed：不可信不发请求，逐跳同origin；已确认CDN需求须先补策略 |

上表 fixed 是主控逐项核实并修订文档，审计者复核结果另记；不得冒充已经复审通过。原始请求/响应、会话ID和快照哈希位于 git 忽略的 `.local/reviews/prep-cross-8910f853/`。本轮审计未执行代码，仅审查提供的固定快照。

## 验证与未测

- 初轮历史记录：36 passed / 2 skipped；Python 3.14.7 下 270 tracked Python AST 解析通过；ADO MCP 只读协议冒烟通过。这些不是当前新增文件的验证。
- WP-01：施工者和独立 Luna high 测试者复验，25 targeted tests passed；WP-02：施工者与独立 Luna high 测试者复验，5 current_behavior tests passed。
- 主控集成后完整 pytest：**66 passed / 2 skipped，exit 0**，0.94s；TemporaryDirectory 已清理。命令和代码摘要见 [verification-2026-10-21.json](verification-2026-10-21.json)。
- 实际执行采集工具：inventory 报告生成成功；受限 import probe 因 os.putenv 保护拦截返回 error、cleanup=ok，未输出有效导入性能指标。[baseline-2026-10-21.json](baseline-2026-10-21.json) 只代表独立口径的文件/依赖元数据。
- 阶段 0 整体为 partial；WP-03 完整GUI/工作负载测量未执行。阶段 1 生产风险修复尚未实施，五个表征通过不代表已修复。
- 未测：完整 GUI 首屏/空闲/工作内存、真实 Telegram 长轮询、真实 ADO 发布与恢复、VPN 登录、Lark OAuth 轮换、Figma 限流与 ok-script Windows/Cython 行为。

## 资源所有权

- baseline：用户既有工作树、既有 `.venv`/dist/进程/用户配置，保留。
- temporary：WP-01、WP-02 独立 managed worktree 已集成并归档，工具返回 archived_worktree，可恢复；测试临时目录已回收。
- 交叉审计第二轮超时已结束，未取得复核结论；本地请求、响应及版本摘要保留作后续定点复核依据。
- artifact：本目录规范、施工包、账本、非敏感基线报告；开发采集工具与测试。
- 任务没有权限按名字停止既有服务或清理旧配置/日志。

## 2026-10-22：方向变更与重写分支

- 决策：用户确认前后端分离重写（Vue 3 + Vite、Tauri 2 薄壳、Python 3.14 + FastAPI），旧 UI 不保留。文档：[ARCHITECTURE.md](ARCHITECTURE.md)、[FRONTEND_STACK.md](FRONTEND_STACK.md)、[MIGRATION_PLAN.md](MIGRATION_PLAN.md)、`next/README.md`；README、WORK_PACKAGES、能力索引已加变更标注。
- 主控：requested 无指定（用户直接对话）；actual 当前会话 Claude Code，模型 claude-opus-5-5（系统提供的运行时信息），effort unknown（工具未回执）。本轮无子 agent、无交叉审计（not_dispatched）。
- 分支/文件夹：`git worktree add -b rewrite/next ../my-own-script-next HEAD`（base c349243）。旧文件夹保持 `main` 与全部脏文件不变；用户两文件 SHA-256 复核与基线一致。
- 带入方式：未 commit。将 WP-00/01/02 的 13 项改动/新增从旧文件夹逐文件拷贝到新 worktree，`cmp`/`diff -r` 核对一致；用户两文件（deploy_target_dialog.py、ai_change_policy.yaml）未带入。旧文件夹中这些文件仍为未提交状态，后续二者分别演进时需注意不要混淆版本。
- 验证（新 worktree，旧 `.venv`）：`PYTHONDONTWRITEBYTECODE=1 ../my-own-script/.venv/bin/python -m pytest -p no:cacheprovider tests` → 首次 1 failed（见 CR-NEXT-001），重跑 **66 passed / 2 skipped，exit 0**；该用例单独重复 15 次全部通过。
- 未做：S0 骨架、依赖安装、视觉方向稿、WP-11/12 热修；WP-03/11..16 处置待用户确认（MIGRATION_PLAN §4）。

| finding_id | 级别 | 问题与核实 | 处置 |
| --- | --- | --- | --- |
| CR-NEXT-001 | minor | `tests/test_modernization_baseline.py::test_probe_failure_timeout_and_guards[open('created', 'w')-error]` 以 0.2s 超时期待 `error`；冷启动子进程超过 0.2s 时返回 `timeout`，属计时型偶发失败（首跑失败、随后 16 次通过） | open：放宽该参数的超时或把 error/timeout 判定分开；不影响生产代码 |

## 2026-10-22：WP-11 / WP-12 旧应用热修（main 文件夹）

- 授权：用户同意在旧应用上先修 WP-11/12，并指定派 Sonnet 施工；WP-13..16 与 WP-03 的处置仍待确认（MIGRATION_PLAN §4）。未 commit。
- 施工环境：主控从 HEAD c349243 建两个 detached worktree（会话 scratchpad 内），拷入表征测试与本目录文档；主控审阅 diff 后以 `git apply --check` 后的限定路径 patch 集成到 `/Users/wesker/my-own-script`，新增文件确认目标不存在。用户两文件 SHA-256 复核不变。
- 代码版本（集成后内容 SHA-256 前 16 位）：ado_work_item_http `21d85d800330944c`、work_item_view `1253639019f0e9c1`、ui/work_items_tab `8dab455f39ba17a6`、tg_work_items_bridge `c4035cea7a9a98ab`、mcp_ado_work_items_server `cb8fb7aa1ca79662`、tg_control `3b0835400b556d29`、notifier_telegram `82bcf4631368d91c`、redact（新）`2a3eba767a20fcdb`、test_attachment_security `f919c3da7a7ae37e`、test_telegram_redaction `0d576d842137cc3e`、test_modernization_characterization `f5c3b97b260df152`。

| 包 | 施工状态 | 交叉审计 | 证据 |
| --- | --- | --- | --- |
| WP-11 附件认证边界（D01） | passed（自动验收）；真实 ADO 待用户验收 | not_dispatched | 新增 trusted_base_url 必填参数贯穿 UI/TG/MCP；不同源不发请求；逐跳手动重定向，跨源/降级/userinfo/超 5 跳终止；50 tests |
| WP-12 TG 错误脱敏（D02） | passed（自动验收） | not_dispatched | 新 `app_ado/redact.py`；tg_control 5 处异常文本 + `_log`/`last_error` 兜底；notifier 错误不带原异常链；409/超时分支仍读原文；47 tests |

署名：

| 角色 | requested_model / effort | actual | 通道 / 标识 |
| --- | --- | --- | --- |
| 主控/审阅/集成/表征转正 | 未指定 | claude-opus-5-5（运行时系统信息）/ effort unknown | Claude Code 当前会话 |
| WP-11 施工 | sonnet（Sonnet 5.5）/ medium | unknown / unknown；显式调度参数为证据，无提供方回执 | Claude Code 原生子 agent |
| WP-11 测试 | haiku（Haiku 5.5）/ medium | unknown / unknown | 施工者派出的原生子 agent，independent=true |
| WP-12 施工 | sonnet（Sonnet 5.5）/ medium | unknown / unknown | Claude Code 原生子 agent |
| WP-12 测试 | haiku（Haiku 5.5）/ medium | unknown / unknown | 施工者派出的原生子 agent，independent=true |

验证：

- WP-11 施工自测 25 passed；Haiku 追加 25 项后 50 passed，未发现实现缺陷。
- WP-12 施工自测 13 passed；Haiku 追加 34 项，首轮 41 passed + 6 xfailed（6 个真实缺口：任意认证方案词、X-*-Token 头、编码后的已知 token、分支判定被异常链改变、notifier `__context__` 残留原 URL 等）；施工者修复其中 5 项并移除全部 xfail，47 passed。第 6 项（未知 token 以编码形式出现在 /bot 路径外）为设计边界，记 CR-NEXT-006。
- 主控转正：D01、D02 两条 `test_current_behavior_*` 改为 `test_regression_*`（外部图片零请求且可信图仍带认证；日志/状态无 token 且保留 401 与 `/bot***/getUpdates`）。其余三条表征保持缺陷证据。
- 集成版本：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests` → **163 passed / 2 skipped，exit 0**；改动模块 AST 解析与 offscreen import 冒烟通过。
- 未测：真实 Qt 工单详情显示、真实 ADO 附件下载（尤其是否存在跨源 CDN 重定向）、真实 Telegram 401/409、TG 图片组发送。交叉审计未派发。
- cleanup：两个临时 worktree 已 `git worktree remove`；patch 与测试输出保留在会话 scratchpad。

| finding_id | 级别 | 问题与核实 | 处置 |
| --- | --- | --- | --- |
| CR-NEXT-002 | major | `app_ado/notifier_telegram_meta.py:17-20` `get_me` 的 `raise_for_status` 异常含完整 bot URL，ok=false 也直接拼数据；若 UI 显示/记录即泄露（WP-12 施工者 grep 发现） | fixed：2026-10-22 增量，见下 |
| CR-NEXT-003 | minor | `app_ado/ai_headless_tg_bridge.py:654-668` `_tg_send` URL 含 token，异常现被 `except: pass` 吞掉，暂无泄露 | deferred：新后端 S4/S5 统一 |
| CR-NEXT-004 | major（待证） | 旧注释称 ADO 附件常 302 到 CDN；按合同跨源终止，若真实环境如此则图片不再显示 | open：需用户在真实工单验收；如属实由主控核验后补明示受信策略 |
| CR-NEXT-005 | minor | UI 对被拒外部图片只是跳过下载，HTML 中原 `<img src>` 保留，无“已拦截”占位；QTextBrowser 默认不加载远程资源（未在真实 Qt 验证） | deferred |
| CR-NEXT-006 | minor | 未知 token 以百分号编码形式出现在 /bot 路径外时无法识别 | rejected（设计边界，已知 token 均已覆盖） |

### 2026-10-22 增量：CR-NEXT-002 修复

- 用户指示修复；主控（claude-opus-5-5，effort unknown）直接实施，未派子 agent，`verified_by=executor, independent=false`。
- 改动：`app_ado/notifier_telegram_meta.py` 的 `get_me` 捕获 `httpx.HTTPError`，以 `redact_exception` 生成消息并在 except 外 `raise RuntimeError(...) from None`；ok=false 消息经 `redact_text`。成功路径与返回值不变；调用方（`ui/telegram_card.py`、`ui/ai_config_tab.py`）均只捕获 Exception，不受类型变化影响。
- 测试：`tests/test_telegram_redaction.py` 新增 6 项（401/404/500、连接错误、ok=false 回显 token、成功路径）；旧实现抛 HTTPStatusError 而非 RuntimeError，这些用例在旧代码上会失败。集成版本全量 **169 passed / 2 skipped，exit 0**。
- 未测：真实 Telegram getMe、设置页 UI 显示。

### 2026-10-22 交付与阶段 1 处置确认

- 用户授权提交推送。`main` 提交 `885d186`（WP-11、WP-12、CR-NEXT-002 生产代码、两份新测试、两页能力文档；pre-commit 自动升版 app_version.py），已推送 `origin/main`。用户两文件、现代化文档/工具/表征测试未纳入该提交，仍为未提交状态。
- 用户确认 MIGRATION_PLAN §4“按建议”：WP-13（D04/D05）→ 新后端 S1；WP-14（D08）→ S6；WP-15（D06）→ S3，旧应用如遇错接管再热修；WP-03 cancelled；WP-16 保留为 S6/S7 前置调查。旧应用阶段 1 不再施工。

### 2026-10-22 视觉方向

- 出稿：A Nocturne、B Porcelain（各三屏）、C Hyperdrive（仅总览，按用户要求中止）；用户改选 rhine-lock 工业 HUD 风格，出 D 方向三屏 × 常态/告警六张。主控 claude-opus-5-5 直接绘制，未派子 agent；画布渲染未由主控核验。决定与来源署名见 FRONTEND_STACK §7。

## 2026-10-22：S0 骨架

- 主控：requested 未指定（用户直接对话）；actual claude-opus-5-5（运行时系统信息），effort unknown（工具未回执）；Claude Code 当前会话，role=lead。
- 提交：`59bcbb1`（本分支既有文档、基线工具与表征测试，用 `SKIP_VERSION_BUMP=1` 跳过旧应用的版本自增钩子，避免与 main 的 `app_version.py` 冲突）；`326789b`（S0 合同写入 WORK_PACKAGES、`.gitignore` 增加 `next/` 构建产物）。
- 参考材料：设计稿 D 页四个 `.dc.html` 取自 claude.ai 画布 version 1792648966-06d1；rhine-lock 浅克隆 commit `a4df68c`（AGPL-3.0）。均放在 git 忽略的 `.local/`。
- 环境：pnpm 11.25.0、uv 0.13.4、Rust/cargo 1.95.0、Node 24.13.0、Python 3.14.7；数据卷可用约 23 GiB（风险：Rust 构建目录，已要求共享 `CARGO_TARGET_DIR`）。

- 交叉审计：用户 2026-10-22 指示本轮不派交叉审计，由主控自审，问题后续再交叉审计。故下表审计列为 not_dispatched（主控自审 ≠ 独立审计）。
- 提交：`90c70e3`（S0-A/B/C 集成）；S0-D 与本账本见随后的提交。

| 包 | 施工 | 测试 | 审计 | 状态 / 证据 |
| --- | --- | --- | --- | --- |
| S0-A 后端与契约 | sonnet / medium（原生子 agent，worktree s0a） | haiku / medium（施工者派出，independent=true） | not_dispatched；主控自审 | passed：主 worktree `uv sync --frozen`、`ruff check`、`contracts --check` exit 0；`pytest` 195 passed（裁决后连跑 3 次中 2 次全过，1 次失败触发裁决，见 S0A-003） |
| S0-B 前端 HUD 壳 | sonnet / medium（s0b） | haiku / medium，independent=true | not_dispatched；主控自审 | passed：`typecheck`/`lint`/`build`/`contracts:check` exit 0；Vitest 121 passed（先 build 后 test，见 S0B-007） |
| S0-C Tauri 壳 | sonnet / medium（s0c） | haiku / medium，independent=true | not_dispatched；主控自审 | passed：`cargo fmt --check`、`clippy -D warnings` exit 0；`cargo test` 36 passed；`pnpm tauri build --debug --no-bundle` exit 0 |
| S0-D 打包 spike | sonnet / medium（主 worktree，写 `next/spikes/packaging`） | haiku / medium 只读复核 | not_dispatched | done：结果见 `next/spikes/packaging/results-2026-10-22.json`；主控复测启动耗时同量级 |

actual 型号/档位：四个施工者与四个测试者均为 Claude Code 原生子 agent，调度参数（model、effort=medium）被工具接受，无提供方回执 → actual=unknown。

### 集成联调（主控，集成版本）

- `pnpm dev:web` + 真实后端 + 浏览器窗格 1440×900：ONLINE、真实 pid；告警开关 → 后端广播 `system.alert` → 全页 `--denied` 黑橙 + WARNING 框；关闭后恢复；控制台无错误；dev 日志无 token。结束后端 → dev:web 随之退出（开发脚本行为）。
- Tauri debug 壳 + 真实后端：READY → WebView 经 `invoke` 取连接，`/ws/events` 被 accept；SIGKILL 后端 → 1 秒后重启（新 pid/端口），WebView 用新 token 重连成功；第二实例立即退出；SIGTERM 壳 → 壳退出、后端进程组 `kill -0` 不存在；壳日志无明文 token。
- 旧代码守卫：`../my-own-script/.venv/bin/python -m pytest tests` → 66 passed / 2 skipped（与基线一致）；`git diff --check` 通过；`next/` 外仅文档与 `.gitignore`。

### 打包 spike 结果（S0-D，M4 / macOS 27.0.1，CPython 3.14.8）

| 指标 | A python-build-standalone（含 pyc） | B PyInstaller onedir |
| --- | --- | --- |
| 运行时目录 | 61.7 MB（不含 pyc 41.8 MB） | 31.2 MB |
| ditto zip | 22.7 MB | 17.0 MB |
| 热启动到 READY（5 次中位数） | 0.265 s | 0.328 s |
| 新副本首跑 | 0.825 s（不带 pyc 1.55 s） | 1.05 s |
| 空闲 RSS 中位数（离散大） | 40.6 MB | 35.6 MB |
| 可重定位 / 非系统动态库 | 是 / 无 | 是 / 无 |

- Tauri 空 .app 9.5 MB（zip 3.5 MB）；整包估算（空壳 + 拷贝运行时，未真正接入 bundle）A 约 71 MB（zip 26.6 MB）、B 约 41 MB（zip 20.5 MB）。
- 施工者建议倾向 A（标准解释器、无隐式导入漏收集风险）；主控同意作为倾向，**最终在 S9 结合签名/公证实测再定**（ARCHITECTURE §8 未决项更新为“已有实测，待定”）。
- 未测：签名/公证与 Gatekeeper 首启、ULFO DMG、真正冷盘（无 purge 权限）、运行时接入 bundle 后的真实 .app。

### 主控裁决与发现

| finding_id | 级别 | 问题与核实 | 处置 |
| --- | --- | --- | --- |
| S0A-001 | minor | WS 二进制首帧导致 1006 | fixed（施工者） |
| S0A-002 | minor | 深嵌套 body 使 422 回显递归 → 500 | fixed（不回显 input） |
| S0A-003 | minor | READY 前 SIGTERM 可能早于解释器执行 Python，退出 -15；负载下 0.05–0.4s 均可能发生（主控复现） | 裁决：合同改为 READY 后必须退出码 0，READY 前允许被信号终止但不得挂起/再打印 READY；独立测试按“是否已 READY”判定（WORK_PACKAGES 已注明） |
| S0A-004 | — | 事件命名歧义 | rejected：已统一 topic=`system`、type=`system.*`，前端一致 |
| S0A-005 | minor | 完全不读的客户端收不到 4408 关闭帧（uvicorn 背压），2 秒后拆连接 | deferred：不影响其他连接 |
| S0A-006 | minor | WS 无 Origin 头视为允许（非浏览器本机客户端，仍需 token） | deferred：S1 复核 |
| S0A-007 | minor | `/api/system/alert` 无 body 大小上限 | open：S1 统一请求体上限 |
| S0B-001 | minor | 合同要求页脚署名与禁词 grep 冲突 | fixed（主控）：页脚注明 rhine-lock；禁词改为 `Rhine Lab`/Arknights/莱茵/Google Fonts |
| S0B-005 | minor | dev 变量在构建时设置会把 token 内联进 dist | fixed（主控）：仅 `import.meta.env.DEV` 读取，补测试 |
| S0B-006 | minor | 左栏切片号与 MIGRATION_PLAN 不符 | fixed（主控）：设置 S1、AI 会话 S5、MCP S6、VPN S8 |
| S0B-007 | minor | 独立禁词测试依赖已存在的 dist，`pnpm test` 早于 build 会失败 | open：S1 改为无 dist 时跳过或由 build 后单独脚本检查 |
| S0B-008 | minor | 总览 UPTIME 只在首次 `/health` 取值，不随心跳刷新（联调截图发现） | open：S1 |
| S0C-001 | major | stderr 按 4096 字节块脱敏，跨块 token 前缀可入日志（Haiku 发现） | fixed（施工者），独立用例覆盖 |
| S0C-002 | — | CSP 额外允许 `ipc:` 与 dev HMR | accepted：Tauri IPC 必需，联调验证 WebView 连接正常 |
| S0C-004 | minor | 握手前 stderr 暂存至多 20 秒才输出 | accepted（防 token 泄漏的取舍） |
| S0D-001..005 | info | pyc 必须随包；PBS 可裁 libpython；PyInstaller 隐式导入风险；RSS 离散；S9 需逐个签名 | 记入 S9 |

### 未测（需用户或后续补测）

托盘菜单交互与状态文字、关窗隐藏与 Dock 重新打开、⌘Q 路径、覆盖式标题栏拖拽、1280×800 / 1728×1117 视觉走查、Tauri 内截图；默认 5 秒心跳与 20 秒握手超时只用缩短参数测过。

### 资源与清理

- 施工 worktree `.local/worktrees/s0a|s0b|s0c`：用户确认后移除（逐文件核对仅余临时占位与主控修正前的旧版本，`git worktree remove --force` + `prune`，约 561 MB）。
- 保留（git 忽略）：`.local/cargo-target` 约 4.0 GB、`next/.local/spike` 约 206 MB、`.local/design`、`.local/ref/rhine-lock`、联调日志。
- 子 agent 报告其 scratchpad 下临时目录（`/private/tmp/claude-501/s0c-scratch` 等）删除被权限拦截，未绕过，留待用户处理。
- 无残留进程（按 pid/pgid 核对）。

## 2026-10-22：S0.5 方向 E 前端改造

- 合同：WORK_PACKAGES「S0.5」（提交 `3da8820`）；设计源与 FRONTEND_STACK §8/§8.1 先行单独提交 `d99890e`。
- 主控：requested 未指定（用户直接对话）；actual claude-opus-5-5（运行时系统信息），effort unknown；Claude Code 当前会话，role=lead。

| 包 | 施工 | 测试 | 审计 | 状态 / 证据 |
| --- | --- | --- | --- | --- |
| S0.5-A 令牌/骨架/组件/三屏 mock | sonnet（Sonnet 5.5）/ medium，原生子 agent，worktree `.local/worktrees/s05`；中途撞会话限额（429），限额重置后续接同一 agent 完成 | haiku（Haiku 5.5）/ medium，施工者派出的原生子 agent，independent=true，新增 77 例（`tests/independent/e-*.test.ts`），发现 2 个缺陷由施工者修复 | 见下方异步审计 | passed（自动验收）：集成版本 `pnpm install --frozen-lockfile`、`typecheck`、`lint`、`build`、`test`（16 文件 217 passed）、`contracts:check` 全部 exit 0；`git diff --check` 通过；源码与 dist 无禁词；`next/desktop`、`next/THIRD_PARTY.md` 与本目录文档以外无改动 |

actual 型号/档位：施工与测试均为 Claude Code 原生子 agent，调度参数（model、effort=medium）被工具接受，无提供方回执 → actual=unknown。

- 集成方式：施工 worktree 内 `git add -A` 限定 `next/desktop`、`next/THIRD_PARTY.md` 生成 binary patch，主 worktree `git apply --check` 后应用（主 worktree 在这些路径无既有改动）。主控随后直接修两处（S05-002、S05-003），修后六条命令重跑全部 exit 0。
- 依赖：新增 `@fontsource/oxanium`、`@fontsource/inter`，移除 `@fontsource/montserrat`；三套字体包 `license` 字段均为 OFL-1.1（主控核对 node_modules），THIRD_PARTY 已登记。
- 删除：`WarningBox`、`InfinityPlaceholder`、`ClockBlock`、`ConnectionBadge`、`design/hud.css`、`features/overview`；对应 HUD 测试 `tests/unit/clock.test.ts`、`tests/independent/{clock-tokens,hud.fault}.test.ts` 删除，其中连接/安全断言（Bearer、token 不入 DOM/storage/URL、重连重新 auth、告警开关失败路径、成功响应不本地切换）由 `e-security`/`e-alert`/`unit/app` 等价覆盖；`src/api/*`、`stores/backend.ts`、`scripts/dev-web.mjs` 未改动。

### 截图对照（主控，`pnpm dev:web` + 真实本地新后端 + 浏览器窗格 1440×960）

截图存于 git 忽略的 `.local/screenshots/s05/`（`tasks-normal`、`tasks-alert`、`work-items`、`ai-session`）。设计稿为画布格式，本地缺 `support.js` 无法渲染，对照依据是设计源码结构与数值，非逐像素比对。

- 告警态：状态栏开关 → 后端广播 `system.alert` → 主区顶部黑色 WARNING 横幅（显示 reason）、出错行转橙并标 FAILED、检查器橙色描边与橙色状态块、导航“任务”角标变 `!`；工作区可点击；关闭后恢复。控制台无错误，dev 日志无 token。
- 与设计稿差异（接受，后续切片处理）：
  1. 不画假红绿灯（合同要求，Tauri Overlay 提供真实按钮）。
  2. 告警横幅不含设计稿的“查看日志/重试/回滚”按钮，页面级动作放在检查器。
  3. 阶段条无独立 skip 状态，并入 pending（合同只列四种）。
  4. 工单页仓库选择为原生 select；内联图片/附件只做文字占位“外部图片已拦截”。
  5. 状态栏无设计稿的“Lark token 6 天”项（合同只列后端/VPN/TG/MCP/待处理）。
  6. 1440 宽时任务名较长的行（admin-console 仅发布）折成两行，行高超过 46px；工单列表标题截断。
- 未测：Tauri 内渲染与截图、1280×800 / 1728×1117、真实浏览器中的键盘走查与 reduced-motion（仅 jsdom 测试与 CSS 规则）、读屏播报、暗色主题（本轮未做）。

### 发现

| finding_id | 级别 | 问题与核实 | 处置 |
| --- | --- | --- | --- |
| S05-001 | major | 仓库根 `.gitignore` 的 `lib/` 规则忽略了 `next/desktop/src/lib/`，S0 的 `src/lib/utils.ts`（Switch 依赖）从未入库；`90c70e3`..`3da8820` 的干净检出 build 失败（施工者在 worktree 发现，主控核实主 worktree 中该文件为被忽略的未跟踪文件） | fixed：`cn` 移至 `src/shared/cn.ts`，不再引用 `@/lib`；施工 worktree（干净检出 + patch）六条命令通过。主 worktree 残留被忽略的 `src/lib/{utils,clock}.ts` 未引用，未删除 |
| S05-002 | major | 柔光装饰绝对定位溢出右下，壳 `overflow:hidden` 仍是可滚动容器；点击状态栏右下控件后整壳被滚动 (160,220)，告警横幅被推出视口（主控截图发现，jsdom 无布局测不到） | fixed（主控）：柔光收进 `inset:0; overflow:clip` 容器，壳改 `overflow:clip`；复测点击后 scroll 为 (0,0)。无自动化回归（需真实布局），列入后续 e2e |
| S05-003 | minor | 任务表状态列文字在 1440 宽下折行 | fixed（主控）：`white-space: nowrap` |
| S05-004 | minor | 导航角标 `aria-label` 挂在无 role 的 span 上，读屏可能不播报；审批条在 window 上监听，页面同时出现多个审批条时会一起响应 | open：S5 接入真实审批时处理 |
| S05-005 | info | `system.hello` 携带非法 alert 时 store 保留上一状态 | deferred：S0 既有语义，S1 复核 |
| S0B-007 | minor | `pnpm test` 依赖已存在的 dist（repo-guard），干净检出须先 build | 仍 open |

### 资源与清理

- dev:web 按 pid 结束，后端与 vite 随之退出（核对无 `toolbox_backend`/`dev-web.mjs` 残留）；浏览器窗格视口已复位。
- 施工 worktree `.local/worktrees/s05`：用户确认后移除（移除前无未提交改动，HEAD 为 `3a5dac1`；`git worktree remove --force` + `prune`，约 311 MB）；patch 与日志在会话 scratchpad。

### 异步交叉审计

| review_id | 审计目标 | 模型/档位 | 状态 | 连续性/结果 |
| --- | --- | --- | --- | --- |
| s05-cross-3a5dac1 / round1 | `3da8820..3a5dac1` 的 `next/desktop`、`next/THIRD_PARTY.md` | codex exec，gpt-6.1-sol / high，sandbox read-only（CLI 头部回执了 model/effort/sandbox） | returned（exit 0） | session `01a16310-6d52-7d10-b3c3-e8d1302038c4`；结论 pass after minor fixes，5 minor、无 blocker/major；审计者离线跑 vitest 217 passed；请求与输出在 `.local/reviews/s05-cross-3a5dac1/` |

主控逐条核实代码，5 项均属实：

| finding_id | 级别 | 问题与核实 | 处置 |
| --- | --- | --- | --- |
| CR-S05-001 | minor | 删除 `hud.fault` 后“未取得连接时点告警开关 → 零请求 + 显示‘后端未连接’”无等价测试（`tests/unit/boot.ts` 固定 `runtime.start()`；`AlertToggle.vue:16` 逻辑仍在） | open：补回测试 |
| CR-S05-002 | minor | 状态栏告警开关根按钮 `h-5`（20px）< 32px，尺寸测试漏查 Switch | open |
| CR-S05-003 | minor | `AppTabs` 只有 `TabsTrigger`，无 tabpanel / `aria-controls` | open |
| CR-S05-004 | minor | AI 会话对话内容写死在 `AiSessionsPage.vue` 模板，未放 `features/ai/mock/` | open |
| CR-S05-005 | minor | `sent`、审批记录未按会话隔离，切换会话后残留上一会话记录 | open |

- 用户 2026-10-22 决定：CR-S05-001..005 保持 open，并入下一个前端切片处理（派工时写进该切片合同；修复后续接同一 Codex 会话 `01a16310-…` 做第二轮复核）。

## 2026-10-22：S1 设置与凭据

- 主控：requested `role: lead`（由上一会话派出）；actual claude-opus-5-5（运行时系统信息），effort unknown；Claude Code 会话。
- 合同：WORK_PACKAGES「# S1」，草案 `11fd8ca`；用户 2026-10-22 确认合同及两项待决（store-id=`toolbox-next`；本轮只导入 ADO PAT），记录于 `92ef9df`。同一提交由主控加入后端依赖 `pyyaml 6.0.3`、`keyring 25.7.0`（`uv add`，既有 195 测试仍全过），施工者无需联网。
- 旧应用核实：只读 `main @ 885d186` 代码；真实配置目录只列文件名，未读内容；未访问 Keychain。
- 主控裁决：S05-005 rejected（理由见 S1-C 合同）；S0B-008 待 S1-C 给出 grep 证据后记 obsolete。

| 包 | 施工 | 测试 | 审计 | 状态 |
| --- | --- | --- | --- | --- |
| S1-A 后端 | codex exec，requested gpt-6.1-sol / medium（两轮，同一 session `01a16325-b180-7292-8e40-cdfb5c46dee7`），sandbox workspace-write，worktree `.local/worktrees/s1a` @ `92ef9df`；actual unknown | codex exec gpt-6-luna / high，session `01a16343-2c78-73d1-b587-25a5d717be8b`，independent=true，两轮共 55 例（`tests/independent/s1/`），未发现产品缺陷 | s1a-cross round1 dispatched | passed（自动验收），集成提交 `814a921` |
| S1-C 前端遗留 | Claude Code 原生子 agent，requested sonnet / medium，worktree `.local/worktrees/s1c` @ `92ef9df`；actual unknown（无提供方回执） | 施工者派 haiku / medium，independent=true，新增 37 例（`tests/independent/s1c-{ui,guard}.test.ts`），未发现缺陷 | s05-cross round2 dispatched | passed（自动验收），集成提交 `fd22770` |
| S1-B 设置页 | Claude Code 原生子 agent，requested sonnet / medium，worktree `.local/worktrees/s1b` @ `c954533`；actual unknown | 施工者派 haiku / medium，independent=true，新增 34 例（`tests/independent/settings-independent.test.ts`），未发现缺陷 | not_dispatched（待 S1-D 后与修复一并审） | passed（自动验收），集成提交 `21957f6` |

请求原文与输出在 git 忽略的 `.local/dispatch/s1a/`。

### S1-C 集成（主控）

- 主控在施工 worktree 与集成后主 worktree 各重跑：`pnpm install --frozen-lockfile`、`typecheck`、`lint`、`rm -rf dist && pnpm test`（19 文件 **269 passed**）、`build`、`guard:dist`（无 dist 时 exit 1，构建后 exit 0）、`contracts:check` 全部符合预期；`git diff --check` 通过。集成方式：限定 `next/desktop` 的 binary patch，`git apply --check` 后应用（主 worktree 该路径无既有改动）。
- 主控审阅 diff 的结论：AppTabs 无插槽用法下 tabpanel 恒 hidden，`aria-controls` 指向空面板——可用但语义偏弱，S1-B 设置页起改用插槽面板；AlertToggle 命中区仅上下扩展（`inset: … 0`），不横向覆盖相邻控件；32px 只做了 CSS 约定检查，无真实布局测量（列入未测）。
- 偏差（已接受）：既有 independent 用例 `repo-guard`、`e-security` 中依赖 dist 的部分移入 `guard:dist`（禁词集合不变，另含 `--denied` 残留检查），src 侧断言保留。
- 测试者观察（记录，不处置）：会话被过滤出列表时对话区仍绑定该会话；`draft` 输入草稿不按会话隔离；UTF-16 产物禁词会漏检（与 grep -I 一致）。

| finding_id | 处置 |
| --- | --- |
| CR-S05-001、002、004、005 | fixed；s05-cross round2 确认 fixed |
| CR-S05-003 | round2：partially_fixed（属实，主控核实：四处页面用法均未传插槽，`aria-controls` 指向空的隐藏面板；两条测试固化了该状态）→ open，并入 S1-B（合同已补“CR-S05-003 收尾”） |
| S0B-007 | fixed（`fd22770`） |
| S0B-008 | obsolete：`grep -rniE "uptime|运行时长" src` 仅命中 `src/api/schema.d.ts` 契约字段；界面不显示运行时长；加了守卫测试 |
| S05-005 | rejected（主控裁决，见 S1-C 合同） |

### s05-cross 第二轮复核

| review_id | 审计目标 | 模型/档位 | 状态 | 连续性/结果 |
| --- | --- | --- | --- | --- |
| s05-cross-3a5dac1 / round2 | `2e0e4c5..fd22770` 的 `next/desktop` | codex exec resume，gpt-6.1-sol / high（CLI 头部回执 model/effort），沙箱继承首轮 read-only | returned（exit 0） | 同一 session `01a16310-6d52-7d10-b3c3-e8d1302038c4`，连续；结论 pass after minor fixes：4 fixed、CR-S05-003 partially_fixed，无新编号；审计者只读跑 251 passed / 1 skipped（排除写临时目录的用例）；请求与输出在 `.local/reviews/s05-cross-3a5dac1/round2-*` |

### S1-A 首轮交回（施工者 partial）

- 施工者报告 partial：核心实现（store、导入、凭据、ADO 接口、出站 HTTP、请求体上限、WS Origin）已写，自测 `verified_by=executor, independent=false`；列出 4 项合同/测试冲突与 README 未更新。用量回执：input 3.65M（cached 3.57M）、output 45k。
- 主控在沙箱外跑全量（worktree，未集成）：**268 passed / 6 failed**，失败仅为 S0 契约精确集合 2 条、`test_fault_http` 预检方法 3 条与超限 1 条，均属合同变更所致；施工者沙箱内无法 bind 端口导致其全量报错，非代码问题。
- 主控裁决写入 WORK_PACKAGES「S1-A 主控裁决」（`8168d59`），续接同一 codex 会话 `01a16325-…` 进行第二轮施工（requested gpt-6.1-sol / medium，沙箱继承 workspace-write）。

### S1-A 集成（主控）

- 施工第二轮 done：裁决 1–7 落实（WORK_PACKAGES「S1-A 主控裁决」）。
- 独立测试：Luna 首轮仅 5 例（凭据泄漏 2、真实端口 3），主控判覆盖不足，续接同一会话补测导入/store/ADO/CORS，第二轮共 55 例；测试者一次失败经核为测试假设错误（预览允许读旧凭据 `get`），未发现产品缺陷。需要端口的 8 例由主控在沙箱外运行通过。
- 主控修正（非逻辑）：测试者 `tests/independent/s1/conftest.py` import 排序（ruff --fix）、`test_s1_store_contracts.py` 一处 `# noqa: ASYNC240`（测试中同步 Path 取 worker 路径）。
- 集成：限定 `next/backend`、`next/contracts` 的 binary patch，`git apply --check` 后应用；同时 `pnpm contracts:gen` 重新生成 `next/desktop/src/api/schema.d.ts`。集成版本：后端 `uv sync --frozen`、`ruff check`、`contracts --check` exit 0，`pytest` **358 passed**；前端 `contracts:check`、`typecheck`、`lint` exit 0，`test` 269 passed；`git diff --check` 通过。
- 主控审阅结论：store 写入流程、导入步骤与残留、凭据入口（keyring 仅生产路径构造，`memory` 仅 `--dev`）、出站 HTTP 边界与合同一致。观察（接受，记录）：① 导入时旧 Keychain 读取若被用户在系统弹窗拒绝会抛错而非返回空，整次导入进入 `failed`（比合同“读不到就跳过”更保守），且导入期间持锁，弹窗未处理时其他写入 5 秒后 `store_busy`；② 内存模式下旧凭据源为空 → S1-B 合同补“dev 假凭据预置”。
- 未测：真实 Keychain（含系统授权弹窗）、真实 ADO、Tauri 内运行。

### S1-A 异步交叉审计

| review_id | 审计目标 | 模型/档位 | 状态 |
| --- | --- | --- | --- |
| s1a-cross-814a921 / round1 | `ec7887b..814a921` 的 `next/backend`、`next/contracts` | Claude Code 原生子 agent，requested opus（Opus 5.5）/ medium，只读；跨厂商（施工为 GPT）；actual unknown | returned：rework required（0 blocker、2 major、4 minor）；凭据值未发现泄露路径；审计者在 `git archive 814a921` 导出副本上跑 358 passed（首次误在 s1b worktree 跑 363 passed，已自行声明不作数），用探针复现 001–004 |

主控逐条核对代码，6 项均属实：

| finding_id | 级别 | 问题 | 处置 |
| --- | --- | --- | --- |
| CR-S1A-001 | major | 测试连接/远端列表的出站请求、导入时读旧 Keychain 都在 store 锁内执行；httpx 读超时非总时长；进程内锁等待无上限 → 设置写入被无界阻塞（审计探针：并发写排队 1.8s） | fixed：锁内 IO 由 S1-D 消除（round2），总时长截止经 CR-S1A-008 / S1-E 修复（round3 确认） |
| CR-S1A-002 | major | 导入 failed 后若用户新建过 library，`decline` 复用“store 为空”前提被永久拒绝；已写入的新 PAT 条目不在凭据页可见 | fixed（S1-D）；round2 确认 |
| CR-S1A-003 | minor | 脱敏器无最小长度：短 PAT（如 1 字符）登记后，任何配置写入因 `contains_secret` 被拒，日志被打碎 | fixed（S1-D）；round2 确认 |
| CR-S1A-004 | minor | collection/project 允许 `.`/`..`，请求可越出 base_url 路径前缀（同 origin，PAT 不跨主机） | fixed（S1-D）；round2 确认 |
| CR-S1A-005 | minor | PAT 元数据/Keychain/base_url 提交顺序导致状态漂移；极端情况下（磁盘写失败）新 PAT 留在旧 origin 下 | fixed（S1-D）；round2 确认 |
| CR-S1A-006 | minor | “日志无 PAT”断言先经脱敏格式化再判断，近似恒真；缺进程级 stderr 检查 | fixed（S1-D）；round2 确认 |

- S1-D 合同已写入 WORK_PACKAGES，排在 S1-B 集成之后（文件重叠）。
- cleanup：审计者在会话 scratchpad 留下 `c814/`（`git archive` 导出副本，无密钥）与 `probe/`（探针脚本）；审计者与主控的删除命令均被权限拦截，未绕过；用户 2026-10-22 手动删除，主控复核已不存在。

### S1-B 集成（主控）

- 集成：限定 `next/desktop`、`next/backend` 的 binary patch（34 文件，无缓存/产物），`git apply --check` 后应用。集成版本：前端 `typecheck`、`lint`、`build`、`guard:dist`、`contracts:check` exit 0，`rm -rf dist && pnpm test` **349 passed**；后端 `ruff` 通过，`pytest` **363 passed**；`git diff --check` 通过；旧应用守卫 `66 passed / 2 skipped`（与基线一致）。
- 主控审阅：PAT 只在 `LibraryPanel` 局部 `ref`，每次带 PAT 的请求后在 `finally` 清空；写操作不用 `useMutation`（避免 variables 进 mutation 缓存）；密码框 `autocomplete=off`；dev 假凭据仅 `--dev`+memory，错误信息不含值。CR-S05-003 收尾：AppTabs `panelId`（`TabsTrigger as-child` 自带 id/aria-controls）+ 插槽面板；两条固化空面板的断言改为页面级断言。
- 主控联调（`pnpm dev:web` 隔离环境，浏览器窗格 1440×960）：预览导入（4 文件存在、library 含 HTTP 明文标签与旧 PAT“已找到”、project、任务规则“由旧 flows 生成任务”、保留段、警告）→ 二次确认 → 执行，revision 0→3；ADO 连接页 library/project 与“当前”标记；凭据页“ADO PAT · 存在 · 导入 · 正常”无值；常规页数据目录为临时目录 `toolbox-dev-web-*`、旧配置目录为仓库 fixture。页面 DOM、localStorage、sessionStorage 均不含假 PAT 字符串。控制台仅有指向端口 55739 的旧 WS 报错（施工者早先会话残留于同一窗格，本次后端端口 58944 无报错）。结束：按 pid SIGTERM `pnpm dev:web`，后端退出、1420 释放、临时数据目录已删。截图未落盘（窗格截图只在会话内）。
- 偏差：施工者报告以**进程名** SIGTERM 回收其 dev:web（违反通用合同“不按进程名批量 kill”）；事后核对无误杀，记录为流程违规，后续派工单重申按 pid 回收。施工者“测试连接后也清空 PAT 输入”比合同更严，接受。
- 观察（未处置）：写操作 busy 时再次点击被静默忽略；busy 被拒时 PAT 输入仍被清空且无提示。列入 S1 收尾的 UX 小项。
- 未测：Tauri 内渲染、Playwright e2e、真实 Keychain/ADO、真实浏览器 axe 扫描与焦点可见性、只读错误态的实机截图（单测覆盖）。

### S1-D 集成（主控）

| 包 | 施工 | 测试 | 状态 |
| --- | --- | --- | --- |
| S1-D 审计修复 | codex exec，requested gpt-6.1-sol / medium，session `01a16365-fd27-7670-9316-e33ab615cf2f`，worktree `.local/worktrees/s1d` @ `1ffc729`；actual unknown | 施工者在 codex 内派原生子 agent `/root/s1d_test`（requested gpt-6-luna / high，actual unknown），只复跑施工者的 17 例回归与 lint，**未补独立用例**——独立性弱，记录 | passed（自动验收），集成提交见下 |

- 修前失败证据：施工者在改产品代码前运行新回归 `tests/test_s1d_regressions.py` → 12 failed（覆盖 001–006 全部六项），修后通过；另 5 例为补充回归（无修前证据）。既有断言改写仅 1 处：`test_s1_settings.py` 日志产物改为原始 `record.getMessage()`/`caplog.text`，formatter 覆盖拆为独立用例。
- 主控沙箱外全量：首次 381 passed / 1 failed——`test_cr006_dev_memory_process_stderr_never_contains_pat` 假设“绑定未监听端口 → 连接被拒（network）”，macOS 实测为 5 秒连接超时（timeout）。属测试环境假设错误：主控将该断言放宽为 `category in {network, timeout}`（stderr 不含 PAT 的核心断言不变）并注释原因。
- 主控审阅：`connection` 在锁内同一快照取 `(library, PAT)`，锁外 `to_thread` 发请求；进程内锁 `wait_for(acquire, 5s)` → `store_busy`；与审计建议一致。
- 集成版本：后端 `ruff`、`contracts --check` 通过，`pytest` **382 passed**；契约无漂移，前端 `contracts:check` 通过（前端代码无改动）。施工者交付报告移至 git 忽略的 `.local/dispatch/s1d/S1-D-REPORT.md`，未入库。
- 注意：PAT 最小长度现为 8，前端设置页未做同样的前置校验，短 PAT 由后端 422 拒绝并显示固定文案（可接受，列入 S1 收尾 UX 小项）。

### S1-A 交叉审计第二轮

| review_id | 审计目标 | 模型/档位 | 状态 | 连续性/结果 |
| --- | --- | --- | --- | --- |
| s1a-cross-814a921 / round2 | `1ffc729..9c94613` 的 `next/backend`（S1-D） | 同一原生子 agent 续接（SendMessage），requested opus / medium；actual unknown | returned | 连续；pass after minor fixes：002–006 fixed，001 partially_fixed，新增 007、008（minor）；审计者在主仓库干净 HEAD `d7f77df` 跑 382 passed、ruff/contracts 通过；探针复现 007、008；确认主控放宽 `test_s1d_process` 分类断言合理；scratchpad 探针已自删 |

主控核对代码，两条新发现属实：

| finding_id | 级别 | 问题 | 处置 |
| --- | --- | --- | --- |
| CR-S1A-007 | minor | `patch_library` 提交失败后无条件恢复旧 PAT；若 `os.replace` 已落盘而回读失败（提交结果不确定），磁盘已是新 base_url，旧 PAT 被绑到新 origin | fixed（S1-E）；round3 确认：失败后重读磁盘，新值保留新 PAT、旧值恢复旧 PAT、读不到则删除并 `pending_delete` |
| CR-S1A-008 | minor | `iter_bytes(chunk_size=65536)` 缓冲至 64 KiB 才产出，慢速滴流时 deadline 与 1 MiB 检查不执行（探针 20.1s 才 timeout）；回归用例首块恰为 64 KiB 未覆盖 | fixed（S1-E）；round3 确认：改 `iter_raw()` 逐原始块检查，回归改为小块滴流 |

info（记录不处置）：导入的短于 8 位旧 PAT 不登记脱敏器（当前无记录路径）；恰为配置 JSON 固定子串的 ≥8 位 PAT 会触发写入闸门（真实 ADO PAT 52 位）；create 回滚时 Keychain `set` 抛错但实际已写入会留下未索引条目；新 service 的 Keychain 读取仍在锁内（其他请求 5s 后 `store_busy`）。

### S1-B 异步交叉审计

| review_id | 审计目标 | 模型/档位 | 状态 | 结果 |
| --- | --- | --- | --- | --- |
| s1b-cross-21957f6 / round1 | `c954533..21957f6` 的 `next/desktop`、`next/backend` | codex exec，gpt-6.1-sol / high（CLI 头部回执），sandbox read-only，session `01a16373-c2c4-7502-860f-e628f2a2d9dc`；跨厂商（施工为 Claude） | returned（exit 0） | rework required：3 major、1 minor；未发现 PAT 进入 Pinia/缓存/存储/URL/console/DOM；CR-S05-003 确认收尾；审计者只读跑 vitest 331 passed / 1 skipped（排除需写入的守卫用例），用内存注入复现 4 项；请求与输出在 `.local/reviews/s1b-cross-21957f6/` |

主控核对代码，4 项属实：

| finding_id | 级别 | 问题 | 处置 |
| --- | --- | --- | --- |
| CR-S1B-001 | major | 编辑草稿只在条目 id 变化时重置；`changed()` 与刷新后的 props 比较、提交用缓存中最新 revision → 外部修改后保存会携带新 revision 把用户未改的旧字段写回，静默覆盖他人修改（library、project 同） | fixed（S1-F）；待审计复核 |
| CR-S1B-002 | major | `pat_origin_change` 确认时重新计算 `changed()` 且地址框仍可编辑 → 确认提示显示 A、实际提交 B，PAT 可被保留到未经确认的 origin | fixed（S1-F）；待审计复核 |
| CR-S1B-003 | major | `writable` 只看缓存的 overview；运行中写请求返回 503 `store_unavailable` 后写入口仍可用 | fixed（S1-F）；待审计复核 |
| CR-S1B-004 | minor | 写响应中的 `warnings`（如 Keychain 删除失败保留 `pending_delete`）被忽略，界面显示“已删除” | fixed（S1-F）；待审计复核 |

### S1-E / S1-F 派工

- 合同：WORK_PACKAGES「S1-E」「S1-F」（`0a0e130`，措辞修正 `597faed`）。两包文件不重叠，并行。
- S1-E 后端（CR-S1A-007、008）：codex exec，requested gpt-6.1-sol / medium，worktree `.local/worktrees/s1e` @ `597faed`；派工单要求其测试子 agent 必须新增独立用例（吸取 S1-D 测试者只复跑的教训）。
- S1-F 前端（CR-S1B-001..004 + UX 小项）：Claude Code 原生子 agent，requested sonnet / medium，worktree `.local/worktrees/s1f` @ `597faed`；测试子 agent haiku / medium。

### S1-E / S1-F 集成（主控）

| 包 | 施工 | 测试 | 状态 |
| --- | --- | --- | --- |
| S1-E 后端 | codex exec，requested gpt-6.1-sol / medium，session `01a16379-bdb3-7162-92e8-64d251ae92b8`；actual unknown | codex 内原生子 agent `/root/s1e_tests`，requested gpt-6-luna / high，actual unknown，independent=true，**新增** 6 例（`tests/independent/s1e/`） | passed，提交 `13bc292` |
| S1-F 前端 | Claude Code 原生子 agent，requested sonnet / medium；actual unknown | haiku / medium，independent=true，新增 27 例（`tests/independent/s1f-independent.test.ts`），发现 2 个缺陷（`storeFault` 仅在同一次 503 刷新中解除）由施工者修复 | passed，提交见下 |

- 修前失败证据：S1-E 两项回归修前 2 failed（CR-S1A-008 用每 0.5 秒 1 字节滴流，修前 21.3 秒才 timeout）；S1-F 回退 src 后自测 16 例中 14 例失败（另 2 例为对照例）。
- 主控审阅：S1-E 重读磁盘后按实际 base_url 决定保留新 PAT/恢复旧 PAT/删除；`iter_bytes()` 不指定块大小逐块检查。S1-F 编辑基线 + 基线 revision、冲突时合并、origin 待确认期间输入禁用并冻结请求体、`store_unavailable` 后刷新且确认 ok 前不可写、warnings 以警告展示、PAT 仅在请求真正发出后清空、前端 PAT ≥8。施工者称“后端未见 PAT 最小 8 校验”有误：`domain/settings.py:73` 已强制（S1-D），前后端一致。
- 既有断言改写（S1-F）：两处冲突提示文案 `已刷新` → `已合并最新内容`（patch 冲突按合同改为合并文案；非 patch 冲突仍为旧文案）。
- 集成版本：后端 `pytest` **390 passed**、ruff/contracts 通过；前端 typecheck/lint/build/guard:dist/contracts:check 通过，`rm -rf dist && pnpm test` **392 passed**；`git diff --check` 通过。
- 未测：真实浏览器/Tauri 渲染、真实后端联调下的多窗口冲突、setActive 带 warnings（无入口）。
- 复核：CR-S1A-007/008 续接 Opus 审计者第三轮、CR-S1B-001..004 续接 codex 审计会话 `01a16373-…` 第二轮，均异步。

### S1 功能清单（对照旧能力 `docs/capabilities/config-and-secrets.md`、`app_ado/ui/code_config_tab.py`）

| 旧能力 | S1 处置 | 说明 |
| --- | --- | --- |
| YAML 配置读写（`~/.config/my-own-script/`） | 改进 | 新独立数据目录 `toolbox-next`，版本化 schema、原子替换、跨进程锁、revision 乐观并发；读取不写盘（D05）；旧配置一次性只读导入，永不回写 |
| flows→tasks 与 ACL task_ids 迁移 | 改进 | 导入时按原始键存在性判定（D04/WP-13），`tasks: []` 不复活、`null`/错误类型阻断；任务编辑在 S3 |
| Library 增删改 + PAT 录入 | 迁移 + 改进 | PAT 只写不读回；改 origin 需重新确认 PAT；被任务引用拒删；删库同时删新 Keychain 条目（旧应用不删） |
| Project 增删改 + “获取 Projects” | 迁移 + 改进 | 远端项目列表只发往所属 origin、不跟随重定向；唯一键改为 (library, collection, project) |
| 当前 library/project | 迁移 | `PUT /api/ado/active` |
| PAT 发现失败弹窗（status/headers/body 截断） | 有意改变 | 只返回固定分类与脱敏文案，不回显远端原文（安全收紧，S1 合同已定） |
| “获取 Collections”（旧应用为桩） | 不迁移 | 旧功能本就未实现 |
| 本地仓库（local_repos）增删改 | **推迟到 S2** | 数据已导入并经 `GET /api/ado` 返回，但 S1 设置页未提供编辑（用户限定的 S1 范围不含）；工单 S2 首个使用它，届时提供 |
| Keychain 其他条目（TG、AI 机器人、VPN/TOTP、dsh、Figma、Lark app secret） | 推迟 | 用户决定：由 S4/S5/S6/S7/S8 各自一次性只读导入 |
| 应用内自更新 | 推迟到 S9 | 不在 S1 范围 |

- 资源所有权：S1 不切换任何单例资源（TG/MCP/Lark 刷新仍归旧应用）。
- 待用户真实环境验收（未测）：真实 Keychain 读取旧条目时的系统授权弹窗与“始终允许”、拒绝授权时导入进入 failed 的体验、真实 ADO 测试连接与远端项目列表、Tauri 内渲染、多窗口并发编辑。

### S1-A 交叉审计第三轮

| review_id | 审计目标 | 模型/档位 | 状态 | 结果 |
| --- | --- | --- | --- | --- |
| s1a-cross-814a921 / round3 | `597faed..13bc292` 的 `next/backend`（S1-E） | 同一原生子 agent 续接，requested opus / medium；actual unknown | returned | **pass**：007、008 fixed（复跑探针：滴流 10.1s timeout；三种提交故障场景旧 PAT 均不落到新 origin），无新发现；390 passed、ruff/contracts 通过；探针已自删。S1-A 审计发现 CR-S1A-001..008 全部闭环 |

info（记录）：提交实际成功但返回 503 时不广播 `settings.changed`（前端 S1-F 收到 `store_unavailable` 会刷新）；持续读盘失败时索引可能残留 `active` 而 PAT 已删（凭据页显示 missing，无泄露）；单个压缩块解压后可能超 1 MiB（既有，需用户自配恶意服务器）。
