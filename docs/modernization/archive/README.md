# 已完成切片归档

2026-10-26 从 [WORK_PACKAGES.md](../WORK_PACKAGES.md) 与 [PROGRESS.md](../PROGRESS.md) 按切片原样拆出（提交 `b5eca58` 时的内容；只把相对链接改成指向原位置）。主文件只保留状态总表与当前切片。

**按需读取**：只打开要用的那一个文件，再用 `grep -n '^#\+ '` 列标题、按行号读所需小节；不要整份通读。

| 切片 | 合同 | 账本 |
| --- | --- | --- |
| 阶段 0/1（WP-00..16、旧应用热修、视觉方向 A–D） | [work-packages/phase0-1.md](work-packages/phase0-1.md) | [progress/phase0-1.md](progress/phase0-1.md) |
| S0 骨架 | [work-packages/S0.md](work-packages/S0.md) | [progress/S0.md](progress/S0.md) |
| S0.5 方向 E 换皮 | [work-packages/S0.5.md](work-packages/S0.5.md) | [progress/S0.5.md](progress/S0.5.md) |
| S1 设置与凭据 | [work-packages/S1.md](work-packages/S1.md) | [progress/S1.md](progress/S1.md) |
| S2 工单 | [work-packages/S2.md](work-packages/S2.md) | [progress/S2.md](progress/S2.md) |
| S3 任务执行 | [work-packages/S3.md](work-packages/S3.md) | [progress/S3.md](progress/S3.md)（含 R1 记录） |
| R1 方向 B 换皮 | [work-packages/R1.md](work-packages/R1.md) | 见 progress/S3.md「R1：方向 B 换皮」 |
| S4 Telegram | [work-packages/S4.md](work-packages/S4.md) | [progress/S4.md](progress/S4.md) |
| S5 AI 开发（含 S5-E） | [work-packages/S5.md](work-packages/S5.md) | [progress/S5.md](progress/S5.md) |
| S6 MCP 管理（含集成验收） | [work-packages/S6.md](work-packages/S6.md) | [progress/S6.md](progress/S6.md) |
| S7 服务管理（含集成验收；dsh 已推迟，S7-0 的 dsh 0.2.0 结论在合同内） | [work-packages/S7.md](work-packages/S7.md) | [progress/S7.md](progress/S7.md) |

## 常被引用的小节

| 引用写法 | 位置 |
| --- | --- |
| 阶段 0/1「通用施工合同」 | work-packages/phase0-1.md |
| 「S0 已定接口」（启动握手、token、Host/CORS/Bearer） | work-packages/S0.md |
| 「S1-A 主控裁决」、S1 数据模型（store、Keychain） | work-packages/S1.md |
| 「S2-D 主控裁决」、媒体代理/同源规则 | work-packages/S2.md |
| S3 运行模型、SQLite 检查点、「S3-C 主控裁决」 | work-packages/S3.md |
| S4 所有权切换步骤、ACL、多槽位 TelegramService | work-packages/S4.md |
| 「协议核对结论」（Claude/Codex/agy）、监督器、「S5-D2 主控裁决」 | work-packages/S5.md |
| 「S6-0 结论」、S6 安全核对表、Lark 刷新所有权切换步骤 | work-packages/S6.md |
| S6 集成验收（S6-ACC-*、resource-lifecycle 关闭点清单、迁移/改进/推迟） | progress/S6.md |
| 「S7-0 结论」（dsh 0.2.0 自带 token 认证/`--trusted-host`）、S7 安全核对表、服务所有权切换步骤 | work-packages/S7.md |
| S7 集成验收（S7-ACC-*、迁移/改进/推迟） | progress/S7.md |
| 各切片「真实验收清单」 | 对应 work-packages/S3.md、S4.md、S5.md、S6.md 等 |
| 历次交叉审计与发现编号（CR-*、S0A-* 等） | 对应 progress/*.md |
