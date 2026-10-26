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
| S8 VPN | 合同草案待确认（[WORK_PACKAGES.md「S8」](WORK_PACKAGES.md)，10 项待决；未派工） | 真实验收清单、所有权切换与主 Bot 切换未授权 | — |
| S9 交付 | not_started | — | — |

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
