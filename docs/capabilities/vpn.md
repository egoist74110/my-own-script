# VPN（Harmony / Check Point SASE 连接 + 自动登录 + TOTP）

## 这个能力做什么
控制本机 SASE 客户端（默认 bundle `com.safervpn.osx.smb`，深链协议 `CheckPointSASE`，可选 `HarmonySASE`）：探测连接、一次「运行」按阶梯自愈、用 Playwright 驱动 Chrome 做 SSO 远程登录（含 MFA）、本地算 TOTP、可选用截屏 OCR 自动点「连接/更新」按钮。桌面端在设置 → 服务页的 VPN 卡；TG `/vpn status`、`/vpn on` 也走同一服务。

## 关键文件（均在 `next/` 下）

| 做什么 | 文件 |
| --- | --- |
| 运行编排（单次只一个 run、阶梯、MFA、历史、取消） | `backend/src/toolbox_backend/services/vpn.py` |
| 偏好模型（客户端/账号信息/超时/窗口自动化模式） | `backend/src/toolbox_backend/domain/vpn.py` |
| REST（`/api/vpn/*`） | `backend/src/toolbox_backend/api/vpn_routes.py`、`vpn_schemas.py` |
| 客户端控制（resolve/status/open/restart，固定 argv） | `backend/src/toolbox_backend/adapters/vpn_client.py` |
| 登录子进程管理、Chrome 身份回收、深链投递 | `backend/src/toolbox_backend/adapters/vpn_browser.py` |
| 登录 worker（Playwright 持久 profile，隔离进程） | `backend/src/toolbox_backend/vpn/login_worker.py` |
| TOTP 计算与 otpauth 导入解析 | `backend/src/toolbox_backend/adapters/vpn_totp.py` |
| 截屏 + Vision OCR + Quartz 点击 | `backend/src/toolbox_backend/adapters/window_automation.py` |
| VPN IP 探测（`utun*` 上匹配隧道前缀，默认 `10.254.`） | `backend/src/toolbox_backend/adapters/net_info.py` |
| VPN 日志 | `backend/src/toolbox_backend/adapters/vpn_log.py` |
| 前端 | `desktop/src/features/settings/{VpnCard,VpnMfaSheet,VpnTotpImportSheet,VpnLegacyImportSheet}.vue`、`useVpn.ts` |

## 自愈阶梯（`VpnService._run`，`max_rung` 可限制）
- 已连（`utun*` 上有隧道前缀 IP）且非 relogin → 直接成功。
- 档 A：`open` 客户端；档 B：quit 后重开（`rungB_restart`）。
- 窗口自动化：仅当 `window_automation` 为 `connect` / `connect_update` 才执行（默认 `off`，会记 `skipped`）；需「屏幕录制 + 辅助功能」双权限，`connect_update` 还会点 Install/Update 并延长预算。
- 档 C：`login_worker` 浏览器 SSO 登录，MFA 码优先用钥匙串里的 TOTP 种子本地算；没有种子则发 `vpn.mfa_required` 事件，120s 内在 UI（`VpnMfaSheet`）手动提交。
- 总预算 `max_run_s`（默认 480s），档超时 `rung_timeout_s`（默认 30s）。

## 怎么用
- 设置里配 workspace / 数据驻留区 / 邮箱，密码与 TOTP 种子存钥匙串（凭据 kind：`vpn_password`、`vpn_totp_secret`）；种子可粘贴含 `otpauth://` 的导出文本导入（`/api/vpn/totp/import`，仅 SHA1/6 位/30s，多个候选需选序号），也可从旧应用导入（`import-legacy`）。
- 点「连接」/「重新登录」得到一个 run（202），可查询/取消；「清除浏览器数据」删持久 profile（运行中不可清）。

## 注意与坑
- 深链：登录 worker 用 CDP 事件截获 `<scheme>://…/callback`（协议名按小写比较），再通过 NSWorkspace 只投递给所选客户端 app；URL 只在内存、不进 argv/日志。截不到报 `login_callback_not_captured`。
- 持久 Chrome profile 在后端数据目录 `vpn/chrome-profile`（0700）；浏览器用 `--remote-debugging-pipe`，退出时按 pid+启动时间精确回收，不误杀用户自己的 Chrome。
- 客户端是 background-only Electron，辅助功能树扫不到，更新/连接按钮只能靠 OCR；点击有预算限制。
- 登录/窗口自动化依赖 macOS 原生模块（playwright、AppKit、Quartz、Vision）；缺失时对应阶梯返回「未实现」类错误。
- 使用系统 Chrome（`channel=chrome`，可用 `chrome_path` 指定）；仅「已有 TOTP 种子且 headless=true」才无头，否则弹出可见窗口；登录时会勾「Remember this browser」以减少后续令牌输入。
- MFA 码与种子只在内存传递，不落盘；日志脱敏。
- 登录选择器与入口仍沿用旧版 Perimeter81 页面（`login_worker.py` 内注释写明待真实验收），页面改版会报 `login_selector_missing`。
- 未迁移/变化：CLI 子命令（`python -m app_ado.vpn_login …`）已无，改为 REST/桌面端；Ente 导出文件不再「读完即删」（改为粘贴文本导入，不碰文件）。
