# 服务管理（code-server / cloudflared 隧道 / VPN 地址）

## 这个能力做什么
「服务」Tab（与 TG 服务面板共享同一套后端）管理本机临时服务：code-server 启停、cloudflared quick tunnel 启停（暴露本地服务）、显示当前 VPN IP。核心解决「关了 bot 服务还在、重启后找不回/关不掉」。

## 关键文件

| 做什么 | 文件 |
| --- | --- |
| 服务后端（启停/状态/落盘/端口与签名扫描） | `app_ado/services_panel.py` |
| UI 服务 Tab | `app_ado/ui/services_tab.py` |
| TG 服务菜单（inline 回调） | `app_ado/tg_control.py`（`_handle_svc_callback`） |
| VPN IP 读取 | `app_ado/vpn_ip.py` |

## 设计要点（都在 `services_panel.py` 注释里）
- 进程 **detached 启动**（`start_new_session`），脱离 bot 独立常驻。
- PID/启动时间/cloudflared 域名落盘 `~/.config/my-own-script/services/<name>.json`，bot 重启能读回。
- 查状态不只信状态文件，还**主动扫端口**（code-server）/**进程签名**（cloudflared），状态文件丢了或手动起的服务也能发现。
- 关闭双兜底：状态文件 PID 杀进程组 + 端口/签名扫描。
- cloudflared 只认 quick tunnel 签名 `cloudflared tunnel --url`，绝不误伤 root 的 `tunnel run --token` 常驻命名隧道。

## 怎么用
- UI：服务 Tab 里对 code-server / cloudflared 点启动/停止，看 VPN IP。
- cloudflared 可切协议（`set_cloudflared_protocol`）；域名从 quick tunnel 日志里解析（`*.trycloudflare.com`）。
- code-server 端口/密码读自 `~/.config/code-server/config.yaml`。

## 注意坑
- 依赖 `cloudflared` / `code-server` 二进制（`_bin` 优先 `which`，兜底 `/opt/homebrew/bin/`），没装会报找不到。
- 杀进程用进程组（`killpg`），避免残留子进程。
- 别把命名隧道（`tunnel run --token`）当 quick tunnel 处理，会误杀 root 常驻服务。
