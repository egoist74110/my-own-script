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
| S7 服务管理 | 合同已确认（12 项待决按推荐，「S7 已决」）；S7-0 已完成；用户 2026-10-26 决定 dsh 暂时砍掉（推迟出 S7，范围调整见合同），可派 S7-A（[WORK_PACKAGES.md「S7」](WORK_PACKAGES.md)） | 真实验收清单与服务所有权切换未授权 | — |
| S8 VPN / S9 交付 | not_started | — | — |

最近一次集成版本全量（S6 集成验收，`6a00fc2` + 验收修复）：后端 **1242 passed**、ruff、contracts --check；前端 frozen install/typecheck/lint/test **1141 passed / 81 文件**/build/guard:dist/contracts:check；Rust `cargo test --offline` 36 passed。

## 跨切片待办（从归档汇总；细节查对应 archive 文件）

真实验收与切换（均需用户另行授权）：

- S2：真实 ADO 列表/详情/评论/附件；CR-NEXT-004（附件是否 302 到跨源 CDN，属实则追加受信策略小包）；I-5、I-7。
- S3：真实 SSH push、ADO 构建/发布/回滚（清单见 archive/work-packages/S3.md）。
- S4：测试 Bot 真实验收；主 Bot 所有权切换（S6–S8 期间择时）。
- S5：真实验收清单（含 Codex `none`/`max` 档、`-m`、TERM 后续聊、Claude 审批 allow 回包、agy stdin 格式）；三个 AI 机器人逐个切换；dev:web 未手工走通的 TG `/cc`、`/wi` AI 分析、桌面工单 AI 分析。
- S6：真实验收清单（archive/work-packages/S6.md「真实验收清单」：运行组件安装含 `npm rebuild keytar` 与 Node 下载、三家 CLI 注册 `toolbox_ado`/`toolbox_figma` 与真实调用、Lark 所有权切换与闲置 >2 小时续期、强杀回收）；Lark 相关（真实包补丁核对、所有权切换、续期）用户 2026-10-26 原话“lark暂时不用验，反正也不用了（暂时不怎么需要了，后续再说”→ 搁置，重启时**首先确认新补丁在真实 lark-mcp 0.5.1 上三项标记均为 applied**（S6-ACC-001）；剪贴板复制、桌面“AI 分析”会话启动（dev:web 未走通）。
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

2026-10-26 主控核对代码后关闭（`rewrite/next @ 5ae038e`）：

| finding_id | 状态 | 证据 |
| --- | --- | --- |
| S0A-006 | fixed（S1-A） | `api/ws.py:203-206`、`api/ai_routes.py:156` 无 Origin 或不在白名单即 1008 关闭；回归 `tests/test_s1_settings.py::test_no_origin_rejected_before_accept_without_network`、`tests/independent/s1/test_s1_live_boundaries.py::test_websocket_handshake_without_origin_is_rejected` |
| S0A-007 | fixed（S1-A） | `api/middleware.py:66` 全局 `BodyLimit`（`app.py:268`，Host→CORS→Auth→BodyLimit），超限 413，覆盖 `/api/system/alert`；回归 `tests/independent/test_fault_http.py:210` |
| S05-004 | obsolete | 导航角标已无 `aria-label` span，计数作为 `RouterLink` 文本读出（`components/Sidebar.vue:86-91`）；审批快捷键改由 `ChatView.vue` 处理，仅焦点在该会话内且有一条待审批时响应。旧 `components/ApprovalBar.vue` 仍挂 window 监听但已无引用（死代码，可删） |

本次只核对代码与既有测试，未重跑测试。

资源：施工 worktree 仅剩 `.local/worktrees/s5e`（删除前问用户）；`s6a/s6b/s6c` 经用户 2026-10-26 同意已删除（删除前核对：未提交内容均已在 `8b6e446`/`9ffedba`/`6a00fc2` 中，唯一差异是集成时去掉的文件尾空行）；`.local/cargo-target` 约 4 GB 等 git 忽略目录保留。

## S7 合同草案（2026-10-26）

- 角色：主控（lead）；requested_model：Sonnet 5.5（用户 2026-10-26 偏好：lead 用 Sonnet），actual_model：Sonnet 5.5（会话系统提示自述，无提供方回执，按 AGENT_WORKFLOW §6 记 unknown 级证据）；runtime_identity：Claude Code 子会话（由 `local_a90c239b-00bd-44ea-9321-f65d58b591a4` 的上级会话派出）。
- 输入：新版 `rewrite/next @ 7dd246b`；旧版 `main @ 885d186`；AGENTS/AGENT_WORKFLOW/PROGRESS/MIGRATION_PLAN/ARCHITECTURE、旧 `docs/capabilities/services.md`、归档 S4 已决 1、S6 合同（结构样板与 McpService 做法）。
- 只读核对范围：旧 `app_ado/services_panel.py`、`dsh_gateway.py`、`ui/services_tab.py`、`vpn_ip.py`、`tg_control.py`（svc 回调）、`tg_help_inline.py`（服务菜单）、`secrets.py`（dsh 条目）；新端 `adapters/proc_supervisor.py`、`services/mcp.py`/`telegram_commands.py` 结构、`domain/settings.py` 版本、`pyproject.toml` 依赖。确认上述旧文件在 `git status` 中无未提交改动。**未**读真实配置/凭据（`~/.config/*`、`~/.dsh`、Keychain）、未启动任何服务、未联网、未改旧应用。对本机已装 `cloudflared tunnel run --help`、`code-server --help`、`dsh web --help` 各跑一次（仅打印帮助；dsh 的 help 会加载 profile 并在 stderr 打印插件不兼容提示，未起服务）。
- 关键新发现（详见合同「S7 旧应用事实核实」）：
  1. 旧端服务全部 detached 常驻、靠 pid+端口/正则签名找回——与新架构“退出即回收”相反，是 S7 最大的取舍（待决2）。
  2. `codeserver_stop` 会杀监听该端口的任意进程；cloudflared 按未转义 `pgrep -f` 前缀匹配，`:5173` 会命中 `:51730`；`_kill_pid` KILL 后不等待也不核对身份。
  3. 密钥/密码外泄面：code-server 明文密码与 dsh 网关密钥进入 UI/TG 状态文本，`dsh_start` 结果经 TG 发送密钥。
  4. D03 具体点：网关 `--key`、命名隧道 `--token` 进 argv，启动还经 `sh -c` 命令串。**本机 `--help` 确认 cloudflared 支持 `TUNNEL_TOKEN`/`TUNNEL_TOKEN_FILE`**，可去掉 argv 凭据。
  5. 网关 `0.0.0.0`、无失败限速、手写 HTTP 解析（不处理请求体 chunked）、Host 改写 + Origin 剥离且无 WS Origin 校验、cookie 无 `Secure`；旧 `services.md` “放行 WS”的描述与代码（WS 只认 cookie）不符。
  6. **dsh `0.2.0-rc.2` 提供 `--trusted-host`**，可能取代网关的 Host/Origin 改写、缩小特权面（待 S7-0 本机实测，待决1）。
  7. 自定义隧道目标不限回环、无数量上限/确认；命名隧道“域名”实为 `<id>.cfargotunnel.com`（路由 CNAME 目标），疑似并非可访问地址（待真实验收，待决11）；网关端口漂移会使隧道路由 502；`npx -y`/`npm install -g` 运行时联网。
  8. 新端无任何 S7 代码；config 当前 v4，S7 将升 v5；S4 已决 1 要求 S7/S8 菜单迁完才切主 Bot，故 TG 服务菜单（待决9）不能砍。
- 产物：[WORK_PACKAGES.md「S7」](WORK_PACKAGES.md)（事实核实、架构五问、config v5、凭据、托管、网关、HTTP/WS、安全核对表、S7-0/A/B/C 分包与模型分工、集成验收、真实验收清单、所有权切换步骤、12 项待决）。
- 状态：合同草案，**待用户确认「S7 待决」**；确认前不派工，不授权 S7-0 本机核对、真实验收与服务所有权切换。
- not_run：未重跑任何测试（只写文档）；dsh 围栏/`--trusted-host` 行为、真实 quick tunnel 日志格式、`cfargotunnel.com` 可访问性均未实测。
- cleanup：无临时进程；草稿在会话 scratchpad，未留仓库。

### S7 已决与 S7-0（2026-10-26）

- 用户确认待决 1–12 全部按推荐（提交 `25faed1`）。S7-0 由主控本机执行（待决1授权）：临时 `DSH_HOME` + 随机端口 39517 仅回环起 `dsh web 0.2.0-rc.2` 两次，curl/socket 探测；结束后进程停止、端口与进程零残留、临时目录与含 token 的日志已删；未读 `~/.dsh`/真实配置、未联网登录、未网络监控。
- 关键发现：**dsh 0.2.0 已有自带 token 认证**（启动打印 `?token=`，每次启动随机、不落盘；cookie `dsh-auth-*` 绑定 Host authority，30 天，SameSite=Strict），旧网关“dsh 无登录”前提与旧 API 路径 `host.describe` 均已失效（该路径现为 404）；`--trusted-host` 可用；围栏规则与 401 指纹见合同「S7-0 结论」。**WS 路径/认证方式未能确认**（探测空应答），留给 S7-B 与真实验收。
- 合同修订：网关改为“用户认证 + 代持 dsh cookie”；外部已运行 dsh **不再复用**（拿不到其 token），改为 `external` 只读 + 409，待用户确认；Host 改写方案保留为默认。
- not_run：未跑任何自动化测试；真实 WS、命名隧道、quick tunnel、`cfargotunnel.com` 均未测。

- 2026-10-26 用户：“dsh 暂时可以砍掉了，现在用不上。” S7 缩为 code-server + cloudflared quick tunnel + 网络信息 + 服务页 + TG 服务菜单；dsh/网关/命名隧道与两条凭据推迟，S7-A/B 合并为一个后端包；S7-0 的 dsh 结论保留备查。未改代码。
