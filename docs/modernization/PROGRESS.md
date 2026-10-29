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
| S9 交付 | 合同已确认（[WORK_PACKAGES.md「S9」「S9 已决」](WORK_PACKAGES.md)，11 项按推荐）；S9-A、S9-B、S9-C 已集成，S9 集成验收有条件通过（2026-10-27，见文末「S9 集成验收」：F1–F7 已于验收后修复），待真实验收 | 真实签名/公证/发布/旧应用下线均未授权；本机无签名身份 | — |

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

### S9-B 构建、版本同步与签名脚本（2026-10-27）

- worker：agy `gemini-4-argon-medium`（codex 额度用完后改派；无提供方回执，actual unknown）；基线 `25fd4f4`，补丁备份 `.local/dispatch/s9b/integration.patch`，worktree 已删。worker 沙箱不能 `chmod`/跑完整 cargo，主控补做。
- 变更：`next/scripts/{build_runtime,build_app,verify_app,sign_app,notarize_app,make_dmg}.sh`、`sync_version.py`、`README.md`、`tests/`（13 个 unittest）；`src-tauri/entitlements.plist`（空）；叠加配置去掉独立 `mcp` 映射（后端资源按 `parents[3]/resources/mcp` 落在运行时内，构建脚本复制到 `lib/python3.14/resources/mcp`）；版本同步到 `1.0.0`（`Cargo.toml/lock`、`package.json`、`pyproject.toml`、`uv.lock`、`__init__.py`、`contracts/openapi.json`）。
- 主控修正（真实构建暴露）：① `uv pip install --target` 产生带绝对 shebang 的 `site-packages/bin/*`，构建时删除；② 路径泄露白名单补充 `_sysconfig*`、`*.dist-info/sboms/`、`task_git.py`（S3 的 forbidden_roots 保护，非运行时依赖）；③ **ad-hoc 签名加 `--options runtime` 会因库验证（无 Team ID）拒绝加载内置 `.so`**，ad-hoc 去掉 hardened runtime（回归断言已加），`--identity` 下是否需要 `disable-library-validation` 留待真实签名实测；④ `bundle.macOS.minimumSystemVersion` 设为 `13.5`（`verify_app.sh` 扫 176 个 Mach-O 的最大 minos，来自 Playwright 自带 node），`bundle_config.rs` 断言由“无该键”改为“等于 13.5”。
- 主控验证（沙箱外）：脚本单元测试 13 OK、`bash -n` 全过（`shellcheck` 本机未安装，not_run）、`sync_version --check` 1.0.0；Rust fmt/clippy/test **40 passed**；后端全量 **1455 passed / 2 skipped / 2 failed**（均为已知间歇：S6-ACC-014 与 s5c flood），ruff、contracts --check 通过；前端 `contracts:check`、typecheck 通过；**真实本地构建** `build_app.sh --skip-frontend --sign adhoc` exit 0：布局、无 `/Users/` 泄露、拷到另一路径可启动并 `/health` 200、退出码 0、只读运行目录未新增文件、`codesign --verify --deep --strict` 通过；`make_dmg.sh` 产出 DMG 133 MiB、zip 96 MiB；无残留进程。
- **体积发现**：整包 294 MB（spike 估算 71 MB），其中 `playwright/` 138 MB（Python Playwright 自带 node 驱动，S8 引入，运行必需）；DMG 140 MB / zip 100 MB，对 Tauri updater 的下载体积有影响。可选后续：裁剪驱动内非必需文件（需实测）、或差分更新；待用户定是否处理。
- not_run：Developer ID 签名、公证、Gatekeeper/quarantine 首启、`stapler`、TCC 授权跨更新保留、`disable-library-validation` 是否需要（均需真实证书与授权）。未测前端 `pnpm build` 之外的 GUI 启动（`verify_app.sh` 只验后端启动，未打开窗口）。

- 2026-10-27：用户授权一次性联网（crates.io）下载 `tauri-plugin-updater` 及传递依赖；主控已执行（v2.14.0，Cargo.lock +46 crate，离线 clippy/test 通过）；接口冻结见 WORK_PACKAGES「S9-C 追加决定与接口冻结」；S9-C 分 shell/ui 两包并行派工。

### S9-C 应用内更新（2026-10-27）

- worker：壳 agy `gemini-4-argon-medium`、前端 agy `gemini-3.8-flash-high`（均无提供方回执，actual unknown；codex 额度用完后改派），基线 `1422b6e`，补丁备份 `.local/dispatch/s9c-{shell,ui}/integration.patch`，两个 worktree 已删。我首次启动 shell worker 时误用后台子进程（无完成通知），发现后按精确 PID 终止该孤儿进程、确认 worktree 未改，再以 `run_in_background` 重启。
- 依赖：用户授权一次性联网（crates.io）；主控 `cargo add tauri-plugin-updater@2` + `cargo fetch`，`tauri-plugin-updater 2.14.0`，Cargo.lock +46 crate、无既有 crate 版本变化（`1422b6e`）。
- 壳：`src/updater.rs`（`UpdateSource` 可注入 trait + `UpdateCoordinator` 状态机 + 真实 `TauriUpdateSource`：`check` → `download`（带进度、可取消、含 minisign 校验）→ `install`，**不用 download_and_install**）；5 个命令（`update_status/check/install/cancel/restart`）与最小权限；`update://status` 事件；`update_restart` 先走协调关闭再重启。**源码核实结论：`tauri-plugin-updater` 的 `Config.pubkey` 无 serde default，`plugins.updater` 缺失时插件初始化会失败并 panic，故仅在配置有效（pubkey 与 endpoints 非空）时才在 `setup` 里注册插件**；默认构建/开发态显示 `disabled`（`update_not_configured` / `update_unsupported_dev`）。`tauri.updater.conf.example.json`（占位）、`build_app.sh --updater-config`、`make_update_manifest.py`（`latest.json` 生成，仅标准库）。
- 前端：`useUpdate.ts`、`UpdateCard.vue`（挂在 `GeneralTab.vue`），非 Tauri 环境降级为只读 `disabled`；notes 纯文本、无 URL 输入框、重启需二次确认。
- 主控修正：壳测试 `FakeSource` 的 `Default`、`CheckMode` 可派生（clippy）；前端测试的 mock 类型/未用导入、Prettier 格式、4 处文案断言与界面实际文案不符（改断言）、`.available-version` 把强调色用作文字色违反既有设计令牌测试（改为 `--ink`）。worker 在沙箱内无法跑 cargo/pnpm，全部验证由主控沙箱外完成。
- 主控验证（沙箱外）：Rust fmt/clippy `-D warnings`/test **53 passed**（既有 40 + updater 11 + bundle_config 新增 2）；脚本 unittest **OK**（既有 13 + 新 5）、`bash -n` 全过、`sync_version --check` 1.0.0；前端 typecheck、lint、test **1194 passed / 84 文件**（1173 + 新 21）、build、guard:dist、contracts:check 全过；`git diff --check` 通过。
- **真实验收项（本包均未做）**：真实更新源与 minisign 更新签名（需用户提供 GitHub 仓库、`tauri signer generate` 公钥、`TAURI_SIGNING_PRIVATE_KEY`）；打包态真实下载/校验/替换 `.app` 与重启；更新后协调关闭后端无残留；GUI 人工体验。`shellcheck` 本机未安装 not_run。
- 开放项：更新包体积（Playwright node 驱动 138 MB，DMG 140 MB/zip 100 MB）；签名后是否需要 `disable-library-validation`；Developer ID 签名/公证/Gatekeeper/TCC 跨更新保留。

## S9 集成验收（2026-10-27）

- 角色：主控（lead，Sonnet 5.5，无提供方回执）；基线 `rewrite/next @ 78efbec`；Opus 只读安全核对用 Agent（`model: opus`，完整报告 `side-session-notes/…/s9-opus-audit.md`，未改文件、未联网）。只验收，未派施工包，**未改任何代码**。
- **结论：有条件通过**（本机自用/开发验收通过；对外分发前须先修 S9-F1，建议同时修 F2/F3/F4）。
- 验证（沙箱外）：
  - 后端 pytest **1455 passed / 2 skipped / 2 failed**：`test_s6b_lark.py::test_lark_health_probe_marks_unhealthy_after_3_failures`（已知）与 `tests/test_s7_processes.py::test_backend_sigkill_reclaims_code_tunnels_and_grandchild`（**新间歇项**：单独重跑 `-k sigkill` 一次过一次败，失败为 `code-pid` 文件尚未写出的时序竞态；S9 对后端仅改版本号，与 S9 无关；已知的 s5c flood 本轮未出现）。ruff、`contracts --check` 通过。
  - 前端 typecheck/lint（0 error，9 个既有 warning）/test **1194 passed / 84 文件**/build/guard:dist/contracts:check 全过。
  - Rust fmt、clippy `-D warnings`、test **53 passed**（8+3+3+9+19+11）。脚本 unittest 18 OK、`sync_version --check` 1.0.0、`bash -n` 全过、`git diff --check` 干净。
  - **真实构建复验**：`build_app.sh --skip-frontend --sign adhoc` exit 0 且 `verify_app.sh` 全过（布局、0 路径泄露、另一路径启动、/health 200、退出码 0、只读、`codesign --verify`、176 个 Mach-O 最低系统 13.5）；`make_dmg.sh` 成功（DMG 132 MB、zip 113 MB、.app 291 MB）；无残留进程。**注意**：首次构建两次失败于 `futures_macro` 的 `E0463`——共享 `.local/cargo-target` 里 release 的 `futures-macro` 产物陈旧/损坏（普通 `cargo build --release` 同样复现），`cargo clean --release -p futures-macro -p futures-util` 后正常；根因未明（疑似此前被中断的构建），属本机缓存问题而非源码缺陷，但干净机器上的首次 release 构建**未测**。
- Opus 发现表：

| 编号 | 级别 | 位置 | 摘要 | 状态 |
| --- | --- | --- | --- | --- |
| S9-F1 | 高（仅真实发布） | `build_app.sh:145,154-162`、`README.md:82-103` | updater 的 `.app.tar.gz`/`.sig` 取自**未签名**的 cargo 产物，而非签名/公证后的 `out/TOOLBOX.app`；按 README 发布会让自动更新装上无 Developer ID/公证的包 | fixed（见下「验收后修复」） |
| S9-F2 | 中（主控读码确认 `updater.rs:524-577,610-626`） | `updater.rs` | 安装阶段状态仍为 Downloading 且 `cancel_tx=None`，`update_cancel` 被接受并广播 Available/cancelled，但安装继续并最终发 Ready，违反“取消保留旧版” | fixed（见下「验收后修复」） |
| S9-F3 | 低 | `UpdateCard.vue:25-28`、`useUpdate.ts:132-173`、`updater.rs:363` | ready 时“检查更新”可点，后端报错后前端把本地状态改 error，“重启”按钮消失 | fixed（见下「验收后修复」） |
| S9-F4 | 低 | `build_app.sh:117-141` | 合并 `--updater-config` 不校验非 https/`dangerousInsecureTransportProtocol`/占位公钥；release 下非 https endpoint 会使插件初始化 panic（推导） | fixed（见下「验收后修复」） |
| S9-F5 | 低 | `verify_app.sh:268-297` | 主进程已退而进程组残留时 finally 不 `killpg` | fixed（见下「验收后修复」） |
| S9-F6 | 低（推测） | `backend.rs:243-246` | 打包态未清 `PYTHONPATH/PYTHONHOME/PYTHONSTARTUP`（终端启动 .app 时可混入） | fixed（见下「验收后修复」） |
| S9-F7 | 低 | `build_runtime.sh:29`、`tauri.bundle.conf.json:4` | `rm -rf "$RUNTIME_OUT"` 无路径防护；设置 `TOOLBOX_BUILD_DIR/RUNTIME_OUT` 时资源路径写死不一致 | fixed（见下「验收后修复」） |
| S9-F8–F13 | 信息 | — | F8 插件 debug 日志含完整 URL（现无日志后端，接日志时须过滤 `tauri_plugin_updater`）；F9 verify 测试钩子经 argv 传临时 token；F10 README 让 export 私钥/口令；F11 合同写 zip、实际 updater 用 tar.gz；F12 `check()` 允许从 Available 发起；F13 `--timestamp` 需联网、entitlements 为空须真实签名时实测 | deferred |

  Opus 清单：①②④⑤⑥⑨⑩ 通过；③ 有保留（F2）；⑦ 有保留（F1/F5/F7）；⑧ 有保留（F6）。无凭据泄漏、无 URL 注入、权限仅新增 5 个 `allow-update-*`、Cargo.lock 新增 46 个 crate 全部来自 crates.io 带 checksum、无既有 crate 版本变化。Opus 未核对 `tests/**` 与真实签名/公证行为。
- **迁移 / 改进 / 有意推迟**（对照 D14、D16）：
  - 已做（D14 打包交付）：自包含 python-build-standalone 运行时 + 后端 wheel 依赖锁定安装；可重定位且无 `/Users/` 泄露；构建/校验/签名/公证/DMG 脚本流水线（内层先于外层、不 `--deep`、公证只读 `TOOLBOX_NOTARY_PROFILE`）；版本单一来源 `tauri.conf.json` 并校验一致；打包态后端解析与开发态回退；失败时 `verify_app.sh` 清理启动的后端。D16：旧更新器“只开浏览器、不校验”被 Tauri updater（minisign 校验、可取消、协调关闭后重启、默认 disabled）取代。
  - 待做：F1–F7 修复；真实更新源与更新签名密钥；Developer ID 签名、公证、staple、Gatekeeper；旧应用下线与旧更新器/空占位清理（改旧代码，需另行授权，S9 不改旧应用）。
  - 有意推迟：不内置 Node/code-server/cloudflared/AI CLI（沿用探测与设置页提示）；不做开机自启；仅 arm64；差分更新；包体积优化。
- **开放项（not_run，均需真实证书/授权）**：Developer ID 签名、公证、Gatekeeper/quarantine 首启、TCC（屏幕录制/辅助功能）授权跨更新保留、`disable-library-validation` 是否需要、打包态真实下载/校验/替换与重启、更新后后端无残留、GUI 人工体验（未启动打包后的 `.app` 窗口）；`shellcheck` 本机未安装；更新包体积（Playwright node 驱动 138 MB，整包 291–294 MB，DMG 132–140 MB/zip 100–113 MB）；S8 遗留低级项 L1–L10；已知间歇测试（S6-ACC-014 lark 健康探测、s5c flood、新增 s7 sigkill 时序）；bundle id/应用名仍为占位 `dev.toolbox.next`/`TOOLBOX`；干净机器首次 release 构建（见上 futures-macro）。

### S9 验收后修复（2026-10-27）

- 派工：3 个 Sonnet 5.5 子 agent（claude 运行时，无提供方回执），路径互不重叠，均未提交；主控复验后限定路径提交。
- F2（`updater.rs`）：`Inner.installing` 标记，下载完成时在同一把锁内判定“取消 vs 进入安装”，安装阶段 `cancel` 原样返回快照；新增回归测试（去掉守卫即红）。F6（`backend.rs`）：打包态 `env_remove` `PYTHONPATH/PYTHONHOME/PYTHONSTARTUP` + 测试。Rust **55 passed**（+2），fmt/clippy 通过。
- F3（`UpdateCard.vue`、`useUpdate.ts`）：ready 时禁用检查按钮；check/install/cancel 出现状态冲突时重拉 `update_status` 而非写 error；+6 测试，前端 **1200 passed / 84 文件**，typecheck/lint/build/guard:dist 通过。（worker 一次全量中 `s2c-independent` 2 条偶发失败，重跑全绿。）
- F1：新增 `make_update_artifact.sh`（从签名后的 `out/TOOLBOX.app` 重打 tar.gz，私钥只读环境变量；ad-hoc/未签名拒绝 exit 2，`--allow-unsigned` 仅本地测试）；README/manifest 流程同步，`build_app.sh` 末尾提示 cargo 产物的 tar.gz 不可发布。F4：新增 `validate_updater_config.py`，拒绝 `dangerousInsecureTransportProtocol`、非 https、占位 endpoint/公钥（exit 2）。F5：`verify_app.sh` 主进程已退但进程组残留时按记录的 PGID `killpg`。F7：`build_runtime.sh` 的 `rm -rf` 路径防护，叠加配置资源映射随实际 RUNTIME_OUT 改写。脚本 unittest **23 OK**（+5）。
- 主控复验：前端/Rust/脚本全量如上；真实 `build_app.sh --skip-frontend --sign adhoc` 再次 exit 0 且 verify 全过；`make_update_artifact.sh` 对 ad-hoc 包正确拒绝；无残留进程。
- not_run：`pnpm tauri signer sign` 靠环境变量取私钥仅按 Tauri v2 文档假设、未实测；真实 Developer ID 签名/公证后的更新包链路；ShellCheck。F8–F13 仍 deferred。

### S9 验收更正：打包应用白屏（2026-10-27，用户安装 DMG 后发现）

- **现象**：安装 `TOOLBOX-1.0.0-arm64.dmg` 后窗口纯白。**根因（主控确认）**：`next/scripts/tests/test_scripts.py` 里 build_app 的单元测试用假 `pnpm`，其 `mkdir -p dist; echo '<html></html>' > dist/index.html` 写进了**真实** `next/desktop/dist`；我在验收里先跑 pnpm build、再跑脚本 unittest、再 `--skip-frontend` 构建，于是把空页面打进了应用（上一节“真实构建复验通过”的 DMG 实际是白屏包）。`verify_app.sh` 只验后端启动，未覆盖前端，因此没发现。该缺陷自 `78efbec` 起就存在。
- **修复**：`build_app.sh` 增加 `TOOLBOX_DESKTOP_DIR` 覆盖，并在打包前强制检查 `dist/index.html` 含 `<script` 且 `dist/assets/*.js` 存在，否则 exit 1；测试改为使用临时 desktop 目录（不再碰真实 dist），新增 `test_build_app_rejects_stub_frontend_dist`。脚本 unittest **24 OK**（跑完后真实 dist 保持完好）。已重新构建并重打 DMG（`next/build/dist/`），二进制内可见 `assets/index-*` 引用。
- **教训/开放项**：此前“真实验收”只覆盖后端启动，GUI 从未被打开——正是用户在场的 GUI 人工体验项所补出的缺陷；建议后续在 `verify_app.sh` 之外补一个不碰真实数据目录的窗口冒烟（not_run）。新 DMG 的窗口内容仍待用户确认。

## 发布配置 v7（2026-10-28，用户本轮已定方案）

- 角色：build；actual_model/actual_effort=unknown（工具未提供可验证回执）；原生运行通道 `/root`；verified_by=executor，independent=false，未委派。基线 `rewrite/next @ 42f5042` + 用户既有未提交改动；本轮未提交、未切分支。
- 实现 done：ReleaseConfig/稳定目标目录/RunCommand，v6→v7 备份与原子迁移，配置及命令 CRUD/排序，旧任务接口兼容展开，TG 冒号标签、ACL/运行记录继续使用原任务 id，OpenAPI 与桌面生成类型。未修改执行器、RunService、运行 SQLite 结构或用户已有 ACL 修复；桌面源码仅更新生成类型。
- 交付字段、接口、兼容写限制、迁移假数据结果与文件清单见 [发布配置与运行命令](../capabilities/release-configs-next.md)。历史空目标选择保留但禁止执行；新命令至少选一个目标。
- 全量验收 partial：`uv run pytest -q` exit 1，**96 failed / 1149 passed / 20 skipped / 211 errors，798.41s**。该轮与施工重叠，含已修复的适配/契约失败；全部失败及原始输出留本地审计目录，不虚报为全量通过。沙箱明确拒绝本地 socket bind 和进程查询；其他 AI/进程/Lark 失败尚未在无沙箱环境复验。
- 最终相邻 S1/S3/S4：**501 passed / 1 failed，115.15s**，唯一失败为 `test_s1d_process.py::test_cr006_dev_memory_process_stderr_never_contains_pat` 的 socket bind `PermissionError: Operation not permitted`；相关配置/迁移集合 **261 passed / 1 skipped，26.88s**；专项 **13 passed，0.68s**；最终契约测试 **14 passed，16.23s**。ruff 全后端、契约 `--check`、桌面 contracts:gen/check、diff --check 通过。
- 未测：用户真实配置迁移、真实 ADO/TG/Keychain、桌面人工体验。后续：前端按新配置/命令接口接入；在允许本地端口/进程查询的环境复跑全量。
- 清理/保留：临时施工脚本已移除；原始输出、SHA-256 与命令记录保留于 Git 忽略的 `next/.local/release-configs-v7/`；uv 缓存保留。


## 发布配置 v8 分支目录（2026-10-28，用户本轮已定方案）

- role=build；actual_model/actual_effort=unknown；verified_by=executor，independent=false；未委派、未提交、未 stash、未切分支。
- done：ReleaseBranch 稳定目录、命令必选 branch_id、配置共享来源合并、v7→v8 备份/原子/幂等迁移、目标映射与命令 id 保持、引用错误码 target_in_use/branch_in_use、旧任务视图与保守写兼容、生成 OpenAPI/桌面类型。执行器、运行库及投递/核对协议不变。桌面仅运行生成命令更新 schema.d.ts。
- 等价假数据验收：6 配置→5 配置，CG_Vue_Front 包含 main/develop 两分支、两命令；未读用户真实配置。字段、迁移、API 对照、前端接入和本轮文件清单见 [交付说明](../capabilities/release-configs-next.md)。
- 验收 partial：专项 20 passed；最终 S1/S3/S4 + 专项 **511 passed / 1 failed，112.18s**，唯一失败为 test_s1d_process 本地 bind 被沙箱拒绝。首轮独立 S1 live boundary 的 8 项 setup errors 经隔离启动确认同为 bind PermissionError，最终集合明确排除该文件。契约及相关配置迁移 **93 passed / 1 skipped，14.93s**；ruff、OpenAPI --check、桌面 contracts:gen/check、diff --check 通过。
- not_run：本轮全量、沙箱外端口相关项、真实配置迁移、真实 ADO/TG/Keychain、桌面业务接入与人工体验。无业务范围偏离；同名构建分支但规则不同的历史冲突保留原文件并报迁移失败。
- 清理/保留：无持久服务，无临时施工文件；原始日志、端口诊断及 SHA-256/命令清单保留在 Git 忽略的 next/.local/release-configs-v8/；测试资源由 fixture 清理。

## 发布配置只读自动发现（2026-10-28）

- role=build；actual_model/actual_effort=unknown（运行时未提供可验证回执）；runtime=/root；verified_by=executor，independent=false，未委派。输入为 rewrite/next @ 42f5042 + 用户既有大量未提交改动；未提交、未 stash、未切分支。
- done：`/api/release-configs/discover` 下 repo/branches/targets/queues 四接口、独立响应契约与服务；本地固定 Git 参数只读发现、URL 去凭据与项目匹配、仓库详情和已有配置检测、默认分支排序、构建 kind、Release 关联与建议目标、队列多版本回退、稳定中文错误。无配置写入、缓存或迁移；凭据与出站限制复用 work_items/AdoRead。接口/示例/边界详见 release-configs-next.md「自动发现」。
- 文件增量：新增 api/release_discovery_routes.py、api/release_discovery_schemas.py、services/release_discovery.py、tests/test_release_discovery.py；release_routes.py 注册子路由；能力文档追加自动发现；OpenAPI/桌面 schema.d.ts 由指定生成器更新。保留原有用户改动，桌面未手改。
- 真实验收：指定 `uv run pytest -q tests/test_release_discovery.py tests/test_release_configs.py` 最终 **45 passed in 1.86s**，exit 0；改动 Python 文件 ruff check **All checks passed!**，exit 0；contracts 生成及 `--check`、桌面 `pnpm -s contracts:gen && pnpm -s contracts:check`（contracts:check ok）、git diff --check 均 exit 0。期间命令工作目录错误已纠正，失败尝试不计作通过。
- 偏离：无业务范围偏离。Release 使用与现执行器一致的同域、6.0→7.0 明确版本不支持回退，不扩大 Library 出站边界。端口精确匹配，不跨 SSH/HTTPS 端口猜测；项目来源不唯一同样返回 project_not_matched，避免选错凭据。
- not_run：真实 ADO/Keychain、前端向导人工体验、后端全量及沙箱外验收。资源核对：Git subprocess.run 有 10s 超时并自动 kill/wait；取消由 outbound 等待线程退出后释放许可；HTTP 复用 AdoRead 的客户端上下文与超时。无任务持久服务或临时施工文件，临时 Git/配置由 pytest fixture 清理；uv 缓存保留。

## Telegram Token 保存后只读校验（2026-10-28）

- role=build；actual_model/actual_effort=unknown；runtime=/root；verified_by=executor，independent=false，未委派。输入 `rewrite/next @ 42f5042` + 用户大量既有未提交改动；未提交、未 stash、未切分支。
- done：主 Bot 与三个 AI Bot 保存/旧版导入后只读 getMe/getWebhookInfo、10 秒总超时、持久化已验证身份及最近校验结果；新增对应 token/verify；失败保留 Token、固定错误码及中文文案；webhook 提示；enable 刷新身份，接管身份和状态机语义不变。配置新字段默认 null，schema 版本不变。
- 文件：backend services/telegram.py、api/telegram_routes.py、api/telegram_schemas.py、domain/telegram.py、domain/ai.py；新增 tests/test_telegram_token_verify.py；test_s4a_foundation.py 补 FakeTelegram 注入；contracts/openapi.json、desktop/src/api/schema.d.ts 由指定命令生成；本能力文档及本账本。保留原有改动，未手改桌面源码。
- 最终指定 pytest 集合 **132 passed in 4.96s**，exit 0；新增专项 28 项，包含四槽位保存/导入成功、401、网络、超时、webhook、verify、更换/删除、enable 身份刷新、持久化重读与响应/日志不含 Token。改动 Python 文件 ruff **All checks passed!**；后端 contracts 生成及 --check、桌面 contracts:gen/check **contracts:check ok**，均 exit 0；git diff --check 通过。
- 首轮指定集合为 1 failed / 127 passed / 1 teardown error：旧 foundation 测试保存 Token 未注入传输，新行为触发 DNS 测试隔离守卫；补 FakeTelegram 后完整通过。此项不是端口绑定失败，没有放宽守卫或捕获守卫异常。
- not_run：真实 Telegram/Keychain、桌面按钮及人工体验、后端全量；前端接入说明见 telegram-control.md。无持久服务或任务临时文件，测试资源由 fixture 回收。


## Telegram 分层菜单（2026-10-28）

- role=build；actual_model/actual_effort=unknown；runtime=/root；原生测试子 agent `/root/menu_tests`（actual unknown）仅新增测试文件，接管后施工者补辅助导航测试；verified_by=executor，最终集成验证 independent=false。输入为 rewrite/next 的用户未提交工作区；未提交、stash、切分支或修改 next/desktop。
- done：主菜单五项及摘要、发布配置→命令→动作→确认、配置/命令权限过滤与排序分页、逐层返回与深层主菜单、原面板编辑、过期提示、详情结果与相对时间、活动运行停止/进度、系统回滚与停止分层、文本命令兼容、工单/服务/MCP 图标及返回。停止加 task_ids 限制且保留原 chat 来源限制；状态/进度独立检查 can_status。执行器、运行协议与配置模型未改。
- 最终指定验收 exit 0：**142 passed in 16.27s**；新增菜单专项包含 27 项。相邻回归除下列失败项外 exit 0：**43 passed, 1 deselected in 28.23s**。改动 Python 文件 ruff check 与 git diff --check 通过。完整菜单树、路径、逐条旧断言与命令见 [交付说明](../capabilities/telegram-menu-next.md)。
- partial（相邻，不属于指定集合）：`test_s5c_wi.py::test_analysis_routes_output_to_enabled_ai_bot` 连续两次等待 AI 输出超时，单独复现 exit 1，**1 failed in 16.23s**；测试库会话 `failed/start_failed`，只有 starting→failed 事件，主 Bot 创建/路由断言已通过。保留失败断言，未改 AI 执行器，原因待定位；没有证据认定为端口沙箱失败，未宣称相邻全量通过。
- not_run：真实 TG/ADO/Keychain、Telegram 客户端人工体验、后端全量。cleanup：无任务常驻服务或新增端口；pytest fixture 回收资源；日志与最终文件摘要保留在 Git 忽略的 `next/.local/telegram-menu/`，任务 `/tmp` 日志已移除，uv 缓存保留。
