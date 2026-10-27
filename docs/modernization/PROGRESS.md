# 重构进度与署名账本

plan_id: modernization-20261021。账本允许追加证据和更正状态，不把计划中的动作当已完成。

2026-10-26：S0–S6 与阶段 0/1 的逐轮记录已原样移入 [archive/](archive/README.md)（按切片一个文件）。本文件只放状态总表、跨切片待办和当前切片记录；切片完成后其记录移入 archive，总表留一行。

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
| S6 MCP 管理 | integrated；集成验收通过（有条件：S6-ACC-001～008 fixed，009～013 deferred，其中 009 待前端派工） | 真实验收清单未授权；Lark（真实包补丁核对、所有权切换）用户搁置，后续再议 | [progress/S6.md](archive/progress/S6.md) |
| S7 服务管理 | integrated；集成验收通过（有条件：S7-ACC-001～003 fixed，004/005 deferred；dsh 已推迟出 S7） | 真实验收清单与服务所有权切换未授权；真实 cloudflared 输出格式待核（S7-ACC-001） | [progress/S7.md](archive/progress/S7.md) |
| S8 VPN | integrated；集成验收有条件通过（`583410c`/`036bde6`/`c902c2c`/`3cae809`；Opus 安全核对 M1–M3 已修，L1–L10 记账） | 真实验收清单（新品牌 SSO/窗口 OCR/深链/客户端 A·B 档）、所有权切换与主 Bot 切换未授权 | 见下「S8-A/B/C 施工与集成验收」 |
| S9 交付 | 合同已确认（[WORK_PACKAGES.md「S9」「S9 已决」](WORK_PACKAGES.md)，11 项按推荐）；S9-A 已集成，S9-B/C 待派 | 真实签名/公证/发布/旧应用下线均未授权；本机无签名身份 | — |

最近一次集成版本全量（S7 集成验收，`a3bd7b3`/`93fca54` + 验收修复）：后端 **1307 passed**、ruff、contracts --check；前端 **1162 passed / 82 文件**（frozen install/typecheck/lint/test/build/guard:dist/contracts:check）；Rust 未改（上次 `cargo test --offline` 36 passed）。

此前（S6 集成验收，`6a00fc2` + 验收修复）：后端 **1242 passed**、ruff、contracts --check；前端 frozen install/typecheck/lint/test **1141 passed / 81 文件**/build/guard:dist/contracts:check；Rust `cargo test --offline` 36 passed。

## 跨切片待办（从归档汇总；细节查对应 archive 文件）

真实验收与切换（均需用户另行授权）：

- S2：真实 ADO 列表/详情/评论/附件；CR-NEXT-004（附件是否 302 到跨源 CDN，属实则追加受信策略小包）；I-5、I-7。
- S3：真实 SSH push、ADO 构建/发布/回滚（清单见 archive/work-packages/S3.md）。
- S4：测试 Bot 真实验收；主 Bot 所有权切换（S6–S8 期间择时）。
- S5：真实验收清单（含 Codex `none`/`max` 档、`-m`、TERM 后续聊、Claude 审批 allow 回包、agy stdin 格式）；三个 AI 机器人逐个切换；dev:web 未手工走通的 TG `/cc`、`/wi` AI 分析、桌面工单 AI 分析。
- S6：真实验收清单（archive/work-packages/S6.md「真实验收清单」：运行组件安装含 `npm rebuild keytar` 与 Node 下载、三家 CLI 注册 `toolbox_ado`/`toolbox_figma` 与真实调用、Lark 所有权切换与闲置 >2 小时续期、强杀回收）；Lark 相关（真实包补丁核对、所有权切换、续期）用户 2026-10-26 原话“lark暂时不用验，反正也不用了（暂时不怎么需要了，后续再说”→ 搁置，重启时**首先确认新补丁在真实 lark-mcp 0.5.1 上三项标记均为 applied**（S6-ACC-001）；剪贴板复制、桌面“AI 分析”会话启动（dev:web 未走通）。
- S7：真实验收清单（archive/work-packages/S7.md「真实验收清单」，dsh 项已推迟）：真实 code-server 启停/`external`、真实 cloudflared quick tunnel 与自定义隧道（**先核对真实输出里域名所在行的格式，S7-ACC-001**）、TG 服务菜单（测试 Bot）、回收；所有权切换：旧应用里手动关闭 code-server/cloudflared（旧端 detached 服务不会随旧应用退出而停）。dsh 整体推迟（用户 2026-10-26），恢复时另起切片，S7-0 结论见归档。
- 通用：Tauri 内人工走查（托盘、关窗常驻、Overlay 拖拽、多分辨率）。

未关闭的发现（最后一次记录的状态）：

| finding_id | 状态 | 说明 |
| --- | --- | --- |
| CR-NEXT-001 | open | 旧代码基线测试 0.2s 超时偶发失败，不影响生产 |
| CR-NEXT-003、CR-NEXT-005 | deferred | 旧应用内的问题，旧应用下线即消失 |
| CR-NEXT-004 | open（待真实验收） | 见上 |
| S0A-005 | deferred | 不读的 WS 客户端收不到 4408 关闭帧 |
| S6-ACC-010 | deferred | mcp 事件历史存完整快照（含 log_tail），最坏约 64 MiB |
| S6-ACC-011 | deferred / 接受 | 运行组件：`node --version` 探测不经监督器；下载无大小上限、取消不中断传输；SHASUMS 同源无 GPG；`.staging-*` 残留 |
| S6-ACC-012 | deferred | Figma wrapper 生产代码保留 `_MCP_MEM_FIGMA` 测试入口 |
| S6-ACC-014 | deferred | Lark 启动后补丁标记只等 5×20 ms（`services/mcp.py:634–638`），负载下间歇误报 `running_degraded`，`test_s6b_lark.py::…unhealthy_after_3_failures` 间歇失败；建议改为有界事件等待（≤2 秒） |
| S7-ACC-004 | deferred | 自定义隧道日志 `cloudflared-<uuid>.log` 删除隧道后不清理，长期累积 |
| S7-ACC-005 | deferred | 服务页首次打开后网络刷新循环常驻（每 5 秒短命 `ifconfig`），不随页面关闭停止 |

2026-10-26 主控核对代码后关闭（`rewrite/next @ 5ae038e`）：

| finding_id | 状态 | 证据 |
| --- | --- | --- |
| S0A-006 | fixed（S1-A） | `api/ws.py:203-206`、`api/ai_routes.py:156` 无 Origin 或不在白名单即 1008 关闭；回归 `tests/test_s1_settings.py::test_no_origin_rejected_before_accept_without_network`、`tests/independent/s1/test_s1_live_boundaries.py::test_websocket_handshake_without_origin_is_rejected` |
| S0A-007 | fixed（S1-A） | `api/middleware.py:66` 全局 `BodyLimit`（`app.py:268`，Host→CORS→Auth→BodyLimit），超限 413，覆盖 `/api/system/alert`；回归 `tests/independent/test_fault_http.py:210` |
| S05-004 | obsolete | 导航角标已无 `aria-label` span，计数作为 `RouterLink` 文本读出（`components/Sidebar.vue:86-91`）；审批快捷键改由 `ChatView.vue` 处理，仅焦点在该会话内且有一条待审批时响应。旧 `components/ApprovalBar.vue` 仍挂 window 监听但已无引用（死代码，可删） |

本次只核对代码与既有测试，未重跑测试。

资源：施工 worktree 剩 `.local/worktrees/s5e`、`s7a`、`s7c`（删除前问用户）；`s6a/s6b/s6c` 经用户 2026-10-26 同意已删除（删除前核对：未提交内容均已在 `8b6e446`/`9ffedba`/`6a00fc2` 中，唯一差异是集成时去掉的文件尾空行）；`.local/cargo-target` 约 4 GB 等 git 忽略目录保留。

## S8 合同草案（2026-10-26）

- 角色：主控（lead）；requested/actual：Sonnet 5.5（会话系统提示自述，无提供方回执，证据等级同前）；无子 agent、无派工。
- 输入：新版 `rewrite/next @ 82a6904`；旧版 `main @ 885d186`；AGENT_WORKFLOW/ARCHITECTURE/MIGRATION_PLAN、旧 `docs/capabilities/vpn.md`、项目记忆 harmony-vpn-automation、S4 已决1、S5/S6/S7 监督器与服务样板。
- 只读核对范围：旧 `app_ado/vpn_control.py`、`vpn_login.py`、`vpn_totp.py`、`vpn_update.py`（结构与关键函数）、`vpn_ip.py`、`secrets.py` VPN 段、`tg_control.py` `/vpn` 与 `svc:vpn`、`tg_help_inline.py`、`ui/services_tab.py` VPN 卡（均无未提交改动）；本机客户端 `Info.plist`、`ps`、`ifconfig`（只读）；新端 `site-packages`（确认无 playwright/pyobjc/pyotp）。**未**读真实配置/凭据/Ente 导出，未启动/停止任何 VPN 或浏览器，未点击，未联网。
- 关键新发现（详见合同「S8 事实核实」）：
  1. **客户端已改名为 `Check Point SASE`（13.1.0，bundle id `com.safervpn.osx.smb`）**，旧代码把 “Harmony SASE” 硬编码在 `pgrep`/`open -a`/`osascript`/OCR 窗口筛选里 → 在 13.1.0 上 `app_running()` 恒 False、窗口自愈整体失效；只有“读 utun 10.254 是否已连”仍然有效。URL scheme 仍同时注册 `HarmonySASE` 与 `CheckPointSASE`。新品牌下 SSO 入口/选择器/`redirectUrl` 未验证。
  2. 旧端自愈全程同步 `sleep`、无取消、无并发保护（可同时起多个 Chrome 登录）；A/B 档靠 `pkill -f`。
  3. 回调深链（含 id_token JWT）经 `open <url>` 进 argv 且每 8 秒重发；日志写深链前缀与页面控件 dump。
  4. TOTP 导入由服务端读用户给的路径并无论成败 `unlink`（等于替用户删任意文件），多条匹配静默取第一条；UI 配置对话框回填明文密码。
  5. 窗口自动化需屏幕录制/辅助功能，合成点击会移动真实鼠标，`surface_app` 周期抢前台；新后端无 pyobjc/playwright 依赖，需新增并锁定（待决1）。
- 产物：[WORK_PACKAGES.md「S8」](WORK_PACKAGES.md)（事实核实、S8-0 本机核对计划、架构五问、config v6、凭据与 TOTP、客户端控制、窗口自动化、登录 worker、连接运行模型、接口、安全核对表、S8-A/B/C 分包与模型分工、集成验收、真实验收清单、所有权切换步骤、10 项待决）。
- 状态：合同草案，**待用户确认「S8 待决」**；确认前不派工，不授权 S8-0、依赖锁定联网、真实验收、所有权切换与主 Bot 切换。
- not_run：未重跑测试（只写文档）；新品牌 SSO 页面、窗口文案、深链 scheme 有效性均未实测。

## S8-0 本机核对（2026-10-26）

- 角色：主控（lead）；requested/actual：Sonnet 5.5（会话系统提示自述，无提供方回执，证据等级同前）；无子 agent、无派工。基线 `rewrite/next @ 025338a`。
- 方法：scratchpad 独立 venv/uv 项目（仓库 `pyproject.toml`/`uv.lock` 未改）；Playwright 驱动系统 Chrome 155.0.8059.40 开回环假 SSO 页 + 假 scheme `s8probe://`，headless 与 headed 各用新临时 profile 两轮；`ps -axo pid,ppid,pgid` 按记录 PID 树核对；fork+setpgid+exec 复现 supervisor 子进程组语义，做 SIGKILL worker / killpg TERM→KILL / killpg KILL（headless+headed）回收实验；`lsof -i` 观察 Chrome 首次启动外联；scratchpad 内 `uv lock/sync` 解析并实测 `pyobjc-framework-ApplicationServices==12.2.2`。
- 只读/联网范围：只读 `proc_supervisor.py`/合同；联网仅 `uv` 解析/下载（已授权）与系统 Chrome 自身后台外联（观察到，非主动访问）；未访问真实站点/SSO、未登录、未读真实配置/凭据/Ente 导出、未点击/退出/重启 Check Point SASE（全程保持已连接）、未用任何真实 scheme。
- 结果：结论与合同修订已写入 [WORK_PACKAGES.md「S8-0 结论」](WORK_PACKAGES.md)；要点：补依赖 ApplicationServices；窗口 owner name=`Check Point SASE`（按 PID 筛）；headless/headed 手法全通过（捕获事件会重复触发需去重）；Chrome 自成进程组但随管道 EOF 自行退出，三种强杀场景零残留，仍保留精确 PID 兜底；Chrome 新 profile 自行外联 Google，加禁后台联网参数；可派 S8-A。
- 清理：本任务启动的 Chrome/worker 均已回收，`ps` 无残留；scratchpad 临时 profile 保留。
- not_run：未重跑仓库测试（只改文档）；新品牌 SSO 页面/真实窗口 OCR/授权后权限行为均未实测。

## S8-A/B/C 施工与集成验收（2026-10-27）

- 角色：主控（lead）；requested/actual：Sonnet 5.5（会话系统提示自述，无提供方回执）。后端 worker：codex `gpt-6.1-sol` medium（命令行指定，无提供方回执，actual 记 unknown）；前端 worker：agy `gemini-3.8-flash-high`（同上）。安全只读核对：Opus 子 agent（requested=opus，actual unknown）。
- 提交（本地，未 push）：S8-A `583410c`；契约缺口修复 `036bde6`（typed vpn WS 事件/client 视图、`DELETE /api/vpn/browser-profile`）；S8-B + S8-C `c902c2c`（含 worker cwd `Path` 未序列化的修复）。
- 验证（沙箱外，主控亲跑）：S8 子集 149 passed / 2 skipped（`real_chrome` 需 `-m real_chrome`）；`real_chrome`（回环假页，headless+headed）2 passed，无 Chrome 残留；ruff、契约 `--check` 通过；前端 typecheck/lint/test(1173)/build/guard:dist/contracts:check 全过。全量后端 pytest（不带 -x）：1439 passed、2 skipped（`real_chrome`）、1 failed——失败的是已知间歇用例 `test_s6b_lark.py::test_lark_health_probe_marks_unhealthy_after_3_failures`（S6-ACC-014，与 S8 无关）。
- 主控修掉的问题：worker `cwd` 为 `Path` 导致 JSON 序列化失败（真实 worker 起不来，被沙箱跳过的测试暴露）；`real_chrome` 测试两处错误期望（scheme 小写、回环页导航与 cookie max-age）；前端 3 个测试（Teleport 的 Sheet 需从 body 查、s7c 无密码断言排除 VPN 卡）。
- Opus 只读安全核对结论：**无严重缺陷，有条件通过**。秘密外泄、进程回收（无 pkill/shell=True，信号仅限校验 PID+lstart+profile 的对象）、深链（scheme 枚举，不可投递任意 URL）、鉴权/单飞/DELETE 路径安全均未发现问题。待处理：
  | 级别 | 项 | 状态 |
  |---|---|---|
  | 中 M1 | worker 环境未剔除 `PLAYWRIGHT_*`/`NODE_OPTIONS`（合同要求）`adapters/vpn_browser.py:259-265` | fixed（S8-D） |
  | 中 M2 | 已连接时 `relogin` 不会真重登（档 A 见隧道即成功）`services/vpn.py:460-475,517` | fixed（S8-D，relogin 直进档 C，登录后重探测隧道；不证明隧道曾重建） |
  | 中 M3 | TG `/vpn on` 缺“需先在桌面端配置”判断，忙时 `vpn_busy` 被吞、无回复 `telegram_commands.py:527,668`、`telegram.py:688` | fixed（S8-D，命令与菜单共用前置检查；修前忙时回泛化“操作失败”而非完全静默） |
  | 低 L1 | worker cwd 用 data_dir 而非 `<data-dir>/vpn/run/` 0700（已知） | open |
  | 低 L2–L10 | 深链固定投 6 次不提前停；OCR 截屏矩形可能含上层窗口（推测）；窗口自动化报错直接终止不进档 C；同步写日志可抛错；登记文件元素不校验；import-legacy fields 绕过运行中 409；`close()` 超时抛 TimeoutError；PUT 的 TOTP 种子不校验；客户端控制按 PATH 解析 ps/open/osascript（推测） | open，记账 |
- 未做/not_run：真实 SSO（新品牌页面/选择器）、真实窗口 OCR/点击、真实 NSWorkspace 深链、权限授权后的行为、真实客户端 A/B 档、前端 dev:web/Tauri 人工走查；均需用户授权的真实验收。安全核对未覆盖前端 S8-C、`proc_supervisor` 内部、`uv.lock` 逐包。
- 资源：worktree `.local/worktrees/s5e/s7a/s7c/s8a/s8b/s8c` 保留，删除前问用户。
- 状态：S8 三包已集成；集成验收待 M1–M3 修复或用户明确接受；真实验收、所有权切换、主 Bot 切换仍未授权。

### S8-D 修复 M1–M3（2026-10-27）

- worker：codex `gpt-6.1-sol` medium（无提供方回执，actual unknown）；基线 `50ae4a4`，worktree `.local/worktrees/s8d`，限定路径补丁集成；每项先写失败回归并留修前失败证据。
- 变更：`adapters/vpn_browser.py`、`services/{events,telegram_commands,vpn}.py`、`tests/test_vpn_lifecycle_s8b.py`（新增用例，旧断言未改）、`tests/test_telegram_vpn_s8d.py`（新）。
- 主控验证（沙箱外）：全量后端 pytest 1455 passed / 2 skipped / 2 failed；失败为已知 S6-ACC-014 与 `tests/independent/s5c/test_s5c_projection.py::test_flood_is_bounded_and_turn_still_completes`（全量负载下偶发，单独连跑 3 次均 12 passed，与 VPN 无关，记为新的间歇项）；ruff 通过。
- 仍 open：L1–L10、真实验收（见上节）。

## S9 合同草案（2026-10-27）

- 角色：主控（lead）；requested/actual：Sonnet 5.5（会话系统提示自述，无提供方回执）；无子 agent、无派工。输入：`rewrite/next @ 3cae809`、旧版 `main @ 885d186`。
- 只读核对：旧 `BUILD_MAC_APP.md`、`pack_mac_app.sh`、`pack_mac_dmg.sh`、`release_github.sh`、`app_ado/release_updater.py`；已装旧 `.app` 的 `codesign -dv`/`spctl -a`；`security find-identity`、`notarytool --version`；新端 `tauri.conf.json`、`Cargo.toml`、`backend.rs`、`pyproject.toml`、`next/spikes/packaging/`、后端外部可执行依赖。未读凭据/Keychain 内容，未联网，未构建/签名/公证/发布，未改旧应用。
- 关键发现：旧 `.app` 是依赖仓库 `.venv` 的未签名包装；旧更新器只打开下载页、不校验；本机 **0 个可用签名身份**；打包态后端命令解析尚不存在；屏幕录制/辅助功能授权绑定宿主 `.app` 签名身份，ad-hoc 签名会使授权随更新失效；“自包含”只能指 Python 运行时与后端依赖（code-server/cloudflared/Node/AI CLI 仍为用户自装）；bundle id/应用名仍是占位（ARCHITECTURE §8 未决）。
- 产物：[WORK_PACKAGES.md「S9」](WORK_PACKAGES.md)（事实核实、架构五问、打包布局、S9-A/B/C 分包与模型分工、集成验收、真实验收清单、11 项待决）。
- 状态：合同草案，**待用户确认「S9 待决」**；确认前不派工，不授权签名/公证/发布/旧应用下线。
- not_run：未重跑测试（只写文档）；签名/公证/Gatekeeper 首启开销、运行时接入 tauri bundle 均未实测。

- 2026-10-27：用户确认 S9 待决 1–11 全部按推荐（原答复见 WORK_PACKAGES「S9 已决」），解除派工门禁；不授权真实签名/公证/发布/旧应用下线。

### S9-A 打包态后端解析（2026-10-27）

- worker：codex `gpt-6.1-sol` medium（无提供方回执，actual unknown）；基线 `c848ca1`，worktree 已删（补丁备份 `.local/dispatch/s9a/integration.patch`）。首轮因我写错叠加配置的资源映射键（`../build` 相对 `src-tauri/` 落在 `next/desktop/build`）被 worker 按“合同与事实不符”停下，主控裁决改为 `../../build/app-resources/{backend,mcp}` 后同会话续接完成。
- 变更（均在 `next/desktop/src-tauri/`）：`backend.rs` 新增 `BackendCommand::packaged`（覆盖变量 → `Contents/Resources/backend/bin/python3.14 -m toolbox_backend`（无 `--dev`，env 追加 `PYTHONDONTWRITEBYTECODE=1`/`PYTHONNOUSERSITE=1`，cwd=`Resources/backend`）→ 开发态），`app.rs` 改调该入口；`tauri.bundle.conf.json`（仅叠加，默认配置不引用暂存资源）；`tauri.conf.json` version `1.0.0`；README 一节；`tests/backend_command.rs`、`tests/bundle_config.rs` 共 4 个新测试（修前 E0599 / 1 failed）。既有断言无变更。
- 主控验证（沙箱外）：`cargo fmt --check`、`cargo clippy --all-targets --offline -D warnings`、`cargo test --offline` **40 passed**（既有 36 + 新 4）、`git diff --check` 全过。
- 只读发现（交 S9-B）：后端按 `Path(__file__).resolve().parents[3] / "resources/mcp"` 定位 MCP 资源（`mcp/runtime.py:32`、`mcp/figma_wrapper.py:99`、`services/mcp.py:567`、`domain/mcp.py:22`），在 wheel 安装态会落到 `Resources/backend/lib/python3.14/resources/mcp`，**打包后失效**，S9-B 须统一资源定位（脚本与 `package.json`）。
- 开放项：`minimumSystemVersion` 待 S9-B 实测；版本现为 Tauri `1.0.0`、Cargo/package.json `0.0.0`、pyproject `0.1.0`，同步与校验归 S9-B。
- not_run：真实 `.app` 打包、运行时启动、GUI、签名/公证。
