# 重构进度与署名账本

plan_id: modernization-20261021。账本允许追加证据和更正状态，不把计划中的动作当已完成。

2026-10-26：S0–S5 与阶段 0/1 的逐轮记录已原样移入 [archive/](archive/README.md)（按切片一个文件）。本文件只放状态总表、跨切片待办和当前切片记录；切片完成后其记录移入 archive，总表留一行。

## 切片状态总表

| 切片 | 状态 | 真实验收 / 所有权切换 | 归档 |
| --- | --- | --- | --- |
| 阶段 0/1 | WP-00/01/02 passed；WP-11/12 已在 `main` 热修并推送（`885d186`）；WP-03 cancelled；WP-13→S1、WP-14→S6、WP-15→S3 | — | [progress/phase0-1.md](archive/progress/phase0-1.md) |
| S0 骨架 | integrated | 托盘/关窗/⌘Q 等人工未测 | [progress/S0.md](archive/progress/S0.md) |
| S0.5 方向 E 换皮 | integrated（后被 R1 方向 B 取代） | — | [progress/S0.5.md](archive/progress/S0.5.md) |
| S1 设置与凭据 | integrated；交叉审计闭环 | 真实 Keychain 未测 | [progress/S1.md](archive/progress/S1.md) |
| S2 工单 | integrated；交叉审计闭环 | 真实 ADO 未测（含 CR-NEXT-004） | [progress/S2.md](archive/progress/S2.md) |
| S3 任务执行 + R1 换皮 | integrated | 真实验收清单未授权 | [progress/S3.md](archive/progress/S3.md) |
| S4 Telegram | integrated | 测试 Bot 真实验收未授权；主 Bot 切换推迟到 S6–S8（S4 已决1） | [progress/S4.md](archive/progress/S4.md) |
| S5 AI 开发（含 S5-E） | integrated；集成验收通过 | 真实验收清单与三个 AI 机器人切换未授权 | [progress/S5.md](archive/progress/S5.md) |
| S6 MCP 管理 | 合同已确认；S6-0 done；S6-A、S6-B、S6-C integrated（`rewrite/next` 本地提交，未 push）；S6 集成验收待做（安全核对用 Opus） | Lark 切换未授权 | 本文件下方 |
| S7 服务管理 / S8 VPN / S9 交付 | not_started | — | — |

最近一次集成版本全量（S5-E 集成，`1391e32`）：后端 **1136 passed**、ruff、contracts --check；前端 frozen install/typecheck/lint/test **1129 passed / 80 文件**/build/guard:dist/contracts:check；Rust `cargo test --offline` 36 passed（S5 集成验收时）。

## 跨切片待办（从归档汇总；细节查对应 archive 文件）

真实验收与切换（均需用户另行授权）：

- S2：真实 ADO 列表/详情/评论/附件；CR-NEXT-004（附件是否 302 到跨源 CDN，属实则追加受信策略小包）；I-5、I-7。
- S3：真实 SSH push、ADO 构建/发布/回滚（清单见 archive/work-packages/S3.md）。
- S4：测试 Bot 真实验收；主 Bot 所有权切换（S6–S8 期间择时）。
- S5：真实验收清单（含 Codex `none`/`max` 档、`-m`、TERM 后续聊、Claude 审批 allow 回包、agy stdin 格式）；三个 AI 机器人逐个切换；dev:web 未手工走通的 TG `/cc`、`/wi` AI 分析、桌面工单 AI 分析。
- 通用：Tauri 内人工走查（托盘、关窗常驻、Overlay 拖拽、多分辨率）。

未关闭的发现（最后一次记录的状态）：

| finding_id | 状态 | 说明 |
| --- | --- | --- |
| CR-NEXT-001 | open | 旧代码基线测试 0.2s 超时偶发失败，不影响生产 |
| CR-NEXT-003、CR-NEXT-005 | deferred | 旧应用内的问题，旧应用下线即消失 |
| CR-NEXT-004 | open（待真实验收） | 见上 |
| S0A-005 | deferred | 不读的 WS 客户端收不到 4408 关闭帧 |

2026-10-26 主控核对代码后关闭（`rewrite/next @ 5ae038e`）：

| finding_id | 状态 | 证据 |
| --- | --- | --- |
| S0A-006 | fixed（S1-A） | `api/ws.py:203-206`、`api/ai_routes.py:156` 无 Origin 或不在白名单即 1008 关闭；回归 `tests/test_s1_settings.py::test_no_origin_rejected_before_accept_without_network`、`tests/independent/s1/test_s1_live_boundaries.py::test_websocket_handshake_without_origin_is_rejected` |
| S0A-007 | fixed（S1-A） | `api/middleware.py:66` 全局 `BodyLimit`（`app.py:268`，Host→CORS→Auth→BodyLimit），超限 413，覆盖 `/api/system/alert`；回归 `tests/independent/test_fault_http.py:210` |
| S05-004 | obsolete | 导航角标已无 `aria-label` span，计数作为 `RouterLink` 文本读出（`components/Sidebar.vue:86-91`）；审批快捷键改由 `ChatView.vue` 处理，仅焦点在该会话内且有一条待审批时响应。旧 `components/ApprovalBar.vue` 仍挂 window 监听但已无引用（死代码，可删） |

本次只核对代码与既有测试，未重跑测试。

资源：施工 worktree 仅剩 `.local/worktrees/s5e`（删除前问用户）；`.local/cargo-target` 约 4 GB 等 git 忽略目录保留。

## 2026-10-24：S6 合同草案（主控）

- 主控 actual unknown（Claude Opus 5.5 会话，lead）。输入 `rewrite/next @ 1a5548d`。
- 主控只读核实旧应用 `main @ 885d186` 的 ADO/Lark/Figma MCP 托管事实（文件与行号写入 WORK_PACKAGES「S6 旧应用事实核实」），未读真实配置/凭据/CLI 配置/lark-mcp 存储，未连真实服务，未启动旧应用 MCP 或 node/npx。
- 关键新发现：①ADO/Figma 的应用“启动”进程不服务任何客户端（CLI 各自 spawn stdio）；②Lark 登录把 App Secret 放进 argv（`app_lark/mcp_server_manager.py:333–337`）；③lark-mcp 令牌存储是全局 `storage.json`，新旧应用天然共用；④Bearer 注入把 UAT 明文写进三家 CLI 配置；⑤Node 下载无校验、解包无过滤；⑥lark-mcp/figma 包未锁版本（D13）。
- 合同写入 WORK_PACKAGES「S6」：架构五问、config v4、凭据、ADO server、stdio 有界自检（D08）、Lark 托管与端口预检/补丁标记、Figma wrapper、Node/npm、接入片段与 S5 分析来源切换、HTTP/WS、安全核对表、S6-0/A/B/C 分包、集成验收、真实验收清单、Lark 所有权切换步骤、待决 11 项。
- 状态：S6 **待用户确认待决**，未派工。

### S6 合同确认（2026-10-26）

- 用户原答复“S6 待决 1–11 全部按推荐，写入 S6 已决并提交，然后做 S6-0。”；WORK_PACKAGES「S6 已决」已写入（revision 11）。主控 Claude Opus 5.5 会话（actual effort unknown）。

### S6-0 协议与版本核对（2026-10-26，主控）

- 主控 Claude Opus 5.5 会话（actual effort unknown），无子 agent。输入 `rewrite/next @ c8f0668`。授权依据：S6 已决 1。
- 做了什么：会话 scratchpad 临时前缀 `npm install --ignore-scripts`（仅 npm registry）两包最新版；`lark-mcp --help`/`mcp|login|logout --help`、`figma-developer-mcp --help`；读 lark-mcp 源码；离线运行：旧 Lark 补丁加载探针、`lark-mcp mcp -m streamable --oauth`（假 app id/secret，随机端口）健康探针与 SIGTERM、figma `--stdio` 握手 + `tools/list`（假 key、遥测关）。全部以临时 HOME 运行，`keytar` 用假模块拦截，未访问真实 Keychain、未登录、未调 Lark/Figma API；真实 `~/Library/Logs/lark-mcp-nodejs` 无今日新文件。
- 结论写入 WORK_PACKAGES「S6-0 结论」13 条；锁文件 `next/backend/resources/mcp/{package.json,package-lock.json}`（lark-mcp 0.5.1、figma-developer-mcp 0.13.2，238 包）。
- 对合同的影响（已写入结论，优先于上文）：login 用 `APP_SECRET` 环境变量即可；子进程 cwd 改为专用空目录（防 `.env` 注入）；保留 `--debug` 并脱敏 authorization code；`refresh_failing` 不依赖 20038；Node 下限 20.20.0、托管固定 v24.13.0；keytar 需 `npm rebuild keytar`（GitHub Releases 预编译，registry 之外唯一联网点）且存储不可用要标 degraded；登录窗口实为 60 秒；Figma 必须关遥测并显式 `--image-dir`。
- 新发现：

| finding_id | 级别 | 问题与核实 | 处置 |
| --- | --- | --- | --- |
| S6-LEAD-001 | major | 旧 `app_lark/lark_mcp_singleflight.js:74–78` 以请求字符串预过滤，`require("./oidc")` 不命中，服务模式下 `verifyAccessToken` 补丁从未生效且无提示（`require.cache` 探针复现；加 `oidc` 关键字后生效） | 用户 2026-10-26 原话：“旧应用不修 S6-LEAD-001，按已决11 等 S6 切换后由新端解决。” → 旧应用不热修；新端补丁按解析后路径判定 + 结果标记，S6-B 补“以相对路径 `./oidc` 加载”的回归 |
| S6-LEAD-002 | minor | lark-mcp 授权失败日志写出 authorization code（`auth/handler/handler.js:53`） | 新端托管读任务脱敏；lark-mcp 自己的日志文件无法控制，记风险 |

- 未测：`npm rebuild keytar` 的真实下载/编译；真实 Lark 登录、刷新、20038；Figma 真实 API 与限流；新 node 路径首次访问 `lark-mcp` Keychain 条目是否弹窗。
- cleanup：scratchpad 临时安装目录（约 224 MB，含临时 HOME 与日志）已删除；无残留进程。

### S6-A 后端派工与集成（2026-10-26，lead = Claude Sonnet 5.5 会话，actual effort unknown）

- 输入 `rewrite/next @ 758ccea`。施工：codex exec（codex-cli 0.163.0），requested `gpt-6.1-sol`/medium，`-s workspace-write`，不联网；worktree `.local/worktrees/s6a`（detached `758ccea`）；请求/输出 `.local/dispatch/s6a/`（request.md、stdout.jsonl、stderr.log、exit.txt、last-message.txt；续接 resume1-request.md、stdout2.jsonl、last-message2.txt）。thread `01a175b3-e33a-7cc1-9ea2-0e207965d2ee`，actual model/effort unknown。测试子 agent `/root/s6a_tests`（requested gpt-6-luna/high，actual unknown）新增 `tests/independent/s6a/` 9 例；施工者自写 `tests/test_s6_{ado,config,http,prompt,runner}.py`。不做交叉审计。
- 第 1 轮施工者按升级条件停下：既有替身 `lark_settings.yaml` 的 `domain: lark` 不是合法 https 域名，迁移 409。**lead 裁定（实施细节，不改合同）**：旧应用只有 `DEFAULT_DOMAIN=https://open.larksuite.com`，无 `lark` 简写；`imported.lark/figma` 迁入 `mcp.*` 时任一字段非法（domain/port/tools 等）回退该字段默认值，迁移不失败，日志只记字段名，`imported.*` 原样保留。第 2 轮（同 thread 续接；首次续接因给 `resume` 传了不支持的 `-s` 而 exit 2，未产生改动）补该规则回归（修前 13 failed、1 passed）、README S6-A 段并自检。
- 对合同的解读（已写入请求）：Figma 自检路由与 wrapper 属 S6-B，S6-A 只交通用自检 runner（命令 spec 入参，假 server 覆盖）；策略基线导入路径由请求参数给出，代码不硬编码旧仓库路径。
- 变更：38 个文件（`next/backend/src/**`、`tests/**`、`README.md`、`next/contracts/openapi.json`）：config v4 与规范化迁移；`domain/mcp.py`；`mcp/{ado_server,cache,policy,runner}.py`+`tools.json`；`api/mcp_*`、`services/mcp.py`；`proc_supervisor` 共享监督函数；`ai_prompt` 来源前缀切换与确认字段。既有断言变更共七处 `schema_version 3→4`：`test_s1_store.py:199`、`test_s4a_foundation.py:27`、`test_s5a_config.py:20`、`test_s5a_regressions.py:28`、`independent/s1/test_s1_store_contracts.py:142`、`independent/s4a/test_telegram_migration_acl_contract.py:102`、`test_s4_lead_fixes.py:12`（`CURRENT_SCHEMA_VERSION`）；其余断言未改。
- 施工者沙箱内：分组 pytest 889 passed、311 项因端口/监督器 `PermissionError` not_run（交主控沙箱外）。
- **lead 沙箱外验证（集成版本 = 758ccea + `integration.patch`，限定路径 binary patch，应用前 `git apply --check`、基线干净）**：`next/backend`：`.venv/bin/python -m pytest -q` exit 0，**1200 passed**（S5-E 基线 1136，+64）；`.venv/bin/ruff check .` All checks passed；`python -m toolbox_backend.contracts --check` exit 0；`git diff --check` exit 0。施工 worktree 版本全量曾 1 failed/1199 passed：`tests/independent/s5c/test_s5c_projection.py::test_flood_is_bounded_and_turn_still_completes`（`1508 < 1500` 计数断言，负载时序，与 S6 无关）；单独在 worktree 与基线各跑 2 次均过，集成版本全量过，记为偶发（未改）。
- lead 抽查（非完整安全核对）：ado_server 三信号/ppid、写工具开关与 tools/list 过滤、cache `O_NOFOLLOW/O_EXCL/0600`、runner 环境剔除 `NODE_OPTIONS/APP_*` 与专用 cwd 均在代码中可见；**安全核对表与 resource-lifecycle 逐项核对留给 S6 集成验收（Opus）**。
- not_run / 未测：前端（本包未改）；真实服务/Keychain/CLI/联网；Pillow 不在依赖中，附件图片压缩跳过；全局进程表零残留未核（沙箱）。S6-B 须补：Figma 自检路由、`./oidc` 相对路径补丁回归、keytar/安装 job 等。
- cleanup：施工 worktree `.local/worktrees/s6a` 保留（S6-B 可复用，删除前问用户）；`/private/tmp/s6a-*.txt` 为施工者复跑清单；无已知残留进程；误启的一条挂起 shell（lead 命令笔误）已终止。

### S6-B 后端派工与集成（2026-10-26，lead = Claude Sonnet 5.5 会话，actual effort unknown）

- 输入 `rewrite/next @ 8b6e446`。**用户因额度紧张指定**施工改用 Gemini 4（不再用 codex）且不派测试子 agent：agy `--model gemini-4-argon-medium --effort medium --sandbox --output-format stream-json --print`，conversation `28c0b751-f866-4301-842b-8e005018cd72`（init 事件回报 model `gemini-4-argon-medium`，其余 actual 视为 agy 回执；effort 以 requested 为准）；worktree `.local/worktrees/s6b`（detached `8b6e446`）；请求/输出 `.local/dispatch/s6b/`（request.md、stdout.jsonl、exit.txt；续接 resume1-request.md、stdout2.jsonl、exit2.txt）。回退候选：Sonnet 5.5（未用到）。无独立测试子 agent：施工者自测，`verified_by=executor, independent=false`；不做交叉审计。
- 第 1 轮（约 88 分钟）施工者自报全部通过（沙箱内）；lead 沙箱外全量：3 failed、1216 passed、1 skipped、7 errors。原因：①`mcp/runtime.py` 模块级 `LOCKED_PACKAGES = package_versions()` 导入期读 `resources/mcp/package.json`，`test_fault_contracts.py` 拷贝 `src` 到临时目录无 resources → 契约故障套件 1 failed + 7 errors；②`test_lark_login_busy_cancel_timeout_success_logout_and_token_status` 稳定 409 `mcp_port_in_use`；③`test_lark_health_probe_marks_unhealthy_after_3_failures` 全量中时序不稳（健康循环硬编码 sleep、未用注入的 `svc.health_sleep`）。这些在施工者沙箱（禁 loopback connect、`/bin/ps`）内不可见。
- 第 2 轮（同会话续接，约 107 分钟）修复；lead 复跑 `test_fault_contracts.py` 与全量均通过。
- 变更：13 个已修改 + 新增 10 个文件（`mcp/{runtime,lark_logs,figma_wrapper}.py`、`resources/mcp/{lark_mcp_patches,figma_mcp_concurrency}.js`、`services/mcp.py`、`api/mcp_*`、`ws.py`/`events.py`/`domain/models.py`（`mcp` 主题）、`services/telegram{,_commands}.py`、README、`next/contracts/{openapi,events.schema}.json`、`tests/test_s6b_{figma,lark,patches,runtime,ws_tg}.py`）。既有断言：无变更。lead 修正 `git diff --check` 的 3 处文件尾空行（纯空白）。
- **lead 沙箱外验证（集成版本 = 8b6e446 + `integration.patch`，限定路径 binary patch，`git apply --check` 通过、基线干净）**：`next/backend`：`pytest -q` exit 0，**1228 passed、1 skipped**（S6-A 基线 1200，+28）；`ruff check .` All checks passed；`contracts --check` exit 0；`git diff --check` exit 0。唯一 skip 是 `test_lark_patch_relative_oidc_and_singleflight_with_node_fixture`（测试只在 `/opt/homebrew`、`/usr/local`、`/usr/bin` 找 node，本机 node 在 nvm 下）；lead 以临时副本（仅在候选路径加入 `~/.nvm/.../v24.13.0/bin/node`，运行后已删除）单独跑该文件：3 passed——`require("./oidc")` 加载下三个补丁标记均 applied，S6-LEAD-001 回归在真实 node 下生效。该 skip 属测试环境缺陷（可后续放宽候选路径，未改）。
- 未测 / 未核：Lark/Figma 真实进程与真实 keytar/`npm rebuild`/Node 下载；真实 `GET /mcp` 405（lark 假替身已覆盖，真实 TCP 用例在沙箱外通过）；`/bin/ps` 全局零残留；`run_in_terminal` 未做。**安全核对表与 resource-lifecycle 逐项核对（argv/env/日志无密钥、SIGKILL 零残留、关闭点清单）留给 S6 集成验收（Opus）。** 前端 S6-C 未派。
- cleanup：worktree `.local/worktrees/s6a`、`.local/worktrees/s6b` 保留（删除前问用户）；临时 `tests/_tmp_s6b_patches_node.py` 已删；施工者 `/tmp/s6b_isolated_src_check` 已删。

### S6-C 前端派工与集成（2026-10-26，lead = Claude Sonnet 5.5 会话，actual effort unknown）

- 输入 `rewrite/next @ 9ffedba`。施工：agy `--model gemini-3.8-flash-high --effort high --sandbox --output-format stream-json --print`，conversation `21a9be88-6ca3-488d-a5dc-1c28741acf43`（init 回报 model `gemini-3.8-flash-high`；effort 为 requested）；worktree `.local/worktrees/s6c`（detached `9ffedba`）；请求/输出 `.local/dispatch/s6c/`（request.md、stdout.jsonl、exit.txt）。**用户规则（2026-10-26）：Gemini 4 只跑后端，前端用 Gemini 3.8 Flash high**；本包最初误用 `gemini-4-argon-medium` 启动，数分钟内被叫停并 TaskStop，worktree 无施工改动，重派（`aborted-gemini4-stdout.jsonl` 保留）。无独立测试者：施工者自测，`independent=false`；不做交叉审计。
- 施工者在 agy print 中途以“等待测试”结束（无最终报告，疑似超时截断，exit 0），lead 沙箱外自行完整验收。lead 在施工前重新生成 `src/api/schema.d.ts`（`pnpm contracts:gen`，随集成）。
- 变更：22 个文件（`next/desktop/src/**`、`tests/**`）：设置页「MCP」分区（`McpTab.vue`、`McpAdoCard/McpLarkCard/McpFigmaCard.vue`、所有权/写工具确认/来源切换 3 个 Sheet、`useMcp.ts`）、`events.ts`/`backend-runtime.ts` 的 `mcp` 主题订阅、`settings/api.ts` 错误码文案、`AiCliTab.vue` 保存时带 `ack_cli_registered:false` 与 `mcp_source` 透传（后端仅在 legacy→toolbox 时要求确认，已核对 `ai_sessions.py:253`）、新测试 `tests/unit/s6c-mcp.test.ts`（12 例）。既有断言变更：页签数 `settings-independent.test.ts`（tabindex 数组 7→8 项）、`settings.test.ts`（页签清单加入「MCP」）。
- **lead 发现并处理的既有问题（非 S6-C 引入）**：基线（`rewrite/next @ 9ffedba`，未改前端）前端测试已 12 failed——`r1-pages`、`s5d2-chat`、`s1c-ui`、`e-controls` 四个文件的审批事件夹具默认时间戳写死 `2026-10-24T09:00:00Z`，而 `ChatView.vue` 审批倒计时 TTL 仅 540 秒，时钟越过该时刻后必然失败（S5-E 集成时钟尚早于该时间戳，故当时通过）。施工者为此在生产代码 `ChatView.vue` 加“elapsed>3600 则归零”的 hack，**lead 已还原（生产代码未改）**，改为把这四个文件夹具的 `ts` 默认值改为 `new Date().toISOString()`（共 4 行，断言未改）。
- **lead 沙箱外验证（集成版本 = 9ffedba + `integration.patch`，限定路径 binary patch，`git apply --check` 通过、基线干净）**：`next/desktop`：`pnpm install --offline --frozen-lockfile` 0、typecheck 0、lint 0、test 0（**81 文件 / 1141 passed**，S5-E 基线 1129 + 12）、build 0、guard:dist 0、contracts:check 0；`git diff --check` 0。后端、Rust 本包未改未跑（后端 S6-B 版本 1228 passed 仍有效）。
- lead 抽查：错误码文案齐全（`api.ts:154–158`）、凭据输入 `type=password autocomplete=off` 且提交后清空、所有权 Sheet/`ack_old_app_stopped`、写工具二次确认、来源切换确认、`mcp` 订阅卸载释放均有对应代码与测试。附件缓存“清空”后端无接口，UI 如实标“暂无清空接口”。
- 未测：dev:web / Tauri 内真实走查与视觉（R1 风格、响应式）；WS 重连与回放水位真实后端联调；Lark/Figma 真实流程。**S6 集成验收（Opus）**：安全核对表、resource-lifecycle、dev:web 端到端（假 ADO + 假 node/lark-mcp）、迁移/改进/推迟清单对照旧 `docs/capabilities/mcp-servers.md`。
- cleanup：worktree `s6a/s6b/s6c` 保留（删除前问用户）；无残留进程已知。
