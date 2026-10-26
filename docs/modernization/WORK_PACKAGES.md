# 工作包（阶段 0/1 与新产品切片）

- plan_id: modernization-20261021
- revision: 11（2026-10-26 S6 十一项待决按推荐确认；此前 10：S5 十项待决按推荐确认）
- 2026-10-26：S0–S5、R1 与阶段 0/1 的合同已原样移入 [archive/](archive/README.md)；本文件只保留当前切片。
- base: c349243286d27ae82943a4381951f9f3b041b7d1 + 账本所列用户修改
- executor_autonomy: standard
- max_same_failure_attempts: 2
- delivery: 阶段 0/1 为本地文件与验证报告；S0 起用户授权在 `rewrite/next` 本地提交，不 push/merge/publish/deploy
- workflow: [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md)
- 状态、真实署名和检查结果只写 [PROGRESS.md](PROGRESS.md)，不能在本文件预填通过。
- 2026-10-22：方向改为前后端分离重写。WP-03、WP-11..16 的处置已由用户确认（见 [MIGRATION_PLAN.md §4](MIGRATION_PLAN.md)）。新产品切片的合同派工前追加到本文件，切片完成后移入 archive。

# 新产品切片

切片顺序与“搬完”标准见 [MIGRATION_PLAN.md](MIGRATION_PLAN.md)。新代码只在 `next/` 下；`next/` 以外的旧代码只读，不 import。

合同中引用的已归档小节（如「S0 已定接口」「S1-A 主控裁决」「协议核对结论」、S4/S5 所有权切换步骤）按 [archive/README.md](archive/README.md) 的「常被引用的小节」表定位，只读对应文件的那一节。

当前切片：**S8 VPN**（合同草案，待用户确认「S8 待决」，见下文「S8」；S7 已于 2026-10-26 集成验收并归档到 [archive/work-packages/S7.md](archive/work-packages/S7.md)）。确认前不派工。

# S8：VPN（合同草案，2026-10-26，待用户确认「S8 待决」）

状态：**草案，未确认，不派工**。输入基线：新版 `rewrite/next @ 82a6904`，旧版 `main @ 885d186`（`git status` 确认 VPN 相关旧文件无未提交改动；只读）。本轮未读真实配置/凭据（Keychain、`~/.config/my-own-script`、Ente 导出文件均未读），未启动/停止任何 VPN 或浏览器、未联网、未触发任何点击；仅对本机已装客户端读了 `Info.plist`、`ps`、`ifconfig`（只读，见「S8 事实核实」）。
依据：ARCHITECTURE §2/§4/§5（进程所有权、长操作统一模型、单例资源切换）、MIGRATION_PLAN S8 行（连接自愈、远程登录、TOTP、更新提示处理）、旧 `docs/capabilities/vpn.md`、S4 已决 1（主 Bot 切换等 S6–S8 菜单迁完）、S5 `proc_supervisor`、S6/S7 的状态机/监督器/日志脱敏做法与 S7 `adapters/net_info.py`。
本合同覆盖：VPN 状态读取、连接自愈阶梯（档 0/A/B/C）、浏览器 SSO 远程自动登录（含 TOTP 本地计算）、窗口自动化（点 Connect / 点更新按钮，截屏 OCR + 合成点击）、凭据与 TOTP 种子管理、`vpn` 配置段、桌面 VPN 卡、TG `/vpn` 与服务菜单 VPN 项。**不含**：远程断开（root helper 维持隧道，旧端也不支持）、自动周期性看门狗（待决8）、主 Bot 所有权切换（S8 验收后另议）、Windows、launchd 常驻。

## S8 事实核实（主控亲自只读核对）

以下位置相对旧目录 `/Users/wesker/my-own-script`；是静态代码事实，不代表真实流程已验证。

### 文件与职责

- `app_ado/vpn_control.py`（272 行）：自愈阶梯与应用控制；`vpn_login.py`（347）：Playwright SSO；`vpn_totp.py`（149）：Ente 导出抽种子 + 本地算码；`vpn_update.py`（442）：截屏 OCR + Quartz 点击；`vpn_ip.py`（37）：`ifconfig` 扫 `utun*` 取 `10.254.` 地址（S7 已迁成 `net_info.vpn_ip`）；`secrets.py:55–80,140–170`（`harmony_vpn:{workspace,residency,email,password}`、`harmony_vpn:totp_secret`、`harmony_vpn:totp_filter`，Keychain 服务 `my-own-script`）；TG `tg_control.py:840–915`（`/vpn on|status|off`，仅 owner；连接在后台线程）、`:930–940`（`svc:vpn`/`svc:vpn:on`）、`tg_help_inline.py:62,118–122`；UI VPN 卡 `ui/services_tab.py:81–250`（配置对话框回填明文密码 `:49`、导入 Ente 导出路径 `:92–112`、后台线程连接 `:114–160`）。

### 自愈阶梯（`vpn_control.ensure_connected` `:131–186`）

- 档 0：`get_vpn_ip()`（utun 上 10.254.x）有值即已连——**唯一真相**（退出 app 不断隧道：root helper `com.perimeter81d` + wireguard-go 维持）。档 A：app 没在跑 → `open -a`；档 B：在跑但没连 → `osascript quit` + 1.5 秒 + `pkill -f` 兜底 + `open -a`（`:42–52,112–120`）；A/B 各等 30 秒（`wait_connected` `:88–109`，途中每 4 秒窗口自愈 `resolve_window`，见下，点到更新则整体延长到 ≥180 秒）；仍未连 → 档 C：`login_flow`。
- 令牌：有 Ente 种子则本地算码并 headless，否则回退 `token_provider`（CLI `input()`；TG/UI 路径传 `None` 即无种子不登录）（`:189–208`）。`relogin`（`:211–224`）无视当前状态强制重登。
- **同步阻塞**：全流程在调用线程里 `time.sleep` 轮询；TG 与 UI 各自开线程包一层（`tg_control.py:871–904`、`services_tab.py:139–156`），无取消、无并发保护（多次点击可并发起多条流程，各开一个 Chrome）。

### 登录（`vpn_login.login_flow` `:101–303`）

- Playwright + **系统 Chrome**（`channel="chrome"`）持久 profile `config_dir/vpn_chrome_profile`（`:48–51`，含 SSO cookie 与“记住此浏览器”）；入口 `https://app.perimeter81.com/sign-in?redirectUrl=HarmonySASE://perimeter81.com/macos/callback&allowTenantSelect=`（`:30–33`）；步骤：填 workspace（+ 数据驻留区下拉 `:152–171`）→ 邮箱/密码 → 等 `/mf` 页找 6 位令牌框（6 组选择器 `:206–228`）→ 填码、勾 “Remember this browser” → 等回调。
- **回调深链**：小写 `harmonysase://…#id_token=<JWT>&tenant_id=…`，CDP `Page.frameRequestedNavigation/ScheduledNavigation` 捕获（大小写不敏感，`:130–142`）；捕获后 `open -a` 起 app、等 ≤15 秒再 +3 秒，之后**每 8 秒重发** `subprocess.run(["open", captured_url])`（`:285–298`，**JWT 进 argv**）；日志截 72 字符深链前缀（`:134`，含 JWT 头部若干字符）；`_dump_inputs` 把页面控件属性写日志（`:83–98,204`）；`cfg["password"]` 仅内存，但页面 `fill` 明文。
- 总等待 75 秒，更新提示/捕获各自延长到 180/30 秒（`:260–303`）。MFA 令牌只过内存。

### TOTP（`vpn_totp.py`）

- 种子来源：Ente Auth 的“明文导出”文件，**由服务端按用户给的路径读取**（`:70–110`），无论成败都 `path.unlink()`（`:105–110`，等于“替用户删任意路径文件”，且不是安全擦除）；筛选关键词默认 `Perimeter`，匹配多条时**静默取第一条**（`:95–104`）；`pyotp` 本地算码（`:113–120`）。种子与密码同存本机钥匙串（用户明确选择的便利取舍，见项目记忆；合同如实记录，不改）。

### 窗口自动化（`vpn_update.py`）

- 原因：客户端是 background-only Electron，对辅助功能(AX)完全不可见 → 只能 `Quartz` 截屏 + `Vision` OCR（限 en-US）找按钮文字 + `CGEventPost` 合成鼠标点击（`:50–250`）；OCR 命中限定在客户端窗口矩形内（`CGWindowListCopyWindowInfo` 按 `kCGWindowOwnerName` 等于应用名筛、仅 layer 0，`:250–277`）；按钮文字白名单/黑名单与长度 ≤24（`:40–45`）；更新是两步（Update→Install→Restart，4 秒轮询衔接）；Connect 仅在窗口显示 Connect/Reconnect 时点（`:206–228,351–363`）；`surface_app` 每 ≤12 秒 `open -a` + `osascript set frontmost` 抢前台（`:75–93`）。需要“屏幕录制”（截屏）、“辅助功能”（合成点击）、System Events 自动化权限。**合成点击会真实移动用户鼠标**。
- 依赖 `pyobjc`（Quartz/Vision）与 `playwright`/`pyotp`：**新后端 `pyproject.toml` 一个都没有**（本轮 `site-packages` 核对）。

### 本机客户端实况（只读核对，2026-10-26）

- **客户端已改名**：`/Applications/Check Point SASE.app`，`CFBundleIdentifier=com.safervpn.osx.smb`，`CFBundleName/Executable=Check Point SASE`，版本 **13.1.0**；已注册 URL scheme 同时含 `HarmonySASE`、`CheckPointSASE`、`perimeter81`、`safervpn`；后台 helper 仍是 `/Library/PrivilegedHelperTools/com.perimeter81d.app`（wireguard-go）；当前 `utun4` 带 `10.254.x.x`。
- **旧代码全部硬编码 “Harmony SASE”**：`APP_NAME`、`pgrep -f "Harmony SASE.app/Contents/MacOS"`（`vpn_control.py:22–23,31–34`）、`open -a "Harmony SASE"`（`:39`、`vpn_login.py:288`、`vpn_update.py:85`）、`osascript … process "Harmony SASE"`（`vpn_update.py:87–90`）、OCR 窗口筛选 `kCGWindowOwnerName == "Harmony SASE"`（`:263`）。在 13.1.0 上这意味着：`app_running()` 恒 False（每次都判“app 没开”）、`open -a` 找不到应用、OCR 窗口矩形恒为空（窗口自愈整体失效）。**只有“已连接”的读取（utun 10.254）仍然有效**。旧端这一回归尚未被日常使用暴露（连接一直在）。
- 未核实：新品牌下 SSO 入口 URL/页面选择器、`redirectUrl` 用 `HarmonySASE://` 还是 `CheckPointSASE://` 是否仍有效、窗口 OCR 文案（Connect/Update/Install 是否改版）、窗口 owner name。这些只能在真实登录/真实窗口上验证（真实验收，需授权与凭据）。

### 旧坑与已知风险（合同依据）

1. 应用名硬编码，新版本全面失效（上）；2. `pkill -f` 按模式杀进程；3. 同步 `sleep` 阻塞线程、无取消、无并发保护（可同时起多个 Chrome 登录）；4. 深链 JWT 进 argv 且重复发；5. 日志里有深链前缀、控件 dump；6. Ente 导出由服务端读路径并删文件、多匹配静默取第一条；7. UI 配置对话框回填明文密码；8. `surface_app` 周期抢前台、合成点击移动真实鼠标，权限缺失时只在日志里提示；9. `vpn_login` 随 CLI `pip install playwright` 运行时联网装包；10. Chrome profile 含 SSO cookie，无“忘记”入口；11. 连接前缀 `10.254.` 硬编码；12. 登录页选择器与 URL 硬编码、无版本兜底，页面一变整条链路静默失败。

### 新端现状

- 无任何 S8 代码；S7 已提供 `adapters/net_info.py`（固定参数 `ifconfig`、`vpn_ip`）与服务页网络信息条；S7 的 TG 服务菜单 VPN 项目前只显示“VPN 管理见 S8”（`services/telegram_commands.py:526`）。配置 schema 当前 v5（`domain/settings.py:237`）；凭据适配器可只读旧 Keychain `my-own-script`、写 `toolbox-next`；`proc_supervisor`/`SupervisedProcess` 与 S6/S7 的 `Lifecycle`/状态机/日志脱敏可直接作样板。新端依赖：httpx、websockets 等（**无 playwright/pyobjc**）。

## S8-0：本机核对（主控；待决1 授权后做）

可在不联网、不登录的前提下核对：① PyObjC（Quartz/Vision/Cocoa）与 Playwright 在新 venv 的可用性与 wheel 来源（解析依赖需联网一次 `uv lock`，需授权）；② Playwright 驱动系统 Chrome 打开本地 `data:`/`http://127.0.0.1` 假 SSO 页（**不访问任何真实站点**）验证 persistent context 与 CDP 深链捕获手法；③ 客户端窗口的真实 owner name 与窗口矩形（`CGWindowListCopyWindowInfo` 不需屏幕录制权限即可读 owner/bounds）；④ 当前进程是否已有屏幕录制/辅助功能权限（`CGPreflightScreenCaptureAccess`/`AXIsProcessTrusted`，只读）。**不做**：真实 SSO 登录、点击客户端窗口、退出/重启客户端（均属真实验收）。结论写回本节，优先于下文。

## S8 数据模型与访问边界（主控技术裁决；涉及取舍的见「S8 待决」，下文“推荐”按待决推荐写，确认后以「S8 已决」为准）

实现完成须按 backend-architecture-review、backend-security-review、backend-business-safety、data-consistency-review、resource-lifecycle-audit、production-readiness-review 复核。

### 架构五问

1. **产生什么数据**：config schema v6 新增类型化 `vpn` 段（非密配置）；Keychain `toolbox-next` 新 account `vpn_password`、`vpn_totp_secret`（kind 同名）；`<data-dir>/vpn/` 下：Chrome 持久 profile（0700，含 SSO cookie，可一键删除）、脱敏日志 `logs/vpn.log`（5 MiB×2、0600）。**不新增 SQLite**：运行记录只在内存（最近 20 条，待决9），连接真相每次从网络接口重读。不落盘任何截屏、OCR 全文、深链、令牌。不复制旧端 Chrome profile（待决7）。
2. **数据流**：桌面/TG（owner）→ S0 Bearer HTTP/WS / TG → `VpnService` →（状态）`net_info`（`ifconfig`）、`ClientController`（`ps`/`open`/`osascript`，固定参数）；（登录）`VpnService` → **受监督登录子进程** `python -m toolbox_backend.vpn.login_worker`（凭据与 TOTP 种子经 stdin 启动 JSON 传入，进度/结果经 stdout JSON 行返回）→ Playwright → 系统 Chrome → Check Point SASE SSO（出站发生在第三方进程）；（窗口自愈）`VpnService` → `WindowAutomation`（Quartz 截屏/Vision OCR/合成点击，仅在内存中处理帧）。后端自身无新增 HTTP 外部出站。
3. **谁能访问**：HTTP/WS 为单一本机主体（S0）；凭据只写不读回；TG 仅 owner；窗口自动化需用户在 macOS 授予“屏幕录制/辅助功能”且在页面显式开启（待决2）；SSO 凭据与 TOTP 种子同机并存是用户已接受的取舍（项目记忆），合同不改变但在页面如实提示。
4. **并发冲突**：每数据目录一个 `VpnService`（沿用后端 flock）；同一时刻最多一条连接运行（409 `vpn_busy`），可取消；状态读取读快照、不等锁；新旧应用不得同时对同一客户端执行连接/登录（无跨进程锁，靠切换步骤约束，见所有权切换）；配置写冲突沿用 revision 409。
5. **失败/清理**：登录 worker、Chrome、网络探测等一律经 `proc_supervisor`：后端被强杀 → 控制管道 EOF → TERM 进程组 → 3 秒 → KILL（Chrome 随 worker 进程组回收）；运行总预算上限（默认 8 分钟）与取消均走同一收尾路径；对**客户端本身**（第三方应用，非我们启动）只做：AppleScript 优雅退出、以及待决4 允许时对**身份核对过的精确 PID** 发 TERM，**绝不 `pkill -f`/按模式杀、绝不 SIGKILL**；窗口自动化每次运行点击次数上限与超时。后端退出：lifespan 中 VpnService 与 Mcp/Services/AI 并行收尾，总预算不变（≤5 秒）。

### config schema v6（`vpn` 段；v5→v6 只新增，迁移快照/原子写/幂等同前）

```
vpn:
  client: {bundle_id: "com.safervpn.osx.smb", app_name: null, url_scheme: "CheckPointSASE"}   # app_name null=按 bundle id 自动解析；url_scheme 枚举 HarmonySASE|CheckPointSASE
  tunnel_prefix: "10.254."                    # 连接判定的 utun 地址前缀（合法 IPv4 前缀）
  login: {workspace: "", residency: "US Data Residency", email: "", totp_filter: "Perimeter", headless: true}
  window_automation: "off"                    # off | connect | connect_update（待决2）
  rung_timeout_s: 30                          # 档 A/B 每档等待，5–120
  login_timeout_s: 75                         # 登录等待，30–300
  max_run_s: 480                              # 单次运行总预算，120–1200
  chrome_path: null                           # null=自动（/Applications/Google Chrome.app）；用户确认后的绝对路径
```
- 迁移：不读旧 Keychain/配置；`login.*` 由用户填写或“从旧应用导入”（只读 `harmony_vpn:{workspace,residency,email,totp_filter}` 与秘密项，旧条目不改不删）。`workspace`/`email` ≤200 字符、禁控制字符；`residency` 只允许后端枚举（US/EU/India/Australia/CA Data Residency）；`tunnel_prefix` 形如 `a.b.` 或 `a.b.c.`；`chrome_path` 绝对路径、可执行、属主为当前用户或 root、非 world-writable。

### 凭据

- `vpn_password`、`vpn_totp_secret` 写入 `toolbox-next`；HTTP 只写（PUT/DELETE），GET 只返回 `configured`；**页面/日志/事件/TG 永不回显密码或种子**（旧端对话框回填明文密码，不迁移）。旧 Keychain 条目仅经显式“从旧应用导入”读取。
- TOTP 种子导入（待决5）：`POST /api/vpn/totp/import` 请求体为**导出文本或单条 `otpauth://` URI**（≤1 MiB、仅内存解析、不落盘、不读路径、不删用户文件；页面提示“导入后请自行删除导出文件”）；按 `totp_filter` 筛选，**多条匹配返回 409 `totp_ambiguous` + 各条 issuer/label（不含 secret）供选择**，提交 `index` 才保存；仅接受 SHA1/6 位/30 秒，其他返回 `totp_unsupported`；种子只存 Keychain，TOTP 计算用标准库（RFC 6238，不引入 pyotp），令牌只在内存、永不记录。
- 子进程注入：登录 worker 的凭据（email/password/seed）**只经 stdin 启动 JSON**，不进 argv/环境；worker 环境 = S5 过滤后环境 + PATH 补全，**不继承** `PLAYWRIGHT_*`/`NODE_OPTIONS`；cwd=`<data-dir>/vpn/run/`（0700 空目录）。

### 客户端控制（`adapters/vpn_client.py`，`ClientController`）

- 身份由 `bundle_id` 解析：枚举 `/Applications`、`~/Applications` 的 `*.app/Contents/Info.plist` 找匹配 bundle id（回退名称 `Check Point SASE`、`Harmony SASE`），得到 `app_path`、`app_name`、可执行名；**不再硬编码名称**。运行判定：`ps -axo pid,lstart,command` 中命令以 `<app_path>/Contents/MacOS/` 开头的主进程（排除 helper）。
- 打开：`open -b <bundle_id>`；优雅退出：`osascript -e 'tell application id "<bundle_id>" to quit'`；强退仅在待决4 允许时对上面解析出的**精确 PID**（再核对 lstart 未变）发一次 TERM，等 ≤3 秒，仍在则报告 `client_stuck` 不再升级。固定参数数组、超时与输出上限、不经 shell。
- 深链：登录 worker 捕获的回调 URL 交给 app 时**不经 argv**（NSWorkspace `openURLs:withApplicationAtURL:`，pyobjc）；URL 仅在内存、日志只记 scheme 与“已交付/次数”；重发间隔 8 秒、至多 6 次；URL 必须以配置的 `url_scheme`（大小写不敏感）开头，否则丢弃。

### 窗口自动化（`adapters/window_automation.py`；待决2）

- 能力分级 `window_automation`：`off`（默认，不截屏不点击）→ `connect`（仅在客户端窗口内、显示 Connect/Reconnect 时点 Connect，排除 Disconnect/Connected to/Change Network）→ `connect_update`（另处理更新三步 Update→Install→Restart，沿用旧白名单/黑名单与长度 ≤24）。
- 安全边界：只处理**属于客户端 bundle 的窗口矩形内**的 OCR 结果（`CGWindowListCopyWindowInfo` 按 owner PID/名称，layer 0）；帧只在内存、**不写盘不记录文字**（只记录命中的按钮文案与坐标是否在矩形内）；每次运行点击总数 ≤8、同一按钮 ≤2；点击前置条件=客户端窗口在前台且鼠标不在用户正在操作的窗口外区域以外（实现细节由施工方给出并测试），**点击会移动真实鼠标，页面须说明**；缺“屏幕录制/辅助功能”时返回 `window_permission_missing` 且**不降级为无声失败**，`GET /api/vpn` 暴露两项权限的只读状态。`surface_app` 不再周期抢前台：仅在需要截屏的轮询中至多每 30 秒一次。
- **可测试性**：OCR/点击放在 `WindowAutomation` 接口后，真实实现只在 macOS 且依赖 pyobjc；纯函数（候选按钮挑选、矩形过滤、坐标换算）以假 OCR 结果单测；真实屏幕行为只在真实验收验证。

### 登录 worker（`toolbox_backend/vpn/login_worker.py`；待决3）

- 受监督子进程，stdin 一行 JSON 启动参数（含凭据）、stdout 逐行 JSON 事件 `{event: step|need_mfa|captured|done|error, ...}`（行 ≤64 KiB，事件字段不含密码/令牌/完整深链）；可被取消（控制管道 EOF/SIGTERM 即关浏览器退出）。
- 浏览器操作经 `BrowserDriver` 接口（Playwright 实现 + 假实现），选择器与入口 URL 放在**一张数据表**（可按“品牌”切换：`perimeter81`/`checkpoint`，S8-0/真实验收后定默认），步骤含：workspace→residency→邮箱/密码→MFA→回调捕获；每步有超时与明确错误码（`login_selector_missing`、`login_credentials_rejected`、`login_mfa_rejected`、`login_timeout`、`login_callback_not_captured`），**不 dump 页面控件属性**，不截图落盘。
- Chrome：系统 Chrome（`channel=chrome` 等价，不下载 Chromium），持久 profile `<data-dir>/vpn/chrome-profile`（0700）；`headless` 取配置（有种子默认 true；无种子需手输令牌时强制有头）；`DELETE /api/vpn/browser-profile` 清空（“忘记此浏览器”，运行中 409）。
- MFA：有种子 → worker 请求 `need_mfa` 时由 `VpnService` 用种子计算并回传一次（令牌 30 秒窗口内、≤2 次重试）；无种子 → 待决6 的桌面手输（WS 事件 `vpn.mfa_required`，`POST /api/vpn/runs/{id}/mfa {code}`，120 秒超时，TG 不支持手输）。

### 连接自愈（`VpnService`；运行模型沿用 ARCHITECTURE §4 的子集）

- `POST /api/vpn/connect` → 立即返回 `run_id`，状态 `queued|running|cancelling|cancelled|succeeded|failed`；步骤事件：`rung0_connected`、`rungA_open`、`rungB_restart`、`window_connect`、`window_update`、`rungC_login`、`waiting_connection`、`done`（含 `ip`，失败含 `error_code` 与脱敏尾日志）。阶梯语义同旧端，但：A/B 判断用 bundle id；窗口自愈只在 `window_automation!=off` 且权限满足时参与（否则跳过并在事件里标 `skipped:window_automation_off`）；更新被点到时总预算延长至 `max_run_s`（不是无限）；总预算耗尽 → `failed(max_run_exceeded)`；`allow_login=false` 的 A/B-only 仅供测试（请求体字段 `max_rung`）。
- `POST /api/vpn/relogin`（无视当前状态强制重登，`check_existing=False`）；`POST /api/vpn/runs/{id}/cancel`；`GET /api/vpn/runs/{id}`、`GET /api/vpn/runs`（最近 20 条，内存）。同一时刻只一条运行，409 `vpn_busy`；`request_id` 幂等。
- 状态：`GET /api/vpn` → `{connected, ip, client{installed, running, app_name, version?}, credentials{password, totp_secret: configured}, permissions{screen_recording, accessibility}, settings, current_run?, revision}`；`ip` 来自 net_info（运行中每 1.5 秒直读 `ifconfig`，**不依赖 S7 的 5 秒缓存**）；`vpn.status` 事件在连接状态或运行状态变化时推送。

### HTTP / WS 接口（全部在 S0 Host/CORS/Bearer/BodyLimit 之后；错误沿用 S1 detail 结构）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/vpn` | 状态快照（见上） |
| PATCH | `/api/vpn/settings` | `vpn.*` 设置（revision 409；运行中改 → 409 `vpn_busy`） |
| PUT/DELETE | `/api/vpn/credentials/{vpn_password\|vpn_totp_secret}` | 只写 |
| POST | `/api/vpn/totp/import` | 导出文本/URI（见凭据；多匹配 409 `totp_ambiguous`） |
| POST | `/api/vpn/credentials/import-legacy` | `{kinds:[…], fields:bool}` 从旧 Keychain 只读导入（旧条目不改不删） |
| POST | `/api/vpn/connect`、`/api/vpn/relogin` | 启动运行，返回 `run_id` |
| POST | `/api/vpn/runs/{id}/cancel`、`/api/vpn/runs/{id}/mfa` | 取消 / 手输令牌（待决6） |
| GET | `/api/vpn/runs`、`/api/vpn/runs/{id}` | 运行记录（内存） |
| DELETE | `/api/vpn/browser-profile` | 清空 Chrome profile |
| WS 主题 | `vpn` | `vpn.status`、`vpn.run`（步骤事件）、`vpn.mfa_required`；回放/水位同 S3 规则 |

新错误码：`vpn_busy`、`vpn_client_missing`、`vpn_not_configured`、`vpn_mfa_required`、`totp_ambiguous`、`totp_unsupported`、`window_permission_missing`、`client_stuck`、`max_run_exceeded`、`login_*`（见上）；均不含凭据与路径细节。

### TG（owner-only，与桌面同一应用服务方法）

- `/vpn status|on`（`off`/断开：沿用“不支持，须在客户端里点 Disconnect”的说明）；服务菜单 VPN 项替换 S7 占位：状态 + 「🔌连接」；连接立即回复“已开始”，运行结束再发一条结果（成功含 IP；失败含错误码与脱敏摘要，不含日志全文）。**状态/结果文本永不含邮箱/密码/种子/深链**。无种子且无桌面在线 → 回复“需先在桌面端配置”。

### 安全核对表（施工与验收都按此）

1. 任何子进程 argv 不含密码/种子/令牌/深链 URL；凭据只经 stdin；静态扫描 + 替身打印 argv/env 断言。
2. 凭据只写不读回；密码/种子/令牌/深链/完整 OCR 文本不入日志/事件/WS/错误/TG/落盘；脱敏器注册密码与种子；扫描假密钥。
3. 不 `pkill -f`、不按模式杀进程、不 SIGKILL 客户端；对客户端只做 AppleScript 退出与（若允许）精确 PID 的一次 TERM；单测断言“同名无关替身进程毫发无损”。
4. 窗口自动化默认 off；开启需权限就绪；点击限定客户端窗口矩形、次数上限、白/黑名单；帧不落盘；权限缺失显式报错。
5. 单运行互斥 + 取消；总预算；worker/Chrome 随后端 SIGKILL 零残留；状态读取不起子进程以外的阻塞。
6. Chrome profile 0700、可一键清除、不复制旧端 profile；`chrome_path` 校验。
7. TOTP 导入不读路径、不删用户文件、多匹配须明确选择；仅 SHA1/6/30。
8. 登录入口 URL 与选择器来自数据表，不接受请求参数传入的 URL；深链 scheme 校验。
9. 路由全部 Pydantic DTO，契约重新生成；无新增后端 HTTP 外部出站。
10. 新增依赖（playwright、pyobjc 子集）仅限 darwin 标记并锁定；运行时不 `pip install`、不联网取包（待决1）。

## S8 通用合同与模型分工

- **派工门禁**：用户确认本合同与「S8 待决」；主控写入「S8 已决」并提交输入 SHA；若待决1 授权，主控先完成 S8-0 并把结论写回本节，再派 S8-B。
- 模型分工（用户偏好）：**后端施工 codex exec `gpt-6.1-sol` / medium（workspace-write、不联网）或 Gemini 4（`gemini-4-argon`，仅后端）**，额度不足换下一候选；测试 codex `gpt-6-luna` / high 或 Claude Haiku 5.5（每包至多一个，仅写 `tests/independent/s8x/`）；**前端施工 agy `gemini-3.8-flash-high`**、`--sandbox`、`--print=`；lead 用 Sonnet，S8-0 与集成验收的安全核对用 Opus；不做交叉审计。实际型号/档位运行前核验，不可验证记 unknown。
- 每包 worktree `.local/worktrees/s8{a,b,c}`，detached 自输入 SHA；施工者不 commit；主控核对 diff 与沙箱外全量测试后以限定路径 binary patch 集成。
- 测试只用临时数据目录、内存凭据、**替身**：假 `ifconfig`（有/无 VPN、多 utun）、假 `ps`/`open`/`osascript`（`ClientController` 固定参数的输入输出）、假客户端 bundle（临时目录里的 `Info.plist`）、假 login worker（正常/各错误码/挂起/大量输出/忽略 TERM/派生孙进程）、假 `BrowserDriver`（脚本化的页面步骤，含选择器缺失/凭据被拒/MFA 被拒/回调未捕获）、本地假 SSO HTTP 页（仅回环）、假 `WindowAutomation`/假 OCR 结果；**禁止调用真实 Chrome、Playwright 真实浏览器、真实 `open`/`osascript`/`ps`（客户端相关）、真实 Quartz/Vision 点击、真实 Keychain、联网**（PATH 只含替身目录，命中即失败）；沿用 conftest keyring/socket 守卫；端口用随机端口。
- 禁止：按进程名 kill、裸 git stash、删除/放宽既有测试、仓库内留报告、改旧应用、读真实配置/凭据/Ente 导出、真实登录/点击/退出客户端、联网（S8-0 授权项与真实验收除外，均需授权）。

## S8-A：后端——config v6、凭据、TOTP、客户端控制、运行模型、HTTP/WS、TG

- write_scope：`next/backend/**`、`next/contracts/**`；测试员仅 `next/backend/tests/independent/s8a/`。
- 结果：v5→v6 迁移；两条凭据与旧 Keychain 导入；TOTP（RFC 6238 标准库、导入解析与多匹配选择）；`adapters/vpn_client.py`（bundle id 解析、运行判定、`open -b`、AppleScript 退出、精确 PID 的受限 TERM）；`VpnService`（运行模型、阶梯编排、取消、预算、事件、日志脱敏、`ClientController`/`LoginRunner`/`WindowAutomation` 三个接缝）；`/api/vpn*` 与 `vpn` WS 主题；TG `/vpn` 与菜单项；lifespan 接入与关闭预算；契约重新生成；README S8-A 段。登录 worker 与窗口自动化的**真实实现**在 S8-B，本包用接缝 + 假实现覆盖编排。
- 自动验收：迁移幂等与快照；状态读取（有/无 VPN、客户端缺失/未运行）；单运行互斥与取消；A→B→C 各档判定与跳档、预算耗尽、更新延长；窗口自动化关闭时跳过并记录；`totp/import` 单条/多条/不支持算法/超大/无匹配；TOTP 向量（RFC 6238 官方测试向量）；凭据只写；argv/env/日志/事件/TG 扫描无假密码与种子；同名无关替身进程在 B 档“退出”流程中毫发无损；后端 SIGKILL 后无残留；TG 权限与文本；shutdown ≤5 秒（与 MCP/Services/AI 并存）。

## S8-B：后端——登录 worker 与窗口自动化真实实现

- 依赖：S8-A 集成、S8-0 结论、待决1 的依赖锁定。write_scope 同上；测试员仅 `tests/independent/s8b/`。
- 结果：`vpn/login_worker.py`（协议、`BrowserDriver` 的 Playwright 实现、数据表驱动的选择器与入口 URL、各步骤超时与错误码、深链捕获与 NSWorkspace 交付、取消与回收）；`adapters/window_automation.py`（权限只读检测、窗口矩形、Vision OCR、挑选逻辑、合成点击、限次）；`pyproject.toml`/`uv.lock` 依赖（darwin 标记）；`DELETE /api/vpn/browser-profile`；README S8-B 段。
- 自动验收：假 `BrowserDriver` 脚本化全流程与每个错误码；worker 协议（行上限、取消、忽略 TERM、孙进程）零残留；凭据只经 stdin（argv/env 断言）；深链 scheme 校验与重发上限；挑选逻辑与矩形过滤、点击限次、黑名单（Cancel/Skip/Disconnect 绝不点）的纯函数单测；权限缺失显式报错；无真实 Chrome/Quartz 调用（守卫）。

## S8-C：前端——VPN 卡（agy）

- 依赖：S8-A 契约（先做）、S8-B 契约。write_scope `next/desktop/**`；测试员仅 `tests/independent/s8c-*`。
- 结果：在设置「服务」页顶部（网络信息条下方）加 VPN 卡（独立 `useVpn` 单实例由 Tab 提供给子组件）：连接状态/IP/客户端状态与版本；「连接」「强制重登」「取消」与运行步骤时间线（WS `vpn.run`）；失败错误码文案与脱敏摘要；凭据设置（密码、TOTP 导入 Sheet：粘贴导出文本或选文件在前端读入内存后提交，多匹配选择列表，提交后清空，提示“请自行删除导出文件”）、旧应用导入、手输令牌 Sheet（`vpn.mfa_required`）；设置项（workspace/residency 枚举/email/tunnel_prefix/超时/headless/chrome_path/窗口自动化三档，含权限状态与“会移动鼠标”说明）；“忘记此浏览器”；`window_permission_missing` 引导文案。不得改动 MCP 页，SettingsPage/ServicesTab 等共用文件只做追加式最小改动。
- 自动验收：前端 frozen install/typecheck/lint/test/build/guard:dist/contracts:check；DOM/存储/URL 无凭据与深链；各错误码文案；单实例与卸载释放；无任何明文密码回填。

## S8 集成验收（主控）

- 后端完整 pytest/ruff/contracts；前端 frozen install/typecheck/lint/test/build/guard:dist/contracts:check；Rust 未改则复跑一次；`git diff --check`。
- 主控亲自核对（含 Opus 安全核对）：所有子进程关闭点（resource-lifecycle-audit 逐项）、后端 SIGKILL 零残留（worker+假 Chrome 替身）、argv/env/日志/TG 无凭据与深链、不杀无关同名进程、窗口自动化默认 off 与边界、TOTP 导入不读路径、单运行互斥、依赖锁定与 darwin 标记。
- dev:web 端到端（假 ifconfig/假客户端/假 worker/假 OCR）：状态 → 配置与凭据导入 → 导入 TOTP（含多匹配）→ 连接（档 0、A、B 的替身路径）→ 取消 → 窗口自动化 off 时跳过提示 → 失败码文案 → TG `/vpn` 走一遍；退出后无残留。
- PROGRESS 列 迁移 / 改进 / 有意推迟清单（对照旧 `docs/capabilities/vpn.md`）。

### 真实验收清单（仅用户另行授权后执行；本合同提交不执行）

1. 权限：窗口自动化需“屏幕录制/辅助功能”；授予后页面权限状态与系统实际一致（开发模式下权限归属启动后端的宿主应用，需注意区分）。
2. 状态读取：客户端 Check Point SASE 13.1.0 的 bundle 解析、运行判定、版本；已连接时 IP 正确。
3. 档 A/B：退出客户端（隧道不断）→ `connect` → 重新打开并保持连接；确认只对客户端精确进程动作。
4. 窗口自动化（`connect`）：窗口显示 Connect 时点击成功；缺权限的错误提示；点击只落在客户端窗口内。
5. **档 C 真实登录**（最高风险）：新品牌下 SSO 入口/选择器/`redirectUrl` scheme 是否仍有效；有种子全自动、headless；无种子桌面手输；“Remember this browser” 与 profile 清除；失败分类码。
6. 更新处理（`connect_update`）：更新提示无法按需触发，**可能保持未测**（旧端曾以还原旧版触发）；如要测须用户先备好旧版安装包。
7. 强杀后端：登录中 `kill -9`，`ps` 核对 worker 与 Chrome 无残留。
8. TG：测试 Bot 上 `/vpn status|on`，结果文本无敏感信息。
9. 未测逐项记账。

### 所有权切换步骤（ARCHITECTURE §5；真实执行另行授权）

1. 前置：S8 集成验收通过；新端凭据与 TOTP 已导入（旧条目不动）；窗口自动化权限（如启用）已授予 TOOLBOX（开发模式下为启动它的终端/宿主应用）。
2. 旧应用：不再点“VPN 连接/Ente 种子/VPN 配置”，不在旧端 TG 触发 `/vpn on`（两端不得同时对同一客户端执行连接/登录；无跨进程锁）。
3. 新端：执行真实验收 2→5；确认连接成功。
4. **主 Bot 所有权切换**（S4 已决1）：S6–S8 菜单迁完后按 S4 步骤（导入 Token → 用户删除旧 Keychain 主条目 → 新端启用 → 回退演练）**另行授权**，不属于 S8 验收。
5. 回退：新端停止使用 VPN 功能；旧端凭据未动，直接可用。

## S8 待决（草案；每项给推荐与备选影响）

技术已定（无需拍板）：客户端按 bundle id 解析（旧代码按 “Harmony SASE” 硬编码在 13.1.0 上会失效）；连接真相只认 utun 地址；登录在受监督 worker 内、凭据只经 stdin；深链不进 argv；不 `pkill -f`、不 SIGKILL 客户端；TOTP 标准库计算、导入不读路径；单运行互斥+取消+总预算；窗口自动化在接口后且帧不落盘；不迁移明文密码回填；`tunnel_prefix` 可配置；运行记录不入 SQLite 之外的取舍见待决9；VPN 卡放在服务页顶部。

| 编号 | 需要拍板 | 推荐 | 备选与影响 |
| --- | --- | --- | --- |
| 1 | S8-0 本机核对与新增依赖 | **授权主控做 S8-0（本机只读探测 + Playwright 驱动系统 Chrome 打开本地假页，不访问真实站点、不登录、不点客户端），并授权联网一次 `uv lock` 解析/下载 `playwright`、`pyobjc-framework-Quartz/Vision/Cocoa`（darwin 标记）；运行时不再 `pip install`** | 不授权：只能按旧代码施工，真实验收才发现依赖/可用性问题，且依赖变更需单独授权；或只授权不新增依赖的探测（①②无法做） |
| 2 | 窗口自动化（OCR+合成点击：Connect / 更新三步） | **保留，但默认 `off`，在页面显式选 `connect` 或 `connect_update` 才启用（需先授予屏幕录制/辅助功能）；会移动真实鼠标，页面说明** | A：`connect` 为默认开启（省一步，但缺权限时每次运行都报错）；B：整体删除（无 pyobjc/TCC 权限，更新弹窗/未点 Connect 时自愈在档 C 前卡住，只能提示你手动处理）；C：只做 Connect、不做自动更新（更新提示出现时报 `needs_user_action`） |
| 3 | 浏览器自动化实现 | **Playwright（锁定版本）驱动系统 Chrome，放在受监督 worker 子进程里** | 直接用已有 `websockets` 手写 CDP：不增依赖，但要自写步骤驱动，且无真实登录无法验证，风险高于沿用已验证手法 |
| 4 | 档 B “重启客户端”是否允许强退 | **只做 AppleScript 优雅退出；超时后对身份核对过的精确 PID 发一次 TERM；仍在则报 `client_stuck`，不 SIGKILL、不按名杀** | A：永不强退（卡死时直接报错，最安全但更常需要人工）；B：沿用旧端 `pkill -f` + 可 SIGKILL（会误杀同名进程，不推荐） |
| 5 | TOTP 种子导入方式 | **接口收“导出文本/单条 otpauth URI”（前端读文件后提交，服务端不读路径、不删文件）；多匹配须明确选择；你自己删除导出文件** | 沿用旧端“给路径→服务端读→无论成败删除”：省一步，但服务端可读/删任意路径文件，且多匹配静默取第一条 |
| 6 | 无种子时是否支持桌面手输令牌 | **支持**（WS `vpn.mfa_required` + 桌面 Sheet 120 秒内输入；TG 不支持） | 不支持：无种子则拒绝登录（更简单，旧端 TG/UI 路径本就要求种子） |
| 7 | Chrome 持久 profile | **新端用全新 profile（首次多输一次 MFA，勾“记住此浏览器”后恢复），并提供“忘记此浏览器”；不复制旧端 profile** | 一次性复制旧 profile（免首次 MFA，但复制含 SSO cookie 的目录并读旧数据，且 Chrome profile 跨路径迁移不一定可用） |
| 8 | 是否做自动看门狗（掉线自动重连） | **不做**，仅手动/TG 触发（与旧端一致；自动重复登录有账号风控/锁定风险） | 做成默认关闭的可选项：周期探测、掉线后按退避自动跑阶梯、每小时最多 3 次，失败通知；需要额外验收与风控评估 |
| 9 | 运行记录持久化 | **内存最近 20 条**（重启后丢失，连接真相每次重读） | 写 SQLite（可审计历史，但要加库、迁移与保留策略；运行中重启需 `unknown` 状态） |
| 10 | 切换时机与旧应用 | **S8 验收通过后按步骤另行授权；不改旧应用代码**（两端不得同时连接，靠步骤约束）；**主 Bot 切换在 S8 验收后另行授权**（S4 已决1） | 在旧应用热修：新端接管时禁用旧 VPN 卡/`/vpn`（更防误操作，但要改旧应用并验证；旧端当前在 13.1.0 上窗口自愈已失效，可顺带评估是否热修名称硬编码——属旧应用改动，需你单独决定） |

## S8 已决

- 用户 2026-10-26 原答复：**“S8 待决 1–10 全部按推荐，写入 S8 已决并提交，然后做 S8-0。”** 确认十项：1 授权主控做 S8-0（本机只读探测 + Playwright 驱动系统 Chrome 打开本地假页，不访问真实站点、不登录、不点客户端）并授权联网一次 `uv lock` 解析/下载 `playwright`、`pyobjc-framework-Quartz/Vision/Cocoa`（darwin 标记），运行时不再 `pip install`；2 窗口自动化保留，默认 `off`，页面显式选 `connect`/`connect_update` 才启用（需先授予屏幕录制/辅助功能，会移动真实鼠标，页面说明）；3 Playwright（锁定版本）驱动系统 Chrome，放在受监督 worker 子进程里；4 档 B 只做 AppleScript 优雅退出，超时后对身份核对过的精确 PID 发一次 TERM，仍在则报 `client_stuck`，不 SIGKILL、不按名杀；5 TOTP 导入接口收导出文本/单条 otpauth URI（服务端不读路径、不删文件），多匹配须明确选择；6 无种子时桌面支持手输令牌（TG 不支持）；7 新端用全新 Chrome profile，提供“忘记此浏览器”，不复制旧端 profile；8 不做自动看门狗，仅手动/TG 触发；9 运行记录内存最近 20 条；10 S8 验收通过后按步骤另行授权切换，不改旧应用代码，主 Bot 切换另行授权。
- 本确认解除派工门禁；**不**授权真实 SSO 登录、点击/退出/重启真实客户端、读取真实配置/凭据/Ente 导出、联网访问任何真实 VPN/SSO 站点、所有权切换、主 Bot 切换、修改旧应用，也不授权真实验收清单（均另行授权）。依赖变更的联网仅限 `uv` 解析/下载上述包。合同中“按待决N”均由以上已决收敛，施工者不得选择备选路径。
- 派工顺序：S8-0（主控）→ S8-A（codex `gpt-6.1-sol` / medium，或 Gemini 4 `gemini-4-argon`）→ S8-B（同会话续接）；S8-C（agy `gemini-3.8-flash-high`，`--sandbox`）在 S8-A 契约冻结后可与 S8-B 并行；最后 S8 集成验收。lead：S8-0 与集成验收的安全核对用 Opus，其余可由 Sonnet 担任。
