# 服务管理（code-server / cloudflared 隧道 / 网络信息）

## 这个能力做什么
设置 → 服务页（`ServicesTab.vue`）管理两个本机服务：**code-server** 启停（带健康检查），**cloudflared quick tunnel**（默认隧道指向 code-server，另可建多条自定义隧道指向本机回环端口）。顶部 `NetworkBar` 显示 VPN IP / 局域网 IP，下方是 VPN 卡（见 vpn 页）。TG 服务面板与桌面端共用同一后端 `ServicesService`。

## 关键文件（均在 `next/` 下）

| 做什么 | 文件 |
| --- | --- |
| 服务生命周期（启停/监控/自定义隧道/协议偏好/日志） | `backend/src/toolbox_backend/services/services.py` |
| 读 code-server 配置、二进制解析、隧道目标校验 | `backend/src/toolbox_backend/adapters/service_runtime.py` |
| 服务日志（0600、5MiB×2 轮转、脱敏 tail） | `backend/src/toolbox_backend/adapters/service_logs.py` |
| 子进程进程组监督 | `backend/src/toolbox_backend/adapters/proc_supervisor.py`、`ai_process.py`（`SupervisedProcess`） |
| VPN IP / 局域网 IP（固定 argv 的 `ifconfig`） | `backend/src/toolbox_backend/adapters/net_info.py` |
| 偏好模型（二进制路径、启动超时、协议、隧道上限） | `backend/src/toolbox_backend/domain/services.py` |
| REST（`/api/services/*`） | `backend/src/toolbox_backend/api/services_routes.py`、`services_schemas.py` |
| TG 服务面板（`svc_*` 回调） | `backend/src/toolbox_backend/services/telegram_commands.py` |
| 前端 | `desktop/src/features/settings/{ServicesTab,CodeServerCard,CloudflaredCard,CloudflaredTunnelSheet,CloudflaredImportSheet,NetworkBar}.vue`、`useServices.ts` |

## 怎么用
- code-server：卡片点启动/停止；端口与 host 读自 `~/.config/code-server/config.yaml`，只有确认配置了密码认证（`safe`）才允许启动。
- 默认隧道：启动后从 cloudflared 输出里解析 `https://*.trycloudflare.com`；启动前需确认「公开到公网」（TG 里是「确认公开到公网」按钮）。
- 自定义隧道：「新增」填 `http(s)://localhost|127.0.0.1|[::1]:端口`，并确认公网暴露；可单条删除；数量上限默认 5。
- 协议可切 http2 / quic（改后对已运行的服务提示需重启）；可从旧协议偏好文件导入（`import-legacy`）。
- 日志：`GET /api/services/{name}/logs`（最多 64KiB tail）。

## 注意与坑
- 二进制：优先设置里的绝对路径，其次 `which`，兜底 `/opt/homebrew/bin`；找不到报 `service_binary_missing`。
- 进程由后端持有（`SupervisedProcess` 进程组监督），**不再是旧版的 detached 常驻**：后端退出或被杀，服务和隧道随之关闭；运行状态与隧道 URL 不落盘。
- 查状态只做端口探测：启动时若 code-server 端口已被外部进程占用，标记 `external` 并拒绝再起（`service_port_in_use`），不会去杀它；不再做进程签名扫描。
- 健康监控：进程退出 → `failed`；端口连续 3 次不通 → `unhealthy`。
- 启动环境会剔除 `NODE_OPTIONS`、`CODE_SERVER_CONFIG` 等，避免被继承覆盖。
- 隧道目标只允许回环地址，且必须显式确认（否则 `tunnel_target_forbidden`）。
- 未迁移：**dsh web（Basic Auth 网关、命名隧道、钥匙串密钥、端口 3081、局域网直连）整块未迁移**，`next/` 里没有任何 dsh 代码；cloudflared 命名隧道（`tunnel run --token`）也未支持，只有 quick tunnel；旧版「启动即脱离、重启后读回」未保留。
