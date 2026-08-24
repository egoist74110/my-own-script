# VPN（Harmony SASE 连接 / 自动登录 / TOTP / 更新点掉）

## 这个能力做什么
控制本机 Harmony SASE 客户端：检测连接、自愈重连、Perimeter81 SSO 远程自动登录（含 MFA）、从 Ente Auth 导出取 TOTP 种子本地算码、点掉 app 内的「更新提示」。

## 关键文件

| 做什么 | 文件 |
| --- | --- |
| 连接控制 + 自愈阶梯（档0/A/B/C） | `app_ado/vpn_control.py` |
| 探测 VPN IP（扫 utun* 找 10.254.x.x） | `app_ado/vpn_ip.py` |
| Playwright 自动登录（系统 Chrome 持久 profile + CDP 截深链 + MFA 回调） | `app_ado/vpn_login.py` |
| Ente Auth 导出抽 TOTP 种子（存 keychain，读完即删导出文件） | `app_ado/vpn_totp.py` |
| 截屏 + Vision OCR + Quartz 点击「Install/Update」 | `app_ado/vpn_update.py` |
| VPN 凭据（workspace/residency/邮箱/密码/TOTP） | `app_ado/secrets.py`（`get_vpn_config`/`get_totp_secret`） |
| TG `/vpn` 命令（状态/异步连接） | `app_ado/tg_control.py`（`_vpn_*` 方法） |

## 自愈阶梯（`vpn_control.ensure_connected` 一次调用自动升级）
- 档 0：已连（10.254.x）→ 直接返回。
- 档 A：app 没开 → `open -a` 重开。
- 档 B：开着但断连 → quit + open 重启 app（避开易碎的菜单栏点击）。
- 档 C：登录失效 → `vpn_login` 浏览器 SSO 重登（MFA 令牌走 `token_provider` 回调）。
- A/B 超时仍连不上 → 自动落 C。

## 怎么用（CLI）
```bash
python -m app_ado.vpn_login setup    # 存凭据到 keychain
python -m app_ado.vpn_login login    # 跑登录，提示输 6 位令牌
python -m app_ado.vpn_totp import <ente导出文件>   # 抽种子、存、删文件
python -m app_ado.vpn_update perm    # 查屏幕录制权限
python -m app_ado.vpn_update scan    # 截屏+OCR 打印目标（不点）
python -m app_ado.vpn_update click   # 真点 Install/Update
```
TG：`/vpn` 看状态/触发连接。

## 注意坑
- Harmony 是 background-only Electron，**macOS 辅助功能完全扫不到它**（0 个 window 节点），所以更新按钮走截屏 OCR，不走 AX。
- OCR 点击需要「屏幕录制 + 辅助功能」双权限，缺了直接报错提示。
- MFA 令牌只过内存不落盘；Ente 导出文件含所有账号 2FA 种子，**读完立刻删**。
- 深链 `HarmonySASE://...` 双保险：CDP 截 URL + 真 Chrome 自然唤起 app，截到后 `open` 确保 app 收到 token。
- 登录后勾 "Remember this browser"，一段时间内可少输/免输令牌（持久 Chrome profile 在 `~/.config/my-own-script/vpn_chrome_profile`）。
