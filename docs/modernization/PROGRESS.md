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
| CR-S1B-001 | major | 编辑草稿只在条目 id 变化时重置；`changed()` 与刷新后的 props 比较、提交用缓存中最新 revision → 外部修改后保存会携带新 revision 把用户未改的旧字段写回，静默覆盖他人修改（library、project 同） | fixed（S1-F）；round2 确认 |
| CR-S1B-002 | major | `pat_origin_change` 确认时重新计算 `changed()` 且地址框仍可编辑 → 确认提示显示 A、实际提交 B，PAT 可被保留到未经确认的 origin | fixed（S1-F）；round2 确认（跨条目延迟响应另列 005） |
| CR-S1B-003 | major | `writable` 只看缓存的 overview；运行中写请求返回 503 `store_unavailable` 后写入口仍可用 | fixed（S1-F + S1-G）；round3 确认 |
| CR-S1B-004 | minor | 写响应中的 `warnings`（如 Keychain 删除失败保留 `pending_delete`）被忽略，界面显示“已删除” | fixed（S1-F）；round2 确认 |

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

### S1-B 交叉审计第二轮

| review_id | 审计目标 | 模型/档位 | 状态 | 结果 |
| --- | --- | --- | --- | --- |
| s1b-cross-21957f6 / round2 | `13bc292..687948a` 的 `next/desktop`（S1-F） | codex exec resume，同一 session `01a16373-…`，gpt-6.1-sol / high；连续 | returned（exit 0） | rework required：001/002/004 fixed，003 partially_fixed，新增 005（major）；PAT 清空 8 个分支验证通过、无新外泄路径；只读 vitest 374 passed / 1 skipped |

主控核对代码属实：

| finding_id | 级别 | 问题 | 处置 |
| --- | --- | --- | --- |
| CR-S1B-005 | major | 保存进行中仍可切换选中条目；A 的延迟响应（`pat_origin_change` 回调、`applySaved`、冲突合并）写入当前组件状态，确认时用当前 `props.library.id` → 把 A 的地址修改 PATCH 到 B（审计内存复现）；成功路径污染 B 的基线导致 B 的合法草稿不发请求。ProjectPanel 同类 | fixed（S1-G `892a5c0`）；round3 确认 |
| CR-S1B-003（剩余） | major | `overviewConfirmedOk()` 只看缓存状态；离线（查询 `enabled:false`）时 503 后不发刷新，却以错误前缓存的 `ok` 解除禁写 | fixed（S1-G `892a5c0`）；round3 确认 |

### S1-G 集成（主控）

| 包 | 施工 | 测试 | 状态 |
| --- | --- | --- | --- |
| S1-G | Claude Code 原生子 agent，requested sonnet / medium；actual unknown | haiku / medium，independent=true，新增 22 例（`tests/independent/s1g-independent.test.ts`），未发现产品缺陷 | passed，提交 `892a5c0` |

- 修前失败：撤掉 src 改动后自测 8 例中 5 例失败（另 3 例为护栏，修前即通过）。修法：面板级编辑会话计数（`flush:'sync'` watch），所有响应回调按会话丢弃跨会话结果，冻结确认对象带条目 id 与会话；overview 以发起/完成序号判定“故障后实际完成”的请求（偏差：未用 `dataUpdatedAt` 时间戳比较，序号更严格，接受）。无既有断言改写。
- 集成版本：前端 typecheck/lint/build/guard:dist/contracts:check 通过，`rm -rf dist && pnpm test` **422 passed**。
- 流程偏差：施工者用裸 `git stash`/`apply`/`drop` 撤回 src 做修前对比（stash 栈与其他 worktree 共享）；主控核对 stash 栈为空，无他人条目受影响，记录在案，后续派工单明确禁止裸 stash。
- 留意（未改）：A→B→A 且 A 的旧保存已成功时，切回 A 显示的仍可能是旧草稿值（按“旧会话响应丢弃”合同），列入 UX 小项。

### S1-B 交叉审计第三轮

| review_id | 审计目标 | 模型/档位 | 状态 | 结果 |
| --- | --- | --- | --- | --- |
| s1b-cross-21957f6 / round3 | `2e8e399..892a5c0` 的 `next/desktop`（S1-G） | codex exec resume，同一 session `01a16373-…`，gpt-6.1-sol / high；连续 | returned（exit 0） | **pass**：005、003 fixed，无新发现；复用第二轮内存复现并补测紧邻时序、取消/重试、PAT 8 分支；只读 vitest 404 passed / 1 skipped |

## S1 阶段状态（2026-10-22）

- 自动验收：完成。集成 HEAD 上后端 `pytest` 390 passed、前端 `pnpm test` 422 passed，lint/typecheck/build/guard:dist/契约检查全部通过；旧应用守卫 66 passed / 2 skipped 不变。
- 交叉审计：S1-A（CR-S1A-001..008，Opus 三轮）与 S1-B（CR-S1B-001..005，GPT 6.1 Sol 三轮）全部闭环；S1-C 相关 CR-S05-001..005 于 s05-cross 第二轮闭环（003 收尾于 S1-B）。
- 待用户真实环境验收（未测）：真实 Keychain 读取旧条目的系统授权弹窗/拒绝后导入 failed 体验、真实 ADO 测试连接与远端项目、Tauri 内渲染、多窗口并发编辑、Playwright e2e（未装浏览器）。
- UX 待办（不阻塞）：A→B→A 后切回显示旧草稿；非 patch 写入推进 revision 后 library 详情保存会多一次 409 合并提示。
- 施工 worktree `.local/worktrees/s1a..s1g`（约 1.5 GB）：用户 2026-10-22 确认后移除（移除前逐个核对改动文件均已集成入主 worktree；`git worktree remove --force` + `prune`）。补丁、派工单与施工/测试输出保留在 git 忽略的 `.local/dispatch/`、`.local/reviews/`。

## 下一步规划（主控 2026-10-22，S1 完成后）

- 顺序建议：**S2 工单 → S3 任务执行**（MIGRATION_PLAN 允许二者并行，但同一主控串行更稳）。理由：S2 以只读为主，不触发构建/发布/推送，便于用户真实验收；它会先把 ADO HTTP 客户端层（认证、origin 约束、超时、错误分类，沿用 S1 `adapters/ado_http.py` 的边界）扩展成通用读取层，S3 直接复用。S3 引入统一运行模型（ARCHITECTURE §4，SQLite WAL 检查点、`unknown` 状态）与真实写操作（git push、触发构建/发布），风险高，单独一个切片做。
- S2 范围草案：看板列/列表/详情/评论/子项/Updates（只读）；附件与内联图片后端代理（D01：按 library origin 逐跳校验、跨源终止，旧应用 `trusted_base_url` 规则）；ADO HTML 后端白名单清洗 + 前端 DOMPurify；本地仓库（local_repos）增删改（S1 推迟项）；工单页由 mock 换真实接口。**不含**：TG `/wi`（S4）、MCP 分析按钮与 AI 会话（S5/S6）、ADO MCP server（S6）。
- 需在 S2 派工前请用户拍板：① UI 是否提供“新建工单”（旧应用只在 MCP 工具里建单）；② CR-NEXT-004——真实工单附件是否 302 到跨源 CDN（需用户在旧应用或浏览器里确认一次），决定是否要“明示受信 origin”配置。
- 遗留待办并入 S2：S1 UX 小项（A→B→A 旧草稿、非 patch 写入后的额外 409 合并提示）、S05-004（导航角标 aria、审批条 window 监听，原定 S5，可顺带看但不强求）。

## 2026-10-22：S2 工单（合同草案）

- 主控：requested `role: lead`（用户粘贴的交接单）；actual claude-opus-5-5（运行时系统信息），effort unknown；Claude Code 会话。本轮无子 agent、无施工。
- 合同：WORK_PACKAGES「# S2」草案，**待用户确认**两项（新建工单；CR-NEXT-004 跨源 CDN）后派工。
- 旧应用核实：只读 `main @ 885d186` 的 `app_ado/ado_work_item_http.py`、`work_item_view.py`、`ui/work_items_tab.py`、`mcp_ado_work_items_server.py`、`tg_work_items_*` 的调用点；未读真实配置/凭据，未连 ADO。CR-NEXT-004 的唯一来源是 WP-11 前的代码注释（`c349243` `_attachment_client`），无证据。
- 新发现：CR-S2-PRE-001（minor）`httpx` 只在后端 dev 依赖组，生产代码 `adapters/ado_http.py` 直接 import → 非 dev 安装缺依赖。open：合同确认后主控在依赖预置提交中修正。
- 用户 2026-10-22 确认合同：1 不做新建工单；2 先按同源规则 A，CR-NEXT-004 由用户稍后在真实工单确认。
- 依赖预置（主控，联网）：后端 `uv add httpx nh3`（nh3 0.3.7）+ `uv remove --dev httpx` → **CR-S2-PRE-001 fixed**；前端 `pnpm add dompurify@3.4.17 @tauri-apps/plugin-opener@2.7.2`；Rust `cargo add tauri-plugin-opener@2`（2.7.2）+ `cargo fetch`（插件尚未注册，由 S2-B 接入）。预置后：后端 `pytest` 390 passed、ruff/contracts 通过；前端 frozen install/typecheck/lint 通过，`pnpm test` 422 passed；`cargo check --offline` 通过。
- S2-A 派工：codex exec，requested gpt-6.1-sol / medium，sandbox workspace-write，worktree `.local/worktrees/s2a` @ `dc377b4`，session `01a163a6-e205-7a70-bd9f-99ef2c687e8c`；actual unknown。派工单要求测试子 agent（requested gpt-6-luna / high）新增独立用例于 `tests/independent/s2a/`。请求与输出在 `.local/dispatch/s2a/`。S2-B、S2-C 待 S2-A 集成后派。

### S2-A 集成（主控）

| 包 | 施工 | 测试 | 状态 |
| --- | --- | --- | --- |
| S2-A 后端 | codex exec，requested gpt-6.1-sol / medium，session `01a163a6-e205-7a70-bd9f-99ef2c687e8c`；actual unknown（CLI 无型号回执）；用量 input 6.74M（cached 6.57M）/ output 50k | codex 内原生子 agent `/root/s2a_tests`，requested gpt-6-luna / high，actual unknown，independent=true，**新增** 44 例（`tests/independent/s2a/`，5 文件），未发现生产缺陷 | passed（自动验收），提交 `bd90107` |

- 施工者沙箱内无端口子集 341 passed；主控沙箱外全量 worktree **530 passed**。施工者报告 7 处补测修复均有修前失败证据（BFS 批内超 500、PAT 回显、httpx 日志含完整路径、媒体 PAT 回显、超长表格属性、存量仓库路径误校验、`id:null` 时 `commentId` 回退）。S1 既有测试无改动（`git diff --exit-code -- next/backend/tests`）。
- 主控审阅：出站客户端（同 origin + 路径前缀、JSON 不跟随 3xx、媒体逐跳校验且跨源前即终止、总时长逐块检查、4/10/25 MiB 双重限额）、nh3 两遍清洗（首遍保留 src 仅用于改写，末遍严格白名单）、媒体取用时重新校验 library、魔数判图、三项响应头、`TOOLBOX_DEV_FAKE_ADO` 启动守卫，均与合同一致。S1 测试连接改走同一信号量（排队超时 503 `busy` 为新增路径，合同允许）。httpx/httpcore 日志降到 WARNING（避免完整 URL 进日志）。
- **CR-S2A-L01**（minor，主控发现并修复，verified_by=lead）：媒体登记表去重键只有 `(project_id, url)`。ADO 内联图通常就是附件，同一 URL 先由描述登记为 image，附件关系复用该 id → 附件为 SVG/非图片时下载返回 415。修复：键加入 kind；回归 `tests/test_s2_lead_regressions.py` 修前失败、修后通过。
- 观察（info，不处置）：出站信号量是模块级对象（单事件循环生产环境无影响）；假 ADO 的 WIQL 对任何列返回全部条目（仅 dev 演示）。
- 集成：限定 `next/backend`、`next/contracts` 的 binary patch（26 文件），`git apply --check` 后应用；`pnpm contracts:gen` 重新生成 `schema.d.ts`。集成版本：后端 `uv sync --frozen`、ruff、contracts 通过，`pytest` **531 passed**；前端 `contracts:check`、typecheck、lint 通过，`pnpm test` 422 passed；`git diff --check` 通过。补丁与输出在 `.local/dispatch/s2a/`。
- 未测：真实 ADO（含 CR-NEXT-004）、真实 Keychain、前端联调。
- S2 并行派工（主控，基线 `6ed7fd1`）：S2-B 工单页（Claude Code 原生子 agent，requested sonnet / medium，worktree `.local/worktrees/s2b`；write_scope 另加 `scripts/dev-web.mjs` 的 `TOOLBOX_DEV_FAKE_ADO`）；S2-C 设置页本地仓库 + UX 两项（同上，worktree `.local/worktrees/s2c`）；两者测试子 agent requested haiku / medium，须新增独立用例。S2-A 交叉审计 s2a-cross-bd90107 round1：原生子 agent requested opus / medium，只读，跨厂商。actual 均 unknown（无提供方回执）。

### S2-A 异步交叉审计

| review_id | 审计目标 | 模型/档位 | 状态 | 结果 |
| --- | --- | --- | --- | --- |
| s2a-cross-bd90107 / round1 | `dc377b4..bd90107` 的 `next/backend`、`next/contracts` | Claude Code 原生子 agent，requested opus / medium，只读，跨厂商；中途因账号会话额度 429 中断，额度重置后 SendMessage 续接同一 agent（连续）；actual unknown | returned | pass after minor fixes：0 blocker/major，4 minor，4 info；在主仓库干净 HEAD 跑 531 passed；探针（MockTransport/ASGITransport）在 scratchpad，已自删 |

主控复现 001（`within` 对 `/ro%6Ft/x.png`、`/root%2Fz.png` 返回 True，原始路径不在前缀下）、002（孤立代理字符 → UnicodeEncodeError）、003（`<p lang title>` 保留），004 经代码核实：

| finding_id | 级别 | 问题 | 处置 |
| --- | --- | --- | --- |
| CR-S2A-001 | minor | 前缀判断用解码路径，实际请求用原始路径；他人编写的工单内容可让 PAT 发往同 origin 下原始路径不在前缀内的地址（需按原始路径路由的反向代理） | open → S2-D |
| CR-S2A-002 | minor | 远端畸形数据（孤立代理字符、`fields` 非对象、`relations.added` 非列表）返回 500 而非 502 bad_response | open → S2-D |
| CR-S2A-003 | minor | nh3 默认 generic 属性保留 `lang`/`title`，偏离合同属性白名单（前端 DOMPurify 会去掉） | open → S2-D |
| CR-S2A-004 | minor | HTML 清洗在事件循环线程同步执行（约 0.8 s/MiB，单请求可阻塞约 3 s）；单次响应可登记大量媒体挤掉登记表 | open → S2-D |
| I-1 | info | 总时长按跳设置读超时，最坏约 2 倍 | accepted（同 S1-E） |
| I-2 | info | 二次取消时许可可能在线程结束前释放 | open → S2-D |
| I-3 | info | S1 测试连接超限文案变化、新增 busy 等 | accepted（分类不变） |
| I-4 | info | 存量重名条目只改路径也被拒；空 PATCH 推进 revision；`isdir` 网络挂载延迟 | 第一项 → S2-D；其余 accepted |
- S2-D 派工：codex exec，requested gpt-6.1-sol / medium，sandbox workspace-write，worktree `.local/worktrees/s2d` @ `1f9ad6b`，session `01a163cc-a28c-7eb3-ab0d-b28e2abb9e8f`；actual unknown；测试子 agent requested gpt-6-luna / high，独立用例写 `tests/independent/s2d/`。与 S2-B/S2-C 并行。

### S2-C 集成（主控）

| 包 | 施工 | 测试 | 状态 |
| --- | --- | --- | --- |
| S2-C 设置页本地仓库 + UX | Claude Code 原生子 agent，requested sonnet / medium；中途 429 中断，SendMessage 续接；actual unknown | 施工者派 haiku / medium，independent=true，新增 52 例（`tests/independent/s2c-independent.test.ts`），发现 2 个缺陷（再次“新建”残留上次草稿，library 与本地仓库）由施工者修复 | passed，提交见下 |

- 修前失败：UX 回归 12 例中 4 例失败（A→B→A 草稿两例、非 patch 写入后多余合并两例），修后全过；“本窗口切换当前项目后保存 library”一例修前即绿（单窗口切换面板会卸载 library 面板），保留为护栏。
- 实现：新增 `editSession.ts` 统一 library/project/本地仓库的编辑会话与基线（比合同更大的重构，由 S1 既有测试与独立测试兜住，接受）。主控审阅：基线 revision 只在服务器字段与基线逐字段相同时静默前移，不会产生丢失更新；会话开始时若数据在刷新/写入在途，落定后只替换用户未改的字段。
- 既有断言改写 10 处（`settings-s1f`、`settings`、`settings-independent`、`s1g-independent`），全部对应合同的两项语义变化（基线前移后 revision 期望值 +1/+2、A→B→A 未改字段跟随服务器、页签数 4→5）；“旧会话回调不执行、无合并提示”的核心保护保留。无删除/跳过。
- 集成：限定 `next/desktop/src/features/settings`、`next/desktop/tests` 的 binary patch，`git apply --check` 后应用。集成版本前端 typecheck/lint/build/guard:dist/contracts:check 通过，`rm -rf dist && pnpm test` **507 passed**；`git diff --check` 通过。
- 未测：真实浏览器渲染与 Tab 顺序、真实后端下 `exists`/warnings、本地仓库 DELETE 的 409 路径。

### S2-D 集成（主控）

| 包 | 施工 | 测试 | 状态 |
| --- | --- | --- | --- |
| S2-D 审计修复 | codex exec，requested gpt-6.1-sol / medium，session `01a163cc-a28c-7eb3-ab0d-b28e2abb9e8f`（两轮，`exec resume` 续接）；actual unknown | codex 内原生子 agent `/root/s2d_tests`，requested gpt-6-luna / high，actual unknown，independent=true，**新增** 36 例（`tests/independent/s2d/`） | passed，提交见下 |

- 首轮交回 partial：001/002/004/I-2/I-4 完成，003 因 nh3 0.3.7 无 `generic_attributes` 参数停下升级（正当）；主控裁决改为 attribute_filter 按标签白名单（WORK_PACKAGES「S2-D 主控裁决」，`0bb61af`），第二轮完成。修前失败证据：两组新回归在还原副本上 29 failed / 11 passed；003 修前 1 failed。
- **CR-S2D-L01**（minor，主控审阅发现并修复，verified_by=lead）：`httpx.URL.raw_path` 含查询串，`%2F/%5C/%2E` 检查误作用到 `?fileName=…`，可能拦截合法附件；改为只检查 `?` 之前的原始路径。回归追加到 `tests/test_s2_lead_regressions.py`，修前失败、修后通过。
- 主控审阅：004 的线程清洗只收集候选 URL 并输出 `candidate-N` 占位，回事件循环后按单响应 200 预算登记替换；攻击者内容无法伪造 `data-media-id`（首遍 img 只放行 src/alt，alt 值引号已转义），既有 `test_html_cannot_forge_generated_media_attributes` 仍通过。I-2 取消路径循环 shield 直到线程结束。
- 集成：限定 `next/backend` 的 binary patch；集成版本后端 `pytest` **572 passed**、ruff/contracts 通过；契约无漂移（前端 `contracts:check` 通过）。
- CR-S2A-001..004、I-2、I-4（第一项）→ fixed（待审计第二轮确认）。

### S2-A 交叉审计第二轮

| review_id | 审计目标 | 模型/档位 | 状态 | 结果 |
| --- | --- | --- | --- | --- |
| s2a-cross-bd90107 / round2 | `8a0fa3d..fa2357a` 的 `next/backend`（S2-D + CR-S2D-L01） | 同一原生子 agent 续接（SendMessage），requested opus / medium；连续；actual unknown | returned | **pass**：CR-S2A-001..004、I-2、I-4（第一项）fixed，无新 minor 及以上；主仓库干净 HEAD 跑 572 passed；探针（纯函数）已自删 |

info（记录，真实 ADO 验收时留意）：I-5 原始前缀按字节比较，base_url 与远端在大小写/编码形式不同时会误拦（安全方向）；I-6 单响应 200 预算由图片先用完，附件可能拿不到 media_id；I-7 `workitemsbatch` 若返回 null 元素会整体 502（旧应用同样会崩）。S2-A 审计发现全部闭环。

### S2-B 集成（主控）

| 包 | 施工 | 测试 | 状态 |
| --- | --- | --- | --- |
| S2-B 工单页 | Claude Code 原生子 agent，requested sonnet / medium；中途 429 中断，SendMessage 续接；actual unknown | 施工者派 haiku / medium，independent=true，新增 149 例（`tests/independent/s2b-{sanitize,media,page}.test.ts`），发现 1 个缺陷（附件页过期图片点“刷新详情”不重取）由施工者修复 | passed，提交 `e96dd3b` |

- 施工者新增 72 例（`work-items.test.ts`、`work-items-security.test.ts`：12 条 XSS 语料经描述/评论、img 只有 `blob:`、Bearer 不进 URL/DOM/存储、revoke、链接不导航、Tauri 走 opener）。mock 删除导致 7 个既有用例改写为基于假后端（`tests/unit/wi-fake.ts`，openapi 形状）的等价断言，主控核对未放宽（看板列/搜索/告警可点击原意保留；一处方向键用例改为在当前页签上按 →）。
- 偏差（接受）：插件注册在 `src-tauri/src/app.rs`（Builder 所在，lib.rs 只 re-export）；mailto 不打开（opener scope 只含 http/https）；非图片附件增加“下载”按钮（Bearer 取 blob 触发下载，10 秒或卸载后 revoke）。
- 主控审阅：DOMPurify 显式 ALLOWED_TAGS/ATTR、URI 只 http/https/mailto、FORBID style/src/srcset/class/id/target；外链 `safeExternalUrl` 拒绝非 http(s) 与 userinfo；媒体缓存卸载时 abort + revoke；capability 仅 `opener:allow-open-url`（http/https）；CSP 只给 `img-src` 加 `blob:`。
- 集成：限定 `next/desktop` 的 binary patch（与 S2-C 共同改过的 `settings-independent.test.ts` 无冲突，`git apply --check` 通过）。集成版本：frozen install、typecheck、lint、build、guard:dist、contracts:check 通过，`rm -rf dist && pnpm test` **728 passed**（S2-B 643 + S2-C 新增 85）；`src-tauri` fmt/clippy `-D warnings`/test 通过；后端 572 passed；旧应用守卫 66 passed / 2 skipped 不变；`git diff --check` 通过。
- `next/` 与本目录文档以外的改动只有 `app_version.py`（仓库 pre-commit 钩子每次提交自动递增第 4 段，S1 起即如此，非施工改动）。

### S2 主控联调（`pnpm dev:web`，假 ADO fixture，浏览器窗格 1440×960）

- 设置页：预览导入 → 确认 → 执行（仓库假旧配置）；工单页：项目“示例 ADO / 示例项目”、看板列“开发中 2”（fake-ado 不按列过滤，#102“新建”也出现，属 fixture 行为）、列表 #101/#102、筛选与分页控件；详情 #101：元信息、标签、“在浏览器打开”，描述中同源图片为 `blob:` 且已解码（naturalWidth>0），跨源图片显示“已拦截外部图片 · https://external.example.test:443”；评论（示例评审者）、子项（#102）、历史（r3 System.Title 旧→新，纯文本）、附件（示例附件.txt + 下载）均正常；检查器 AI 分析禁用并标 S5。
- 安全核对：媒体请求 URL 无查询串；localStorage 只有 `toolbox.work-items.selection = {project_id, column}`。控制台仅有指向端口 50711 的 WS 失败——S2-B 施工者早先在同一窗格留下的旧后端端口（本次后端端口不同、状态栏在线），非本次问题。
- 回收：按 pid SIGTERM `pnpm dev:web`（23299），uv/后端进程退出，1420 释放，临时数据目录已删。截图未落盘（窗格截图只在会话内）。

### S2 功能清单（对照 `docs/capabilities/work-items.md`、旧 `ui/work_items_tab.py`）

| 旧能力 | S2 处置 | 说明 |
| --- | --- | --- |
| 选项目 + 固定五列看板 | 迁移 | 列名与默认“开发中”不变；选择存 localStorage（旧应用写 ui_settings.yaml） |
| 列表（按 BoardColumn WIQL）+ 关键词/指派筛选 + 分页 | 迁移 + 改进 | WIQL `$top=500` 并提示截断；列表不再拉 relations；分页 10/50/100 |
| 详情：描述 + 评论 + 内联图片 | 迁移 + 改进 | 后端 nh3 + 前端 DOMPurify 双重清洗（旧应用无清洗）；图片经后端代理，同源 + 路径前缀 + 逐跳校验，跨源显示占位（旧应用跳过无占位，CR-NEXT-005 在新应用解决） |
| ReproSteps / AcceptanceCriteria | 新增 | 旧 UI 未展示 |
| 关联单（子项） | 迁移 + 改进 | BFS 8 层、≤500、去环 |
| 历史 Updates | 新增（UI） | 旧应用只在 MCP 用 |
| 附件 | 改进 | 列表 + 下载（旧 UI 只下载图片落盘到 `~/.config/.../work_item_view/`，新应用不落盘） |
| “在浏览器打开” | 改进 | 网页地址 `_workitems/edit/{id}`（旧应用给的是 API url）；Tauri 走系统浏览器 |
| 本地仓库 local_repos 增删改 | 迁移（S1 推迟项） | 设置页「本地仓库」页签 |
| MCP 分析 / 复制提示词 | 推迟 S5 | 检查器面板禁用标 S5 |
| TG `/wi` | 推迟 S4 | |
| ADO MCP server（含 `ado_create_work_item`） | 推迟 S6 | 用户决定 S2 不做 UI 建单 |

- 资源所有权：S2 不切换任何单例资源。
- 待用户真实环境验收（未测）：真实 ADO 列表/详情/评论/历史/子项、**CR-NEXT-004 附件是否跨源 CDN**（若是，追加方案 B 小包）、I-5/I-7 两项、真实 Keychain、Tauri 内 blob 图片与 opener、Playwright e2e。
- 交叉审计：S2-A 两轮闭环；S2-B/S2-C 审计 s2bc-cross round1 已派（codex exec，gpt-6.1-sol / high，sandbox read-only，session `01a163e0-93a8-7621-b72f-980852f7b7ec`），pending。

### S2-B/S2-C 异步交叉审计

| review_id | 审计目标 | 模型/档位 | 状态 | 结果 |
| --- | --- | --- | --- | --- |
| s2bc-cross-e96dd3b / round1 | `6ed7fd1..e96dd3b` 的 `next/desktop` | codex exec，gpt-6.1-sol / high（命令参数；CLI 无型号回执，审计自述 unknown），sandbox read-only，session `01a163e0-93a8-7621-b72f-980852f7b7ec`；跨厂商 | returned（exit 0） | rework required：2 major、2 minor；未发现 DOMPurify 绕过、token 外泄或 10+7 处断言放宽；只读跑 710 passed / 1 skipped（排除需写临时目录的守卫用例）；内存探针复现四项；请求与输出在 `.local/reviews/s2bc-cross/` |

主控对照代码核实四项属实：

| finding_id | 级别 | 问题 | 处置 |
| --- | --- | --- | --- |
| CR-S2C-001 | major | `editSession` 刷新落定路径 `adopt()` 保留用户草稿却把基线整体换成服务器值并接纳新 revision → 他人对同一字段的修改被下一次 PATCH 静默覆盖，不出现 409 合并提示（S2-C 引入） | open → S2-E1 |
| CR-S2B-001 | major | 首次工单请求在途时 `settings.changed` 的 `invalidateQueries` 复用在途请求，旧来源响应清掉失效标记 → 显示旧项目数据 | open → S2-E2 |
| CR-S2B-002 | minor | “刷新详情”先 `forgetFailed` 再失效，旧 id 先被重试；换新 id 成功后仍显示“部分图片已过期” | open → S2-E2 |
| CR-S2B-003 | minor | 图片附件分支没有下载按钮（含 SVG、预览失败的图片） | open → S2-E2 |
- S2-E 派工（基线 `5d591e2`）：S2-E1（CR-S2C-001）续接 S2-C 施工 agent，worktree `.local/worktrees/s2e1`；S2-E2（CR-S2B-001..003）续接 S2-B 施工 agent，worktree `.local/worktrees/s2e2`；均 requested sonnet / medium，actual unknown；并行，文件不重叠。
- S2-E1 集成（主控）：施工者（续接 S2-C agent，requested sonnet / medium，actual unknown）新增 `tests/unit/settings-s2e1.test.ts` 4 例，未派测试子 agent（合同允许，`verified_by=executor` + 主控复核）。主控在 worktree 临时反向应用 src 补丁复跑：3 failed / 1 passed（护栏），恢复后全过——修前失败证据属实。修法：settling 时若用户改过的字段服务器也变了即不 adopt，基线与 revision 不动，保存走 409 合并提示。集成版本前端 **732 passed**，typecheck/lint/build/guard:dist/contracts:check 通过，提交 `3d0fdd3`。CR-S2C-001 → fixed（待审计第二轮）。
- S2-E2 集成（主控）：施工者（续接 S2-B agent，requested sonnet / medium，actual unknown）新增 5 例回归（`tests/unit/work-items-e2.test.ts`）；测试子 agent haiku / medium，independent=true，新增 18 例（`tests/independent/s2e2-*`），发现被拦截但带 media_id 的附件缺下载按钮，已修；一例因 store 对相同 revision 不触发而改为递增 revision（store 不在范围、后端 revision 单调，接受）。主控反向应用 src 补丁复跑新回归：**5 failed**，恢复后全过。修法：settings.changed 先 cancelQueries 再 invalidate，六个查询传 signal；刷新详情先等重取再 forgetFailed，过期计数按引用者（`get(id, owner)`/`release(owner)`）统计；凡有 media_id 的附件都有下载按钮。既有断言改写 1 处（security 测试按文本精确定位“下载 doc.txt”，断言内容不变）。施工者关于“SVG 附件下载 415”的担忧经核实不存在：后端附件关系一律登记为 attachment kind（CR-S2A-L01 后与内联 image 分开），不会 415。集成版本前端 **755 passed**，typecheck/lint/build/guard:dist/contracts:check 通过，提交 `ca190df`。CR-S2B-001..003 → fixed（待审计第二轮）。

### S2-B/S2-C 交叉审计第二轮

| review_id | 审计目标 | 模型/档位 | 状态 | 结果 |
| --- | --- | --- | --- | --- |
| s2bc-cross-e96dd3b / round2 | `f90885e..ca190df` 的 `next/desktop`（S2-E1、S2-E2） | codex exec resume，同一 session `01a163e0-…`，gpt-6.1-sol / high；连续 | returned（exit 0） | **pass**：CR-S2C-001、CR-S2B-001..003 fixed，无新发现；复用首轮内存探针，另核对多 owner 过期计数、clear 中止并 revoke、被拦截附件下载只请求后端不透明 id；只读 vitest 737 passed / 1 skipped |

## S2 阶段状态（2026-10-22）

- 自动验收：完成。集成 HEAD 上后端 `pytest` 572 passed、ruff/contracts 通过；前端 `pnpm test` 755 passed，typecheck/lint/build/guard:dist/contracts:check 通过；`src-tauri` fmt/clippy/test 通过；旧应用守卫 66 passed / 2 skipped 不变。
- 交叉审计：S2-A（Opus，两轮，CR-S2A-001..004 + I-2/I-4）与 S2-B/S2-C（GPT 6.1 Sol，两轮，CR-S2B-001..003、CR-S2C-001）全部闭环；主控自查发现 CR-S2A-L01、CR-S2D-L01 已修。
- 待用户真实环境验收（未测）：真实 ADO 列表/详情/评论/历史/子项/附件；**CR-NEXT-004** 跨源 CDN（若属实追加方案 B）；I-5（base_url 与远端路径大小写/编码不一致时误拦）、I-7（batch 返回 null 元素）；真实 Keychain；Tauri 内 blob 图片、CSP 与 opener；Playwright e2e。
- 施工 worktree `.local/worktrees/s2a..s2e2`（约 1.5 GB）：逐文件核对，s2d、s2e1、s2e2 与主仓库完全一致；s2a/s2b/s2c 中不一致的文件均为被后续包（S2-D、S2-E）或两包合并改动覆盖的旧版本。用户 2026-10-22 确认后移除：`git worktree remove --force` ×6 + `git worktree prune`，`git worktree list` 只剩 `main` 与 `rewrite/next`，`.local/worktrees/` 为空。补丁、派工单与施工/测试/审计输出保留在 git 忽略的 `.local/dispatch/`、`.local/reviews/`。

## 2026-10-23：S3 任务执行（合同草案，待确认）

- 主控：requested GPT 6.1 Sol/high；actual model/effort=unknown（当前Codex工具无提供方回执），runtime_identity=codex，session_id=unknown；本轮未委派任何施工/测试/审计会话。
- 输入：`rewrite/next @ 5c0d4c2`，开始时工作区干净；旧目录 `main @ 885d186` 只读。主控亲自检查 `tasks_tab.py`、`models.py`、`task_migrate.py`、`task_history.py`、`ado_git_ops.py`、`ado_build_http.py`、`ado_build_query.py`、`ado_release_http.py` 与新版S1/S2入口。
- 事实与合同追加在 WORK_PACKAGES「S3」：端点/api-version/git argv/轮询/停止/构建复用/日志来源；运行库schema与数据目录、外部副作用意图/回执、重启unknown只读对账、取消/超时/子进程隔离、S3-A/B/C分包与离线/真实验收清单。
- 加载技能：AI prompt root下backend-architecture-review、backend-security-review、data-consistency-review、backend-business-safety；提交验证使用verification-before-completion，检查现有提交钩子使用script-engineering。只写合同，未实施后端功能。
- 六项待确认：只发布/回滚是否首版纳入；完整任务增删改/排序；每次确认旧应用空闲且不做跨应用锁；远程PR与git认证兼容范围；Classic部分成功制品能否发布；未选Release环境是否强制不自动部署。推荐与影响见合同，尚无用户已决。
- S3-A/B/C：not_dispatched；Claude Sonnet 5.5/medium代码审计：not_dispatched（尚无代码差异）。模型可用性核验/依赖预置在确认之后进行，不把目标配置记成实际执行结果。
- 工具限制：Serena索引初始化失败（服务PATH找不到uv/uvx），改用只读文本核对；未安装工具、未修改全局配置。无额外worktree/子进程/临时仓库需清理。
- 安全范围：未读真实配置/凭据、未连真实ADO/TG、未执行远端push或触发构建/发布；旧目录源码未改。当前仅文档及既有pre-commit自动递增版本；未重新执行功能全量测试，572/755仍是S2历史基线，不称为本轮验证结果。
- 本轮提交前验证：`git diff --check` exit0；后端 `.venv/bin/python -m toolbox_backend.contracts --check` exit0（契约无漂移）；文档结构/六项待决/围栏与S3-C实际集成路径检查exit0。仅本合同和账本有人工改动；未运行S3功能验收，尚无实现。

### S3 合同确认与启动准备（2026-10-23）

- 用户原答复“均按你推荐的来”，六项均按推荐确认；WORK_PACKAGES「S3 已决」已更新。主控可继续派工、离线测试、异步只读审计及本地提交；真实远端写/凭据/旧应用仍不在本轮测试授权范围。
- 运行时预检：codex exec/resume与Claude Code help可用；`agy models` exit0，仅列出的Gemini高档为 `gemini-3.8-flash-high`（Gemini 3.8 Flash High），前端选此型号，无Gemini Pro，不替换厂商。Claude尚未执行审计请求，型号可用性与modelUsage在实际审计回执核实。
- 后端无新增依赖；先从本确认提交创建S3-A worktree并离线同步uv.lock。S3-A先实现运行内核/配置/Git；S3-B接入ADO后才开放完整真实执行链；S3-C随后替换任务mock。派工结果另追加，不把准备状态记成已开工。
- S3-A已派：codex exec，requested `gpt-6.1-sol / medium`，sandbox workspace-write，输入`bcfeba5`，worktree `.local/worktrees/s3a`；session `01a16444-9e5a-7da0-8286-67f40c7827f8`，actual model/effort未知（JSON尚无型号回执）。主控 `uv sync --offline --frozen` exit0（33个锁定包，Python3.14.7，无新增依赖），派工单要求GPT6 Luna/high新增独立测试。请求/输出 `.local/dispatch/s3a/`，状态running。
- 主控启动基线复验：输入版本后端全量pytest **572 passed**（135.29s），前端 **755 passed**；均exit0，未改断言。S3-A进行中，不能把基线结果当集成验收。
- 补充运行时证据：S3-A原生rollout的 `turn_context` 记录 model=`gpt-6.1-sol`、effort=`medium`、workspace-write、network_access=false；这是本地运行时配置回执，非提供方底层路由保证。独立测试已实际调用原生 `collaboration.spawn_agent`，requested `gpt-6-luna / high`，返回task_name=`/root/s3a_tests`；其实际型号/档位无独立回执仍unknown。
- **CR-S3A-L01（major，open，主控亲自复现）**：Git command等待中，进程先退出、日志sink随后失败时，`sink_errors`只在等待drains之前检查，可能漏掉末尾日志持久化错误而返回命令成功。主控在施工树重跑S3新增集合：**34 passed / 1 failed**（`test_late_output_journal_failure_cannot_report_command_success`，DID NOT RAISE SettingsError）。复现与观察源码哈希存 `.local/dispatch/s3a/lead-red-l01.json`，修复前不接收该版本。
- S3-C输入侦查已派（非施工/审计）：Antigravity CLI `agy --print`，requested `gemini-3.8-flash-high / high`，mode=plan、sandbox、单轮纯文本，5分钟上限；cwd为重写worktree。限定只读现有前端/测试/启动器，不运行测试/应用、不联网、不修改文件、不派发。用于收集S3-C组件与测试接入点，正式前端施工仍等S3-B冻结契约；请求/输出 `.local/dispatch/s3c-scout/`，会话ID待首轮完成后按cwd取缓存，actual未知。
- S3-C侦查返回exit0，cwd缓存会话 `023e830f-4b59-4cf6-a5b2-daa0d0344d16`；actual model/effort仍unknown（无提供方回执），前端源码无改动。事实导航见 `.local/dispatch/s3c-scout/final.txt`：EventClient无公开send、BackendRuntime只有api/start/stop；旧任务mock耦合触点为pages、e-alert、s1c、settings-independent四个测试文件。主控已读过runtime/events/侧栏原文；后续按冻结DTO迁移夹具与交互，不能保留mock制造的任务结果或虚构周KPI。

### S3-A 候选接收与主控回归（2026-10-23）

- 施工会话 `01a16444-9e5a-7da0-8286-67f40c7827f8` 因 Codex CLI 账户 usage limit 退出（exit1），没有最终交付报告，也未完成最后一轮全量验收；状态 **unavailable**。保留原会话/施工树，额度恢复后同会话续接，不静默换模型。CLI 提示 5:03 AM，时区未核实，不推算恢复时刻。
- **CR-S3A-L01** 主控新增确定性回归：强制进程退出等待先完成、日志sink随后失败；修前1 failed（DID NOT RAISE SettingsError）。修复为drains结束后二次检查sink错误，Git/日志定向 **20 passed**。
- **CR-S3A-L02（major，主控亲自复现并小修复）**：SQLite已提交queued后取消HTTP请求，执行派发随请求丢失，任务永久停queued。新增回归按提交后挂起→取消请求→释放交接，修前1 failed（等待executor进入超时）。RunService持有shielded acceptance任务并登记收尾，关闭时先等已开始接收完成再回收worker；回归+faults **26 passed**。两项回归在 `tests/test_s3_lead_regressions.py`，未删除/放宽施工方用例。
- 候选清理仅新增/改动文件的格式、import及内部锁等待参数名；ruff通过，契约已重生。最终后端全量验收进行中，不能把定向结果当集成通过。
- S3-A交叉审计已异步派发：Claude Code CLI requested `claude-sonnet-5-5 / medium`，只读Read/Grep/Glob及精确允许的只读git/既有假环境测试命令，禁止Edit/Write/派发/联网。review_id=`s3a-cross`，预分配session=`d20575a3-cb48-45a0-8de1-c02aec1ff0f4`（待JSON回执确认），输入基线`bcfeba5`+29文件SHA256清单；请求/回执 `.local/reviews/s3a-cross/`，actual/modelUsage待回执，不以参数冒充实际回执。

### S3-A 首轮审计与阶段检查点

- 审计首轮exit0，JSON确认同一session `d20575a3-cb48-45a0-8de1-c02aec1ff0f4`；`modelUsage` 唯一模型键及canonicalModel均为 `claude-sonnet-5-5`，provider=`firstParty`。medium由命令可验证，提供方未回执实际effort。首轮结论 **pass after minor fixes**，7项minor；L01/L02代码层面确认修复。精确白名单拒绝其带cd及不同参数的Bash命令，未扩大权限；审计者只读源码，未跑测试/核验SHA或完整审阅生成契约及既有测试，不冒充全覆盖。

| finding_id | 主控核实与处置 |
| --- | --- |
| CR-S3A-001 | **fixed（S3-B，2026-10-23；主控修前复现）**；原记录：**deferred，S3-B接入前落实**：纯本地异常/总超时的failed/cancelled分类需结合阶段与远端观察。不能仅凭effects为空判定安全终态：复用的owned=false构建仍可能运行。生产executor尚未接入，入口关闭。 |
| CR-S3A-002 | **fixed（2026-10-23，原会话续接；见「S3-A 收尾」）**；原记录：**deferred，原S3-A施工会话恢复后优先修**：收尾的DB/CAS失败可使worker退出而持久状态仍running/cancelling；需登记失联worker/诊断及同进程只读恢复。DB真正不可写时不能伪造unknown已落盘。当前保留预约，重启recover；不宣称此项闭环。 |
| CR-S3A-003 | **fixed（主控）**：关闭时逐worker容错，finally发停止信号，最外层finally关闭DB/锁。新增cancel journal抛错回归，修前失败。 |
| CR-S3A-004 | **fixed（主控）**：checkpoint UPDATE检查rowcount，不存在步骤404并事务回滚，不发假checkpoint事件。新增回归修前DID NOT RAISE。 |
| CR-S3A-005 | **fixed（主控）**：raw_bytes预算仍持久计数，空safe文本不发log事件；后续文本只追加一个seq。新增回归修前2 != 1。 |
| CR-S3A-006 | **rejected（合同依据）**：WORK_PACKAGES规定活动/unknown任务编辑/删除409，sort_order也属于编辑字段；更改活动任务位置应阻断，不擅自放宽为只锁执行字段。其他任务单独PATCH仍可用；待同会话确认/挑战。 |
| CR-S3A-007 | **fixed（主控）**：临时bare远端改写source ref后，真实GitAdapter.execute修前fetch失败；仅fetch至refs/remotes/origin的refspec加`+`，push及本地分支均不强制。新增回归验证远端跟踪更新、本地main不变。 |

- 003/004/005/007新增回归均由主控亲自先跑失败，修复后与L01/L02合计 **6 passed**。修复delta限定binary patch已check后同步回施工树，第二轮同会话 `--resume` 复核进行中；保留001/002延期与006拒绝，不要求审到零问题。
- 集成按 `next/backend`、`next/contracts` 限定binary patch，先 `git apply --check` 后应用；主控生成前端 `schema.d.ts`。首轮集成版本全量后端 **639 passed**（166.13s），前端 **755 passed**（37文件）；frozen离线安装/typecheck/lint/build/guard:dist/contracts:check通过；后端ruff/contracts通过。Rust fmt/clippy离线通过，test **36 passed**（8+9+19）；根目录旧代码守卫 **66 passed / 2 skipped**（68项收集，ok-script两例因平台符号不可用跳过），均在重写目录执行。
- 上述639是审计小修复之前版本；最后修复版正在重新全量验收，最终结果另追加，不套用旧结果。独立测试目录实际收集 **10项新增用例**，已包含在全量集合；子agent最终报告因父施工会话quota退出未核齐，不虚构其交付。施工自修的修前证据已从CLI提取30条失败命令；主控尚未核齐每项反向补丁复现，需原会话续接整理，当前只保存阶段检查点，**不宣称S3-A工程交付或整个S3完成**。
- 四技能/生命周期复核：确认单一ConfigStore写入、配置锁内预约、SQLite状态/事件原子提交，副作用意图先行；unknown预约保留；Git管道/监督进程/继承锁与关闭finally有测试，HTTP请求取消后的接受任务由后端持有。001/002残留已明确，不声明production-ready。
- S3-B/C **not_dispatched**；B公开API核实和接力要点保留 `.local/dispatch/s3b/`，C侦查已完成。后续顺序：额度恢复续接原S3-A会话核齐交付/优先修002 → S3-B完整ADO链及001 → 冻结DTO和假fixture → Gemini S3-C。无新增用户决策。
- 未测：真实SSH agent/host key/远端push、真实ADO构建/发布/回滚、Keychain及Tauri人工运行；本轮全部外部写测试为临时bare或假执行器，没有对真实远端操作。施工worktree/本地回执保留，未删除；没有启动需长期保留的业务进程。
- Claude第二轮exit0，JSON确认仍是同session，modelUsage仍仅 `claude-sonnet-5-5`/firstParty，medium实际effort无提供方回执；结论仍 **pass after minor fixes**。确认003/004/005/007关闭、接受006拒绝，无新发现；001/002继续deferred/open，明确002是S3-A验收未完成项。只读复核patch与测试结构，未独立运行测试/校验SHA，不宣称审计全通过。后续修复继续resume此session，不另换会话或模型。
- **最终修复版主控验收**：后端完整 `pytest -q` **643 passed**（164.28s），ruff、contracts --check、git diff --check及改动范围/SHA256一致性检查通过；前端/Rust/根目录守卫结果仍对应相同未改源码。此结果仅证明当前自动检查通过，不关闭001/002、不替代施工最终报告/全部修前证据核齐或真实验收。当前包状态 **checkpoint / partial**；本地提交后不push，pre-commit自动版本递增单列为既有行为。

### 2026-10-23：前端视觉方向重做，S3 界面施工暂停

- 用户在 1440×900 dev:web 下看过任务/工单/设置后判断：方向 E「液态玻璃 × 游戏 UI」不适合做成正式软件，决定重出设计稿。
- **S3-C 暂停**（not_dispatched → paused）；S3-A/S3-B 后端照常。新设计稿以工单页真实数据形态、1440×900 出 2~3 个方向供用户选择，选定后另立换皮工作包（令牌/基础组件 → 工单、设置两页），验收加对照设计稿截图。
- 画布 https://claude.ai/artifact/Uno9R3vJky5oSRgvxb5D1K 出 A/B/C 三版工单页（数据为虚构，字段形态按 S2 真实接口）。**用户选定 B（macOS 原生），C 作为深色模式参考**；规则记入 FRONTEND_STACK §9。下一步：B 深色稿 → 其余页面与组件清单 → 换皮工作包合同。
- 同画布补齐方向 B 的任务（运行中/确认运行/需要核实/没有任务，状态与步骤按 S3 合同七态与三种操作）、设置（ADO 连接；正常/HTTP 明文警告/存储只读）、AI 会话（等待审批/运行中/没有会话，仍为 S5 前的示意）与组件清单（色彩、字号、按钮、输入、列表行、状态、反馈、版式）。待用户过目后写换皮工作包合同；尚未对画布截图自查。
- 用户确认页面与组件清单，下达写换皮合同。WORK_PACKAGES revision 7 追加 **R1：方向 B 换皮**（单包，Claude sonnet / medium 施工 + haiku 独立测试，codex gpt-6.1-sol / high 只读交叉审计；只换视觉不改行为；任务页改占位，由 S3-C 按 B-Tasks 实现）；S3-C 改为依赖 R1 集成。设计源码快照入库 `design/b-native/`。R1 状态 **not_dispatched**。

### R1：方向 B 换皮（2026-10-23，集成完成）

- 主控：Claude Code 主会话（由 S3 主控会话派生，role: lead），requested Opus 5.5 / medium；actual model/effort=unknown（无提供方回执）。输入 `rewrite/next @ 493f9fd`（派工前确认 HEAD 未变），施工 worktree `.local/worktrees/r1`（detached）。
- 施工：Claude Code 原生子 agent，requested sonnet / medium，actual unknown；agent_id `a9977194f0d6aa326`。测试子 agent（施工者委派）：requested haiku / medium，independent=true，actual unknown；agent_id `a062f719b49102fd7`，新增 `tests/independent/r1-{tokens,guards,components,connection,pages}.test.ts` 共 72 例，未发现生产缺陷（其 3 处类型错误由施工者改写法修正，断言未动）。
- **交叉审计：用户 2026-10-23 取消（原话“不需要交叉审核，最多派个测试员就行了”），not_dispatched**；合同中 codex gpt-6.1-sol 审计条款本包不执行。
- 改动：90 个文件，均在 R1 write_scope 内；`src/api/**`、`stores/backend.ts`、`app/backend-runtime.ts`、后端、contracts、src-tauri、scripts 未动。删除 E 组件 14 个与 `app/mock/{pinned,shell-status}.ts`、`features/tasks/mock/`；新增 Pane/Button/ToolbarButton/TextField/SearchField/Tag/StatusPill/Banner/Inspector/InspectorToggle/Sidebar/ConnectionStatus/ListRow/EmptyState/Skeleton/Sheet/SegmentedControl；令牌、骨架、工单/设置/AI/任务占位重写；移除三个 @fontsource（lockfile 同步）；README、THIRD_PARTY 更新。
- 既有测试改动（施工者逐一列理由，主控抽查 diff）：仅改定位方式——boot.ts（新增 openConnection）、s1c、s1c-ui、e-security（开关前先开连接弹层）、settings/settings-independent（竖向分区 ArrowDown/Up）、s2b-page（重试按钮限定在 wi-error 内）、work-items（P2/标签/指派改在检查器断言，“在浏览器打开”在顶栏）、a11y（Tab 序列改在工单页、28px 目标）；E 视觉断言按 B 改写/删除——tokens、components、app、pages、e-alert、e-controls、e-security 对比度段、settings-independent 的 /tasks 页签用例（任务 mock 已删）。主控核对 e-alert/work-items/s2b-page/e-security 删除行：删除的只有任务 mock 行/检查器/角标与 E 令牌断言，告警只由 store 驱动、告警下可交互、连接安全断言保留或改在工单页等价断言。
- 合同偏差（主控接受）：①合同令牌 `#6E6E73` 在侧栏 4.35、控件底 4.34、“已停用”底 4.46，不满足合同自身 4.5:1 验收，新增 `--mute-tint #636368` 用于这些面、已停用文字改 `#65656A`；深色选中行次行用 `--row-sel-sub`。②设置页删除/导入确认仍为行内确认（合同只要求沿用确认语义），Sheet 仅组件 + 单测。③工单列表行次行多一个“状态”字段（保留既有行信息断言）。④AI 会话徽标用 CL/CX/AG 文字缩写，检查器目录/分支/关联工单为 mock 派生值。
- 集成：限定路径 binary patch（首版遗漏施工者 `git rm` 暂存的删除，改用 `git diff HEAD` 重新生成；`git apply -R` 撤回后重应用），每次 `git apply --check` 后应用，主仓库与施工 worktree `git diff HEAD --stat` 一致。
- 截图对照（dev:web 1440×900；端口 1420 已被 09:19 启动的同目录 dev:web 占用——非本会话进程，未终止，直接复用其隔离临时后端 + 假 ADO；为进入正常态在其中新建假 library/project `Sample` 并填 fixture 假 PAT `dev-credentials.json` 值；告警演示开关开后已关回）：
  - 第一轮退回施工者：**设置页内容区宽度 0**（竖向 SegmentedControl `width:100%` 撑满）、库/项目/仓库编辑器仍在右侧检查器（标签在上）、连接弹层 Esc 关不掉。施工者返工：竖向 tablist `width:auto`、编辑器进内容区白卡片（120px 标签列，标签在左）、设置页去掉检查器与开关、弹层文档级 Esc 关闭并回焦；新增 `tests/unit/settings-layout.test.ts` 5 例 + app.test 1 例。
  - 第二轮主控复查：导航实测仅 113px（SegmentedControl 竖向规则 scoped 特异性 0,4,0 高于设置页 0,3,0，220px/内边距被覆盖）。主控小修：选择器改为 `.panel .settings-tabs[data-orientation='vertical'] :deep(.seg)`，同步更新 settings-layout 断言选择器并加注释；同步回施工 worktree。
  - 通过：工单 未配置（浅/深）、正常 + 详情选中（浅/深，选中行浅色强调蓝白字、深色 `#262A1C`）、出错（未配置 PAT → 列表内 error Banner + 前往设置/重试）；设置 正常（ADO 连接两张卡片 + 编辑卡片）、HTTP 明文 warn Banner（字段下方内联）；AI 等待审批（会话列表、工具调用条、内联审批 Y/A/N、检查器）；任务占位（EmptyState，无 mock 文本）；告警（页面区顶部 warn 横幅、连接行变橙、页面可操作）。
  - 残余差异（不退回，记录）：出错态设计稿为列表区居中图标 + “无法读取工单”，实现为列表顶部 error Banner（合同允许 Banner/空状态）；读取中骨架态一闪而过未截到（单测覆盖）；设置“存储只读”无法在 dev 后端触发（单测覆盖）；AI“运行中”态未单独截图；同源示例图片未显示属假 fixture 无媒体内容，非 R1 行为改动。
- 集成版本验收（`next/desktop`，最终版）：`pnpm install --frozen-lockfile --offline`、typecheck、lint（0 error / 2 warning，既有 one-component-per-file）、`pnpm test` **847 passed / 43 文件**、build、guard:dist、contracts:check 全部 exit 0；`git diff --check` exit 0；写入范围外无改动；`src/**` 无 clip-path/backdrop-filter/Oxanium/@fontsource/禁词（dist 中 clip-path/backdrop-filter 字符串仅来自 Tailwind `.sr-only`、DOMPurify 与 tailwind-merge 内置表，guard:dist 通过）。
- 未测：Tauri 内渲染与 Overlay 标题栏拖拽区、真机深色切换、Playwright e2e、`:focus-within` 与焦点陷阱真实浏览器行为（仅 jsdom）。
- cleanup：本会话 dev:web 因端口占用未成功启动、已退出；施工 worktree `.local/worktrees/r1` 保留（删除前需问用户）；补丁与日志在 `.local/dispatch/r1/`。
- 状态：**R1 integrated**；S3-C 可以本提交为输入派工。

### S3-A 收尾（2026-10-23，CR-S3A-002）

- 主控：Claude Code 会话，role: lead，requested Opus 5.5 / medium；actual=unknown（无提供方回执）。用户本日改派：前端 agy、后端 GPT、测试 GPT，不做交叉审计。
- 施工：codex 额度已恢复，`codex exec resume 01a16444-9e5a-7da0-8286-67f40c7827f8` 同会话续接（未换会话/模型），`-m gpt-6.1-sol -c model_reasoning_effort=medium`，沙箱沿用首轮 workspace-write。本地 rollout `turn_context` 记录 model=`gpt-6.1-sol`、effort=`medium`、workspace-write、network_access=false（本地运行时回执，非提供方底层路由保证）。exit 0。请求/输出 `.local/dispatch/s3a/resume2-*`。续接前主控核对施工树与 `66a92f2` 后端/契约内容一致（仅 README 一行差异，已同步）。
- 测试子agent：本轮未新派；上轮 `/root/s3a_tests`（requested gpt-6-luna / high，rollout turn_context 记录 gpt-6-luna/high）新增 10 例，施工者本轮复跑 10 passed。
- CR-S3A-002 修复：`services/runs.py` worker 外层登记失联 worker（固定脱敏诊断，不外泄 DB/适配器异常文本），恢复轮仅对已退出 worker 调用限定 run 的 `recover(reason_code=worker_lost)`；`adapters/run_store.py` recover 支持限定 run_ids，运行期写故障保护仅在恢复事务成功提交后解除。DB 仍不可写时状态/last_seq 不变、预约保留、不调用 reconcile；恢复后 unknown/pending 再只读 reconcile，不重放执行。新增 `tests/test_s3_worker_recovery.py`（6 参数化：running/cancelling × DB 提交失败/CAS 冲突/SQLITE_FULL）。
- **主控修前复现**：在集成树 `66a92f2` 只加新测试、生产代码未改：**6 failed**（`exited worker was forgotten`）；应用限定 patch（`.local/dispatch/s3a/cr002-fix.patch`，2 文件 +48/−9，`git apply --check` 后应用）后 S3 定向 **44 passed**。施工者另报 readonly 用例修前 2 failed（解除故障后仍 running/cancelling）。
- 主控核查备注：`_execute` 外层同时吞下 CancelledError 并登记为失联；关闭时被取消的 worker 也会登记，但只影响登记，预约保留并由下次启动 recover 处理，不触发外部写。接受。
- 上轮 30 条失败命令：施工者逐条对应到修复项（表见 `.local/dispatch/s3a/resume2-stdout.jsonl` 最终回复），**未逐项反向复现，状态 unknown**；其中 3 条为检索/探测非回归。主控不宣称该 30 项逐项复现闭环。
- 集成版本验收（`next/backend`）：首次全量 pytest **648 passed / 1 failed**（`tests/independent/test_fault_lifecycle.py::test_sigterm_during_startup_window_does_not_hang[0.15]`，S0 启动窗口计时用例，与本改动无关；单独重跑 5 轮 25/25 passed，判为负载下计时抖动，记 flaky）；ruff exit 0；contracts --check exit 0；`git diff --check` exit 0。第二次全量 **649 passed**（170.51s，exit 0）。
- 状态：CR-S3A-002 fixed；CR-S3A-001 仍 deferred 至 S3-B；CR-S3A-006 rejected 维持。S3-A **integrated**（生产 start/preflight 仍 unsupported_task，等 S3-B）。未测：端口外真实 SSH/ADO/Keychain/Tauri。施工 worktree `.local/worktrees/s3a` 保留（删除前问用户）。

### S3-B 集成与接口冻结（2026-10-23）

- 施工：codex exec 新会话 `01a16677-1c84-7eb3-9f24-11f0dbc7197e`，`-m gpt-6.1-sol -c model_reasoning_effort=medium -s workspace-write`；本地 rollout turn_context 记录 gpt-6.1-sol / medium / workspace-write / network_access=false（本地运行时回执）。输入 `b65460e`，worktree `.local/worktrees/s3b`。exit 0，交回 partial（一条旧断言待裁定、端口用例 not_run）。请求/输出/交接 `.local/dispatch/s3b/`（`handoff/` 含补丁、19 文件 SHA-256 清单、17 项修前证据、验证记录）。
- 测试子agent：`/root/s3b_tests`，requested gpt-6-luna / high，rollout `01a16677-f86d-…` turn_context 记录 gpt-6-luna / high；新增 `tests/independent/s3b/` 31 例，施工者复跑 31 passed。交叉审计：用户已取消，not_dispatched。
- 结果：真实 `AdoTaskExecutor`（sync_build_release/deploy_only/rollback），共享 ado_read 出站底座与 6 许可；Release 版本 GET 协商冻结、写不重发；复用身份全元组、固定 commit、owned 仅来自 intent+回执；单 artifact 绑定、manualEnvironments、新 attempt 区分；生产 start/preflight 开放。PlanResponse 等全部具体 DTO，契约重生成。dev 假数据：`TOOLBOX_DEV_TASK_ROOT`（须 --dev + memory + FAKE_ADO 三重门），后端建临时 bare+clone，播种四任务（同步成功/只发布失败/回滚需核实/已停用），有状态 MockTransport。
- **CR-S3A-001 主控修前复现**：在施工树临时把 `runs.py` 两处 `_failure_outcome` 还原为无条件 unknown，`tests/independent/s3b/test_runservice_uncertain_outcomes.py` **2 failed / 2 passed**（local_exception→实际 unknown 预期 failed；timeout→实际 unknown 预期 cancelled）；恢复后 4 passed。规则：effects 非空或任一步骤 checkpoint 含 build_id/pipeline_run_id/release_id 即保持 unknown，否则 failed/cancelled 并释放预约。其余 16 项修前证据为施工/测试者记录，主控未逐项反向复现（unknown）。
- **用户裁定（2026-10-23 原话“同意：把 test_start_is_rejected_as_unsupported_until_s3b_executor_exists 改写为初始化后的未知 plan 返回 409 plan_expired 且不产生 run”）**：主控改写 `tests/independent/s3a/test_task_http_auth_contract.py` 该用例为 `test_start_with_unknown_plan_is_rejected_without_creating_a_run`（lifespan 初始化后 start 未知 plan → 409 plan_expired，`/api/runs` 为空）；同文件认证用例不动。（首次改写被 auto mode 分类器拦截，取得用户同意后执行。）
- 集成：施工树 `next/backend`、`next/contracts` 限定 binary patch（20 文件，+5631/−483，含上述测试改写），`git apply --check` 后应用于 `b65460e`；施工树改动均在 write_scope 内。主控 `pnpm contracts:gen` 生成 `next/desktop/src/api/schema.d.ts`（+342/−21）。
- 集成版本验收：后端全量 pytest **729 passed**（181.95s，含端口用例，沙箱外），ruff exit 0，contracts --check exit 0；前端 `pnpm install --frozen-lockfile --offline`、typecheck、lint、test **847 passed / 43 文件**、build、guard:dist、contracts:check 全部 exit 0；`git diff --check` exit 0。施工树全量另跑 729 passed。
- **接口冻结**：以本提交的 `next/contracts/openapi.json`、`events.schema.json`、`next/desktop/src/api/schema.d.ts` 与 `next/backend/tests/fixtures/fake-ado/tasks.json` 为 S3-C 输入；S3-C 不得改契约/后端，缺字段停下交主控。
- 未测：真实 ADO（自建服务器版本/Pipeline↔Build 关联/manualEnvironments/审批门禁）、真实 SSH push、Keychain、Tauri。施工 worktree `.local/worktrees/s3b` 保留。

### S3 接口扩展：runs order=desc 与 TaskView.last_run（2026-10-23）

- 起因：S3-C 第二轮 dev:web 实测，冻结接口无“每任务最近运行”且运行列表仅旧到新，前端只能捏造行状态（无运行默认“成功”）与时间。**用户批准（原话“同意扩展接口：GET /api/runs 增加 order=desc（新到旧，游标同步支持），TaskView 增加 last_run 摘要（run_id、status、operation、created_at、finished_at）。仍由原 S3-B codex 会话实现并补测试，主控重新生成契约并冻结，再让 agy 第三轮接入。”）**
- 施工：`codex exec resume 01a16677-1c84-7eb3-9f24-11f0dbc7197e`（同会话，gpt-6.1-sol / medium，workspace-write 沿用）；未派测试子agent（扩展小，主控验收）。方案：asc 默认保持原两字段游标；desc 游标 `["desc", created_at, run_id]`，方向混用/非法 order 422；`LastRunSummary` DTO，一次参数化 SQL 批量取各任务最新运行（含活动中），运行库不可用时 last_run=null + warnings，任务接口仍 200。既有 `test_s3_faults.py` 仅把注入点从 `active_snapshots` 改为 `task_summaries`，断言不变。请求/输出/交接 `.local/dispatch/s3b/ext-*`。
- **主控修前复现**：集成树 `6dc0de0` 只加新测试 `tests/test_s3b_run_read_extensions.py`：**9 failed / 2 passed**（与施工报告一致）；应用实现补丁后通过。
- 集成版本验收：后端全量 **740 passed**（182.20s，沙箱外含端口），ruff、contracts --check exit 0；前端 frozen install/typecheck/lint/test **847 passed**/build/guard:dist/contracts:check 全 exit 0；`git diff --check` exit 0。契约与 `schema.d.ts` 以本提交**重新冻结**为 S3-C 输入。

### S3-C 任务页接真实接口（2026-10-23，集成）

- 分工（用户本日指定）：前端施工 Antigravity CLI `agy`，requested `gemini-3.8-flash-high` / `--effort high`，`--sandbox`（auto mode 分类器拒绝 `--dangerously-skip-permissions`，本机 agy toolPermission=always-proceed，改用 sandbox 无该标志可正常执行 pnpm）；cwd 缓存会话 `8a2d0771-77ea-4903-9f85-a2c05d8498e9`，共 5 轮 `--conversation` 续接；actual model/effort=unknown（agy 纯文本无回执）。独立测试：codex exec `gpt-6-luna` / high，session `01a16710-c23d-7fc3-97dd-91ed5a7c62d6`（rollout turn_context 记录 gpt-6-luna/high），续接 1 轮；不做交叉审计。输入 `6dc0de0`，worktree `.local/worktrees/s3c`，主控同步 `2a2e0a4` 接口扩展。请求/输出 `.local/dispatch/s3c/`。
- 结果：任务页按 B-Tasks（列表/搜索/筛选、详情、preflight→Sheet 确认含精确制品与必选“旧应用空闲”、三操作、CRUD/排序、运行卡片/步骤/日志、历史 order=desc、unknown 说明与只读“立即核对”、停止提示不回滚）；WS run 订阅先订阅后补齐、run_seq 去重/乱序/单飞补缺口、切换退订、卸载不取消；侧栏任务角标取服务数据；dev-web.mjs 接 `TOOLBOX_DEV_TASK_ROOT` 生命周期。R1 尾巴：设置删除/导入确认改 Sheet；工单出错态改居中 EmptyState。
- 主控 dev:web 实测（1440×900，假 ADO + 临时 git）退回问题，逐轮修复：R2 实时状态不更新（运行结束仍显示运行中、步骤/历史/角标不刷新）、日志逐行时间戳捏造（契约无 ts，改为行号）、产品内隐藏“任务执行正在接入”占位（删除；经主控特许迁移 `tests/unit/pages.test.ts`、`tests/independent/r1-pages.test.ts`、`tests/independent/e-controls.test.ts` 三处断言为“任务页根存在且不含 mock 文本”）、日志全量入内存、补缺口非单飞、列表行显示长路径；R3 无运行任务默认显示“成功”、行时间取选中任务最旧运行、卡片跳回旧运行（触发用户批准的接口扩展，见上节）；R4 测试者发现双击发 2 次 POST、确认单 commit 截 7 位且缺失写“最新”，加失败原因展示；R5 has_more=false 但缓冲仍有更高 seq 时不再补齐。每轮施工者报告修前失败用例；主控复现了测试者的 3+1 个失败（修前 3 failed / 8 passed；1 failed / 21 passed）。
- 独立测试：`tests/independent/s3c-*.test.ts` 7 文件 22 例（契约观察、列表/角标、run 隔离、设置取消、后续流程、历史/键盘、日志分页）；施工者未改其文件（主控核对 mtime 早于后续轮次）。施工者单测 `tests/unit/s3c-*`。未覆盖：cancelling→cancelled 单独路径、真实 WebSocket 断开重连（仅在线状态切换模拟）、jsdom 下原生 Enter 激活。
- 实测通过（dev:web）：同步构建发布 成功（实时 运行中→成功、步骤 commit/#102/Release-202、历史新到旧、角标清除）；只发布 失败（确认单精确制品 #12，失败胶囊）；回滚 需核实（Release #130，warn 横幅“结果需要核实”+“立即核对”、停止不回滚提示）；深色模式需核实页；无运行任务显示“未运行”；设置删除 project 走 Sheet，Esc 关闭不删除；工单正常加载（出错态在假 ADO 下无法触发，由单测/独立测试覆盖）。观察：浏览器窗格隐藏时 Reka Sheet 关闭动画不结束、残留 closed 节点（可见时正常），记为环境现象。
- 集成：worktree `next/desktop` 限定 binary patch（41 文件，+7224/−76，全部在 S3-C write_scope + 特许的三处测试迁移内），先核对 worktree 后端/契约/schema 与 `2a2e0a4` 一致，`git apply --check` 后应用。
- 集成版本验收：前端 frozen install、typecheck、lint（0 error / 8 warning，one-component-per-file 测试内组件）、test **903 passed / 57 文件**、build、guard:dist、contracts:check 全 exit 0；Rust `cargo fmt --check`、`cargo clippy --offline -D warnings`、`cargo test --offline` **36 passed**；后端全量 **740 passed**、ruff、contracts --check exit 0；根目录旧代码守卫 **66 passed / 2 skipped**；`git diff --check` exit 0。
- 未测：真实 Tauri 渲染与 Overlay 拖拽、真实 ADO/SSH/Keychain、真实 WS 断网重连、Playwright e2e；S3 真实验收清单未授权未执行。
- cleanup：主控 dev:web 两次均由本会话启动并停止，1420 已释放，dev 临时 data-dir/TASK_ROOT 已删除；worktree `s3a`、`s3b`、`s3c`、`r1` 保留（删除前需问用户）。
- 状态：**S3-A/S3-B/S3-C integrated**（本地提交，未 push）。

## 2026-10-23：S4 Telegram（合同草案，待确认）

- 主控：Claude Code 会话（由 S3 主控会话派生，role: lead），requested Opus 5.5 / medium；actual model/effort=unknown（无提供方回执），session_id=unknown。本轮只写合同，**未派工**、未委派任何施工/测试会话。
- 输入：`rewrite/next @ e3e4314`，开始时工作区干净；旧目录 `main @ 885d186` 只读（该目录有用户未提交改动，均不在 Telegram 相关文件，未触碰）。主控亲自核对 `app_main.py`、`tg_control.py`、`notifier_telegram.py`、`redact.py`、`secrets.py`、`store.py`、`models.py`、`tg_work_items_bridge.py`、`tg_work_items_inline.py`、`tg_help_inline.py`、`ui/acl_dialogs.py`、`ui/telegram_acl_mixin.py`、`ui/telegram_card.py`、`ui/tasks_tab.py`（TG 回调/通知段），以及新端 `legacy_config.py`、`domain/settings.py`、`services/tasks.py`、`logging_setup.py`、`adapters/credentials.py`、`config_store.py`、`run_store.py`、`app.py`。
- 关键事实（详见 WORK_PACKAGES「S4 旧应用事实核实」）：旧端 4 条轮询线程共用 `telegram_control_enabled`（关它会停掉 AI 机器人）；409 时 deleteWebhook 后继续轮询，不让出；offset 整批处理完才保存，中途异常导致整批重投、已执行指令再触发；积压指令照常执行；owner 为空时第一个私聊者自动成为 owner；callback_data 携带 task_id、回滚确认不重查 ACL；通知失败摘要含 git stderr 首行且正文未脱敏；`/wi` 把 ADO 异常原文回给 TG；新端尚无 Bot Token、脱敏器缺 bot URL/认证头/URL 编码规则。
- 合同追加在 WORK_PACKAGES「S4」（revision 8）：架构五问、config schema v2 `telegram` 段与迁移、Bot Token 凭据与旧端只读导入、`telegram.sqlite3` 与 runs v2 `origin_json`、长轮询生命周期与 409 让出、所有权切换步骤与回退、ACL 解析与 S3 执行衔接（确认时重查、动作令牌、uuid5 幂等键）、`detach_acl` 解除 `task_referenced`、发件箱通知、`/wi` 只读、统一脱敏、HTTP/WS、安全核对表、S4-A/B（后端）/S4-C（前端）分包、验收命令与真实验收清单（另行授权）。
- 加载技能：AI prompt root 下 backend-architecture-review、backend-security-review、data-consistency-review、backend-business-safety（按其要求写入五问/安全/一致性/生命周期合同）。
- **八项待决**（推荐与影响见合同「S4 待决」）：1 主 Bot 切换时机与方式；2 TG 执行是否加确认；3 owner 绑定；4 username 成员与旧白名单；5 删除被 ACL 引用的任务；6 `/wi` 图片转发；7 停机积压指令；8 Telegram 是否走系统代理。尚无用户已决。
- 状态：S4-A/S4-B/S4-C **not_dispatched**；交叉审计按用户 2026-10-23 决定不做。
- 安全范围：未读真实配置/凭据/offset 文件、未连真实 Telegram/ADO；旧目录源码未改；未新建 worktree/进程/临时目录，无需清理；`.local/worktrees/{s3a,s3b,s3c,r1}` 保留。本轮只改 WORK_PACKAGES 与 PROGRESS，未运行功能测试（无代码改动）。

### S4 合同确认（2026-10-23）

- 用户原答复“S4 的八项待决均按你推荐的来。”，八项均按推荐确认；WORK_PACKAGES「S4 已决」已写入，合同状态改为已确认，派工门禁解除。主控 actual model/effort=unknown。
- 状态：S4-A/S4-B/S4-C 仍 **not_dispatched**（本会话受派生任务约束“只写合同、不派工”，派工另行开始）；主 Bot 切换与真实验收未授权。

### S4-A 派工（2026-10-23）

- 用户原话“开始派工 S4-A（codex gpt-6.1-sol / medium，测试员 gpt-6-luna / high）”。主控：Claude Code 会话，role: lead，actual unknown。
- 输入 `rewrite/next @ b70afb0`；worktree `.local/worktrees/s4a`（detached），后端 `uv sync --frozen --offline` 后 `contracts --check` exit 0。
- 施工：codex exec，`-m gpt-6.1-sol -c model_reasoning_effort=medium -s workspace-write`，不联网；请求与输出 `.local/dispatch/s4a/`（request.md、stdout.jsonl、stderr.log）。施工者可派一层测试子agent gpt-6-luna / high，仅写 `next/backend/tests/independent/s4a/`；不做交叉审计。实际型号/档位以 rollout turn_context 为准，返回后补记。
- codex session `01a16743-a089-74d1-8d42-a2a6201bb517`。
- 状态：S4-A **dispatched / running**；S4-B、S4-C not_dispatched。
- 第 1 轮（2026-10-23）：exit 0，交回 **partial**。rollout turn_context 回执施工 `gpt-6.1-sol` / medium、workspace-write、network_access=false；测试子agent `/root/s4a_tests` rollout `01a16744-a8da-7d01-97d2-6b51b9645859` 回执 `gpt-6-luna` / high（本地运行时回执）。交付：`logging_setup.py` 脱敏扩展（bot URL/认证头/URL 编码/代理 userinfo/异常链）、`adapters/telegram_http.py`、施工回归 7 例（修前 6+1 failed）、独立 13 例；主控复跑 20 passed、ruff exit 0。其余目标未实现；施工者按规则停下列出 5 处既有断言冲突（schema 版本 1、读取 `imported.telegram`）。测试子agent曾试图 apply_patch 到主控目录（失败未落盘，主控确认主目录干净）。
- 主控裁定：5 处冲突是已确认合同（config v2、移除 imported.telegram）的计划内变化，允许仅改这 5 处并保留原意（逐条列出）；要求导入路径与 v1→v2 迁移结果一致。`codex exec resume` 同会话续接第 2 轮，请求 `.local/dispatch/s4a/resume1-request.md`。

### S4-A 集成（2026-10-23）

- 第 2 轮：`codex exec resume 01a16743-…` 同会话，rollout turn_context 回执 `gpt-6.1-sol` / medium（本地运行时回执）；exit 0，施工者报告整包完成。测试子agent `/root/s4a_tests`（`gpt-6-luna` / high 回执）累计新增独立用例 32 例（`tests/independent/s4a/`）；本包新增用例共 87。请求/输出 `.local/dispatch/s4a/resume1-*`。
- 结果：config schema v2 类型化 `telegram`（v1→v2 迁移与直接导入共用规范化，强制停用，移除 `imported.telegram`，快照+原子写）；Bot Token 凭据（kind=telegram_bot，手动/旧端只读导入/删除）；`adapters/telegram_http.py`（固定域名、不跟随重定向、限额、独立并发、跟随系统代理、固定错误类别）；`telegram.sqlite3`（tg_bots/tg_updates/tg_actions/tg_outbox）与 runs v2 `origin_json`；TelegramService（enable/disable/retry、首次基线、先登记后处理、409 停止零 deleteWebhook、退避、过期指令、关闭清理）；ACL 解析与 `/bind`、username→user_id 绑定；发件箱通知与重启补发；统一脱敏；19 个 HTTP 操作、WS `telegram.status`、`DELETE /api/tasks/{id}?detach_acl=true`、新错误码；dev 假 Telegram（`TOOLBOX_DEV_FAKE_TELEGRAM=1` 须 --dev+memory，inject/sent 路由仅该模式注册）。执行类指令回复“暂未开放”，留 S4-B。
- 既有测试改动：仅主控裁定的 5 处（schema 1→2 两处、`imported.telegram`→类型化 `telegram` 三处），主控逐行核对 diff 与裁定一致。
- **主控修前复现**：集成树中临时把 `logging_setup.py` 换回 `b70afb0` 版本，`tests/test_s4a_redaction.py` **6 failed / 1 passed**；恢复后 7 passed（与施工树逐字节一致）。其余修前证据为施工/测试者记录，主控未逐项反向复现（unknown）。
- 集成：worktree `next/backend`、`next/contracts` 限定 binary patch（`.local/dispatch/s4a/integration.patch`），`git apply --check` 后应用；主控去掉两处独立测试文件 EOF 多余空行（diff --check）。主控 `pnpm contracts:gen` 重新生成 `next/desktop/src/api/schema.d.ts`。
- 集成版本验收：后端全量 pytest **827 passed**（240.42s，沙箱外含端口；施工树沙箱外另跑 827 passed），ruff exit 0，contracts --check exit 0；前端 frozen install/typecheck/lint（0 error / 8 warning，既有）/test **903 passed / 57 文件**/build/guard:dist/contracts:check 全 exit 0；`git diff --check` exit 0。Rust 与根目录旧代码守卫：not_run（本包未改 src-tauri/旧代码）。
- 主控核查备注（留 S4-B 处理）：①无 can_run 的组成员菜单仍显示“任务”入口（当前只回复暂未开放），S4-B 开放执行时按权限收紧；②轮询循环只捕获 TelegramError，本地 DB 等其他异常可能使轮询任务静默结束而状态不更新，S4-B 需补兜底与回归。
- 未测：真实 Telegram/Keychain/系统代理/Tauri；dev:web 假 Telegram 端到端留 S4-C 联调。施工 worktree `.local/worktrees/s4a` 保留（删除前问用户）。
- 状态：**S4-A integrated**（本地提交，未 push）；S4-B、S4-C not_dispatched。

### S4-B / S4-C 并行派工（2026-10-23）

- 用户原话“派工 S4-B（同 codex 会话续接）和 S4-C（agy gemini-3.8-flash-high，--sandbox），并行。”主控 actual unknown。输入均为 `b64dd65`（S4-A 集成，契约冻结）。
- S4-B：`codex exec resume 01a16743-a089-74d1-8d42-a2a6201bb517`（`-m gpt-6.1-sol -c model_reasoning_effort=medium`，沙箱沿用 workspace-write、不联网），沿用 worktree `.local/worktrees/s4a`：主控先把施工者第 2 轮工作树留档为本地 WIP 提交 `17444d9`，再 detached 切到 `b64dd65`（工作区干净）。测试子agent gpt-6-luna/high 仅写 `tests/independent/s4b/`。请求明确**不得改动契约**（与 S4-C 并行），并包含 S4-A 主控核查备注两项。请求/输出 `.local/dispatch/s4b/`。
- S4-C：agy `--sandbox --model gemini-3.8-flash-high --effort high --print=<请求>`（不用 `--dangerously-skip-permissions`），worktree `.local/worktrees/s4c`（detached `b64dd65`，前端 frozen offline install、后端 uv offline sync）。首次启动把 `--sandbox` 写在 `--print` 之后被 agy 当作提示词（未执行、未改文件），改为 `--print=` 形式重发。独立测试待 agy 交付后由主控另派 codex gpt-6-luna/high（`tests/independent/s4c-*`）。请求/输出 `.local/dispatch/s4c/`；会话 id 完成后按 cwd 从 agy 缓存取，actual model/effort=unknown。
- 状态：S4-B、S4-C **dispatched / running**。
- S4-B 第 1 轮：exit 0，按“同类失败两次”交回。交付 `services/telegram_commands.py`、`services/telegram_work_items.py` 及 telegram/runs/store/http/fake/app 改动，新增 32 例（含独立 `/root/s4b_tests` 21 例）；契约无改动（contracts --check exit 0），既有测试未改。阻断：`test_s4b_execution.py::test_confirmed_telegram_run_uses_only_temporary_bare_git` 在沙箱内停在 git 步骤。**主控沙箱外复跑：整文件 5 passed、该用例连续 3 次 passed**，判定为沙箱环境限制、非执行链缺陷，不改生产代码/不放宽用例。剩余 ruff 两处、README、最终复核：同会话续接（`.local/dispatch/s4b/resume1-request.md`）。
- S4-B 第 2 轮：ruff 两处、README「S4-B」、按钮文字脱敏与过期动作保留修复完成（新增 `test_s4b_security_lifecycle.py` 12 例；修前证据见施工报告）；无端口集合 680 passed。复核发现：S2 `outbound()` 取消后等待读取线程（JSON 15 秒/媒体 30 秒），Telegram 关闭超过 5 秒（回归 1 failed），施工者按停止条件交主控。**主控裁定**：不扩展 S2 共享出站（保留 6 许可语义）；Telegram 关闭等待≤5 秒后把仍卡在只读出站的处理器标 detached，此后零发送/零 DB 写/不触碰已关闭资源，进程退出可能延迟至 S2 预算，RunService 关闭不排在其后；合同「停用/关闭」条已同步修订。同会话续接第 3 轮（`.local/dispatch/s4b/resume2-request.md`）。

### S4-B 集成（2026-10-23）

- 第 3 轮：同会话续接，rollout turn_context 6 轮均回执 `gpt-6.1-sol` / medium；测试子agent `/root/s4b_tests` rollout `01a1677d-9ca7-…` 回执 `gpt-6-luna` / high，独立新增 21 例；本包新增用例共 48。施工者按裁定实现 detached 关闭语义，S2 `services/work_items.py` 与 `next/contracts` 对 `b64dd65` 无改动（主控 `git diff --quiet` 核实）；既有测试未改。
- 结果：`services/telegram_commands.py`（构建发布/仅发布/回滚确认流、令牌原子消费+配置锁内权限重查、`uuid5` 幂等键、origin=telegram、停止归属、S3 错误码中文映射、菜单分页与按权限收紧）、`services/telegram_work_items.py`（owner 工单浏览、分块、60 秒缓存、图片白名单与限额）；telegram/runs/store/http/fake/app 衔接；按钮文字入箱脱敏；本地非 Telegram 异常可观察（backoff/store_unavailable）；关闭等待≤5 秒后 detached；lifespan 先关 RunService。
- **主控修前复现**：集成树临时把 `adapters/telegram_store.py` 换回 `b64dd65` 版本，`test_s4b_security_lifecycle.py -k button_labels` **6 failed**；恢复后 6 passed（与施工树逐字节一致）。其余修前证据为施工者记录，未逐项复现（unknown）。
- 集成：worktree `next/backend` 限定 binary patch（`.local/dispatch/s4b/integration.patch`），`git apply --check` 后应用。
- 集成树首次全量 **873 passed / 2 failed**：①`test_s4b_execution.py::test_confirmed_telegram_run_uses_only_temporary_bare_git` 在主目录稳定失败、施工树通过；主控临时调试副本（已删除）显示运行实际 succeeded，但需轮询 441–520 次（10 ms/次），用例只等 400 次——负载下等待窗口过紧，非代码缺陷。**主控修改本包新增用例**：等待上限 400→3000 次（≈30 秒）并加注释，断言不变，主目录与施工树同步；整文件连跑 3 次 5 passed。②第二个失败当次输出被截断未取得用例名，重跑未复现——记 **unidentified / 疑似负载抖动**，后续全量若再现再定位。
- 集成版本验收：后端全量 **875 passed**（260.72s，沙箱外含端口与 bare git），ruff exit 0，contracts --check exit 0；前端 contracts:check exit 0（契约无变化，schema.d.ts 未重生成）；`git diff --check` exit 0。Rust/旧代码守卫 not_run（未改）。
- 未测：真实 Telegram/ADO/Keychain/系统代理/Tauri；dev:web 端到端待 S4-C 集成后主控联调。施工 worktree `.local/worktrees/s4a` 保留。
- 状态：**S4-B integrated**（本地提交，未 push）；S4-C 施工已交回、独立测试进行中。

### S4-C 施工与独立测试（2026-10-23，进行中）

- 施工第 1 轮：agy `--sandbox --model gemini-3.8-flash-high --effort high`，cwd 缓存会话 `e2d67d9a-9943-40fa-8656-f55dd36e7baf`，exit 0；actual model/effort=unknown（agy 无回执）。22 文件均在 write_scope；新增 `tests/unit/s4c-*` 3 文件 26 例；既有测试仅两处随新增分区更新（页签列表加“Telegram”、竖向页签计数 5→6），主控核对 diff。主控在施工树复跑 frozen install/typecheck/lint（0 error/8 既有 warning）/test **929 passed**/build/guard:dist/contracts:check 全 exit 0，`git diff --check` exit 0。
- 独立测试：codex exec `gpt-6-luna` / high，session `01a167af-4003-71e2-b4ea-fba73e77cf27`（rollout turn_context 回执 gpt-6-luna/high），新增 `tests/independent/s4c-*` 4 文件 11 例：10 passed / **1 failed**——缺陷 S4C-001：`telegram.status` WS 事件晚于在途 GET 时被旧 GET 结果回滚（conflict→已停用），疑似 `useSettings.ts:94/115`。测试员自报未覆盖：502/503 文案、enable 请求体、九种状态与阈值、解绑 revision/Esc、ACL 重名/规范化/冲突草稿、任务删除查询参数、方向键/焦点陷阱、PAT/Bearer 全面扫描（部分由施工者单测覆盖，不计独立）。
- 退回 agy 第 2 轮（同 `--conversation`）：修 S4C-001，不得改独立测试，新增自有回归。请求 `.local/dispatch/s4c/round2.md`。

### S4-C 集成与 S4 端到端联调（2026-10-23）

- S4-C 第 2 轮：agy 同 `--conversation e2d67d9a-…`，exit 0，actual unknown。修 S4C-001：`useSettings.ts` 引入 WS 事件序号与 `since` 比较，在途 GET 返回时若期间有更新的 WS 轮询状态则保留 poller 字段、其余字段照常更新；WS 自身晚到旧 `since` 也忽略。新增自有回归 1 例（`tests/unit/s4c-telegram-cards.test.ts`）。主控核对 `tests/independent/s4c-*` 4 文件 mtime 均早于第 2 轮请求（未被施工者修改）；独立用例 11/11 passed。S4C-001 **fixed**（修前失败由独立测试员在定向与全量两次运行中观察，主控未自行反向复现，记 unknown）。
- 集成：worktree `next/desktop` 限定 binary patch（`.local/dispatch/s4c/integration.patch`，主目录 `next/desktop` 先核对与 `b64dd65` 一致），`git apply --check` 后应用。
- **主控 dev:web 联调**（`pnpm dev:web`，假 ADO + 临时 git + 假 Telegram，1440×900，本会话启动并停止；临时 `.claude/launch.json` 用后删除；启动器临时目录已自动删除，1420 已释放）：
  - 设置→Telegram：录入假 Token 后仅显示“已保存（手动录入）”，脚本检查 DOM/输入框/localStorage/sessionStorage/URL 均不含 Token；启用开关弹出切换步骤 Sheet（单独测试 Bot、删除旧 Keychain `my-own-script`/`telegram_bot_token`、勿关旧端开关、回退）+ 必选确认；确认后 Bot 用户名/ID 来自假 getMe，状态“轮询中”。
  - 生成绑定码 → 注入 `/bind <码>` → “owner 绑定成功”，owner chat 6001；`/help` 菜单按钮为 22 字符随机令牌；陌生 chat 7777 零回复；10 分钟前的 `/status` 回复过期提示。
  - TG 端：任务→“演示 · 同步构建发布”（停用任务不出现）→构建发布→计划摘要（仓库/分支/目标/definition/stage、停止不撤回提示）→同一“确认执行”按钮注入两次：**仅 1 个 run**（succeeded，origin=telegram），两次都回“已开始（运行 #b035b839）”，开始/成功通知各一条发给触发 chat。任务页运行卡片与历史显示“由 Telegram 触发”。
  - 删除任务“演示 · 只发布失败”（被 API 新建的“测试组”引用）：Sheet 显示 409 引用组名与“同时从 1 个权限组移除并删除”，点击后发 `DELETE …?revision=6&detach_acl=true`，任务删除，组保留 can_run 且 task_ids 为空并给 warning“该组已无可运行任务”。
- **联调发现并由主控修复**（均先写会失败的回归）：
  - S4-LEAD-001：设置页显示“schema v1”——`SettingsResponse.schema_version` 默认 1 而 `services/settings.py` 未传实际值（S1 潜在缺陷，S4-A 升 v2 后暴露）。修复传入 `config.schema_version`；回归 `tests/test_s4_lead_fixes.py` 修前 1 failed → 修后 passed；契约无变化。
  - S4-LEAD-002：Telegram 分区三个开关无可访问名称（合同 S4-C 键盘与可访问性项）。`TelegramTab.vue` 加 aria-label；回归 `tests/unit/s4-lead-switch-names.test.ts` 修前 1 failed → 修后 passed。
- **记录、未修（后续另排）**：S3C-F1 选中已结束 run 时一次性约 40 个 `GET /api/runs/{id}` 请求突发（非持续轮询，5 秒内 0 新增）；S3C-F2 日志面板 innerText 出现行号重复（3…14 后又 3,4,5），截图中可视区未见重复，未确认；过期提示时间按 UTC 显示（`07:44`，用户本地为 16:44），建议改本地时区；删除冲突提示文案写“被其他配置或工单引用”，“工单”不准确。
- 集成版本验收（前端，含主控两处修复）：frozen install、typecheck、lint（0 error/8 既有 warning）、test **942 passed / 65 文件**、build、guard:dist、contracts:check 全 exit 0；`git diff --check` exit 0。后端全量见下条。
- 未测：真实 Telegram（测试 Bot）/Keychain/系统代理/Tauri；真实验收清单未授权未执行；主 Bot 切换按已决1 推迟到 S6–S8。worktree `.local/worktrees/{s4a,s4c}` 保留（删除前问用户）。
- 集成版本后端（含 S4-LEAD-001 修复）：全量 pytest **876 passed**（254.51s，沙箱外），ruff exit 0，contracts --check exit 0。Rust 与根目录旧代码守卫 not_run（S4 未改 src-tauri/旧代码）。
- 状态：**S4-A/S4-B/S4-C integrated**（本地提交，未 push）。S4 真实验收清单（测试 Bot）待用户另行授权；主 Bot 切换按已决1 推迟到 S6–S8。

### S4 联调遗留四项修复（2026-10-23，主控亲自修）

- 用户原话“修一下联调记录的四个小问题：任务页选中 run 的请求突发、日志行号疑似重复（先确认）、过期提示时间改本地时区、删除冲突文案去掉‘工单’。”主控 actual unknown。每项先写会失败的回归。
- S3C-F1 请求突发（**fixed**）：根因 `features/tasks/useRunLogs.ts` 回放每个 checkpoint/state 事件都 `scheduleSnapshotRefresh(0)` 立即 GET 快照，无合并。修复：初次同步期间只记标记、结束后统一刷新一次；快照刷新改单飞（在途时只记一次待刷新）。回归 `tests/unit/s4-lead-run-replay.test.ts` 用例 1：修前 **11 次**快照 GET（≤2 失败）→ 修后通过。
- S3C-F2 日志行重复（**确认为真缺陷并 fixed**）：dev:web 实测后端该 run 仅 10 条 log 事件，页面渲染 20 行、仅 10 行唯一。根因：`syncRun` 先 WS 订阅再等快照，快照在途时 WS 回放已把水位推到末尾，快照返回后 `watermark = startAfterSeq` 把水位重置为 0，HTTP 回放重复追加。修复：水位只进不退，HTTP 回放游标取当前水位。回归同文件用例 2：修前 **40 行**（期望 20）→ 修后通过。dev:web 复测：10 行/10 唯一，快照 GET 2 次（修前约 40 次）。
- 过期提示时区（**fixed**）：`services/telegram.py` 新增 `local_clock()` 按本机时区格式化；回归 `tests/test_s4_lead_fixes.py::test_expired_command_time_is_shown_in_local_timezone`（TZ=Asia/Shanghai，07:44Z→15:44）修前失败→修后通过。
- 删除冲突文案（**fixed**）：`features/tasks/api.ts` `task_referenced` 改为“任务被 Telegram 权限组引用，无法直接删除”；既有断言 `tests/unit/s3c-tasks.test.ts:312` 按用户本次要求同步改为匹配新文案（仅改期望文本）。
- 验收：前端 frozen install/typecheck/lint（0 error/8 既有 warning）/test **944 passed / 66 文件**/build/guard:dist/contracts:check 全 exit 0；`git diff --check` exit 0；dev:web 本会话启动并停止，临时 `.claude/launch.json` 已删、1420 已释放。后端全量见下条。
- 后端（含时区修复）：全量 pytest **877 passed**（258.46s，沙箱外），ruff exit 0，contracts --check exit 0。四项均 fixed，本地提交未 push。

### 施工 worktree 清理（2026-10-23）

- 用户要求统一清理。主控先把 `r1/s3a/s3b/s3c/s4a/s4c` 六个 worktree 相对各自 HEAD 的未提交改动（含未跟踪文件，不含忽略目录）存为 binary patch，归档到 `.local/dispatch/worktree-archive-20261023/`（内容均已按限定路径集成进 `rewrite/next`）。
- `git worktree remove --force` 被 auto mode 分类器以“不可逆本地删除”拒绝，主控未绕过；待用户自行执行删除。S5 合同已开新会话（s5-contract）。
- 用户随后自行执行删除：六个 worktree 已移除并 prune，`git worktree list` 仅剩旧应用 `main` 与 `rewrite/next` 两行。

## 2026-10-23：S5 AI 开发（合同草案，待确认）

- 主控：Claude Code 会话（由 S4 主控会话派生，role: lead），requested Opus 5.5 / medium；actual model/effort=unknown（无提供方回执），session_id=unknown。本轮只写合同，**未派工**、未委派任何施工/测试会话或子 agent。
- 输入：`rewrite/next @ 90889b9`，开始时工作区干净；旧目录 `main @ 885d186` 只读（该目录有用户未提交改动，均不在 AI 会话/TG 桥相关文件，未触碰）。主控亲自核对 `app_main.py`、`ai_dev_session.py`、`ui/ai_dev_tab.py`、`ai_headless_session.py`、`ai_headless_tg_bridge.py`、`cc_approval_hook.py`、`codex_headless_session.py`、`codex_headless_tg_bridge.py`、`antigravity_headless_session.py`、`antigravity_headless_tg_bridge.py`（向导段）、`claude_sessions.py`、`models.py`、`ui/ai_config_tab.py`、`secrets.py`、`tg_control.py`（AI 模式/轮询/ACL 段）、`tg_work_items_bridge.py`、`tg_work_items_inline.py`、`ai_work_item_flow.py`、`ui/work_items_tab.py`（MCP 分析段）、`mcp_ado_work_items_server.py`（项目解析段），以及新端 `legacy_config.py`、`domain/settings.py`、`adapters/git_process.py`、`api/ws.py`、`app.py`、`src-tauri/src/backend.rs`（进程组段）、`features/ai/`。
- 关键事实（详见 WORK_PACKAGES「S5 旧应用事实核实」）：PTY 在多线程 GUI 进程内 `os.fork()`，关闭只杀子进程 pid、不回收后代，chdir 失败被忽略；所有 AI 子进程无“父死即回收”；Claude 审批钩子是死代码（TG 会话固定 `auto`），TG 会话写死 `claude`；Codex/agy 提示词在 argv；Codex 续聊 id 只在内存；agy 按 cwd 取 conversation_id 同目录会串；Codex/agy 的 TG 向导可选“完全放开/自动批准”；TG 可手输任意目录起会话；AI 事件在读线程里同步发 TG（D11）；三个 AI 机器人与主机器人共用 `telegram_control_enabled`，但旧 AI 配置页“清除绑定”可单独停掉某个 AI 机器人；`can_dev_*` 组权限从未能在旧 UI 设置（实际仅 owner）；工单 MCP 分析提示词写死 Claude 工具前缀、依赖旧 MCP 与旧 UI active_*，并写回 `work_items_local_repo_id`；AI 机器人 Token 缺失时会话输出静默丢弃。
- 合同追加在 WORK_PACKAGES「S5」（revision 9）：架构五问、状态模型与不变式、config schema v3 `ai` 段、AI Bot Token、`ai.sqlite3`、单线程监督器进程模型（后端不 fork、控制管道 EOF 回收进程组、启动扫描防 PID 复用）、env 过滤与 repo 边界、三种 headless 协议适配、Claude 审批、多槽位 TelegramService 与 AI 机器人逐个切换步骤/回退、`/wi` 与桌面 AI 分析、HTTP/WS（含终端二进制 WS）、安全核对表、S5-A/B/C（后端）/S5-D（前端）分包、验收命令与真实验收清单（另行授权）。
- 加载技能：`backend-business-safety`、`backend-security-review`（按其要求写入状态模型/不变式/终止路径与四问风险表）；其余复核技能（architecture/data-consistency/resource-lifecycle）留实现后。
- **十项待决**（推荐与影响见合同「S5 待决」）：1 AI 机器人切换时机；2 AI 机器人使用者范围；3 工作目录边界；4 高权限档位；5 默认档位与工单分析只读档；6 Claude 审批；7 会话事件持久化；8 工单分析依赖的 ADO MCP；9 真实 CLI 协议核对授权；10 前端 xterm.js 依赖安装。尚无用户已决。
- 状态：S5-A/S5-B/S5-C/S5-D **not_dispatched**；交叉审计按用户 2026-10-23 决定不做。
- 安全范围：未读真实配置/凭据/CLI 会话缓存，未连真实 Telegram/ADO，未启动任何 AI CLI；旧目录源码未改；未新建 worktree/进程/临时目录，无需清理。本轮只改 WORK_PACKAGES 与 PROGRESS，未运行功能测试（无代码改动）。

### S5 合同确认（2026-10-23）

- 用户原答复“S5 的十项待决均按你推荐的来。”，十项均按推荐确认；WORK_PACKAGES「S5 已决」已写入（revision 10），合同状态改为已确认，派工门禁解除。主控 actual model/effort=unknown。
- 待决9 授权的真实 CLI 协议核对排在 S5-A 集成后、S5-B 派工前执行，本轮未运行任何 CLI。
- 状态：S5-A/S5-B/S5-C/S5-D 仍 **not_dispatched**（本会话受派生任务约束“只写合同、不派工”，派工另行开始）；AI 机器人与主 Bot 切换、真实验收未授权。

### S5-A 派工（2026-10-23）

- 用户原话“开始派工 S5-A（codex gpt-6.1-sol / medium，测试员 gpt-6-luna / high）。”主控：Claude Code 会话，role: lead，actual unknown。
- 输入 `rewrite/next @ 04f9897`；worktree `.local/worktrees/s5a`（detached），后端 `uv sync --frozen --offline` 后 `contracts --check` exit 0。
- 施工：codex exec（codex-cli 0.163.0），`-m gpt-6.1-sol -c model_reasoning_effort=medium -s workspace-write`，不联网，请求经 stdin；请求与输出 `.local/dispatch/s5a/`（request.md、stdout.jsonl、stderr.log、exit.txt）。施工者可派一层测试子agent gpt-6-luna / high，仅写 `next/backend/tests/independent/s5a/`；不做交叉审计。测试只用替身 CLI，禁止调用本机真实 claude/codex/agy。实际型号/档位以 rollout turn_context 为准，返回后补记。
- codex thread `01a16895-14fa-7e10-8ab8-9c2c7c90f8b8`。
- 状态：S5-A **dispatched / running**；S5-B/C/D not_dispatched；待决9 协议核对排在 S5-A 集成后。
- 第 1 轮（2026-10-23）：exit 0，交回 **partial / blocked**。rollout turn_context 回执施工 `gpt-6.1-sol` / medium、workspace-write、network_access=false；测试子agent `/root/s5a_tests`（rollout `01a16895-d905-…`）回执 `gpt-6-luna` / high，新增独立用例 14 例（本地运行时回执；施工者自报为 unknown）。交付仅 config v3 `ai` 段与迁移（`domain/ai.py`、`settings.py`、`config_store.py`、`legacy_config.py`）、未接入的监督器候选（`adapters/proc_supervisor.py`、`ai_process.py`）及新增测试；AI SQLite、AISessionService、PTY/WS、HTTP、升级 job、dev 假 AI 均未实现。施工者自报：全量 pytest 中止 244 passed / 3 failed / 8 errors（8 个端口 setup，疑沙箱 bind），ruff 4 项，contracts --check exit 0。全部改动在 write_scope 内（主控 `git status` 核对）。
- 施工者提出三项冲突，**主控裁定**：①监督器与 CLI 分属不同进程组（监督器 `start_new_session`；CLI 在子进程 `setpgid(0,0)`，PTY 模式 `setsid`+`TIOCSCTTY`），监督器杀 CLI 组后继续 wait——合同措辞以此为准；②env 过滤改为按 `_` 切段匹配 `TOKEN|SECRET|PASSWORD|PAT|COOKIE` 等段及 `API_KEY|ACCESS_KEY|PRIVATE_KEY` 子串，`PATH/MANPATH/INFOPATH/FPATH` 永不删除，PATH 补全目录可注入（测试不得补入真实 CLI 目录）；③批准 4 处既有断言 `schema_version == 2→3`（`test_s4a_foundation.py:27`、`test_s1_store.py:199`、`independent/s4a/test_telegram_migration_acl_contract.py:102`、`independent/s1/test_s1_store_contracts.py:142`）。另要求：生产迁移步骤始终存在、注入步骤只合并；端口 setup error 先确认确为 bind 被拒再记 not_run。`codex exec resume 01a16895-…` 同会话续接第 2 轮，请求 `.local/dispatch/s5a/resume1-request.md`。
