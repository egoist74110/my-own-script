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
