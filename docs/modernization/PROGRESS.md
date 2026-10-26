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
| S6 MCP 管理 | 合同草案，**待用户确认 11 项待决**，未派工 | — | 本文件下方 |
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
| S0A-006、S0A-007 | 待核后关闭 | S1-A 已实现 WS Origin 与请求体上限，账本未正式标 fixed |
| S05-004 | open | 导航角标 aria、审批条 window 监听（原定 S5 顺带处理，未见关闭记录） |

资源：施工 worktree 仅剩 `.local/worktrees/s5e`（删除前问用户）；`.local/cargo-target` 约 4 GB 等 git 忽略目录保留。

## 2026-10-24：S6 合同草案（主控）

- 主控 actual unknown（Claude Opus 5.5 会话，lead）。输入 `rewrite/next @ 1a5548d`。
- 主控只读核实旧应用 `main @ 885d186` 的 ADO/Lark/Figma MCP 托管事实（文件与行号写入 WORK_PACKAGES「S6 旧应用事实核实」），未读真实配置/凭据/CLI 配置/lark-mcp 存储，未连真实服务，未启动旧应用 MCP 或 node/npx。
- 关键新发现：①ADO/Figma 的应用“启动”进程不服务任何客户端（CLI 各自 spawn stdio）；②Lark 登录把 App Secret 放进 argv（`app_lark/mcp_server_manager.py:333–337`）；③lark-mcp 令牌存储是全局 `storage.json`，新旧应用天然共用；④Bearer 注入把 UAT 明文写进三家 CLI 配置；⑤Node 下载无校验、解包无过滤；⑥lark-mcp/figma 包未锁版本（D13）。
- 合同写入 WORK_PACKAGES「S6」：架构五问、config v4、凭据、ADO server、stdio 有界自检（D08）、Lark 托管与端口预检/补丁标记、Figma wrapper、Node/npm、接入片段与 S5 分析来源切换、HTTP/WS、安全核对表、S6-0/A/B/C 分包、集成验收、真实验收清单、Lark 所有权切换步骤、待决 11 项。
- 状态：S6 **待用户确认待决**，未派工。
