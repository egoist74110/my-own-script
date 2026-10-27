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

当前切片：**S9 交付**（合同草案，待用户确认「S9 待决」，见文末「S9」；S8 已于 2026-10-27 集成验收（有条件通过，见 PROGRESS），未归档；S7 已于 2026-10-26 集成验收并归档到 [archive/work-packages/S7.md](archive/work-packages/S7.md)）。确认前不派工。

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

### S8-0 结论（2026-10-26，主控 Sonnet 5.5 实测；**优先于上文与下文一切冲突处**）

方法：scratchpad 独立 venv（仓库 `pyproject.toml`/`uv.lock` 未改）；Playwright 驱动系统 Chrome 打开回环假页（`127.0.0.1` 随机端口）+ 假 scheme `s8probe://`；`ps -axo pid,ppid,pgid` 按 PID 树（记录的 Chrome 主 PID 及后代）核对，不按名字/路径 grep；未访问真实站点、未登录、未碰真实客户端（Check Point SASE 全程保持已连接）、未用任何真实 scheme。

1. **依赖解析**（联网仅 `uv lock/sync`）：CPython 3.14.8；`playwright==1.64.1`（greenlet 3.5.6、pyee 14.0.0、typing-extensions 4.16.0）；`pyobjc-framework-Quartz/Vision/Cocoa==12.2.2`（带入 pyobjc-core 12.2.2、pyobjc-framework-coreml 12.2.2）；全部 `sys_platform=='darwin'` 标记可解析。**需补 `pyobjc-framework-ApplicationServices==12.2.2`**（`AXIsProcessTrusted` 在其中；带入 coretext 12.2.2，共 12 包）——S8-B 依赖清单 = playwright + 上述 4 个 pyobjc 子包，均锁 `==`，darwin 标记；已实测 `import ApplicationServices` 与 `AXIsProcessTrusted()` 可用。不引入 pyotp。
2. **权限只读探测**：`CGPreflightScreenCaptureAccess()=False`、`AXIsProcessTrusted()=False`（宿主=当前 Claude 会话进程树）。**权限归属启动 Python 的宿主应用**：开发模式归启动后端的终端/Claude 桌面应用，打包后归 TOOLBOX；权限状态接口必须在后端进程内探测，页面须提示“授权对象是启动后端的那个应用，授权后需重启后端”。
3. **客户端窗口**：`CGWindowListCopyWindowInfo` 全量列表可见 owner name = **`Check Point SASE`**（两个 layer 0 窗口 280×533 与 166×56，当前 `kCGWindowIsOnscreen` 为空）；`OptionOnScreenOnly` 下无匹配。**不含旧名 “Harmony SASE”，旧筛选已失效**。S8-B 窗口筛选**按 owner PID（由 `ClientController` 以 bundle id 解析出的主进程）匹配**，owner name 仅作辅助与日志；窗口为空/不在屏上时返回明确状态而非静默。`NSWorkspace.openURLs_withApplicationAtURL_configuration_completionHandler_` API 存在（未调用）。
4. **Chrome/Playwright 手法**（系统 Chrome 155.0.8059.40，`channel="chrome"`，launch_persistent_context）：**headless 与 headed 均通过**——每个临时 profile 连续两轮启动成功；CDP `Page.frameRequestedNavigation` 与 `Page.frameScheduledNavigation` 均捕获到页面脚本跳转的 `s8probe://cb#id_token=…`（reason=scriptInitiated，页面写 `S8Probe://` 而 scheme 比较大小写不敏感成功；**两个事件各触发一次，同一 URL 共 2 条，捕获端须去重/只取首条**）；第 2 轮 cookie 保留（persistent profile 有效）；`navigator.webdriver=false`（带 `--disable-blink-features=AutomationControlled`）。版本要求：Playwright 1.64.1 内置参照 Chromium 156.0.8078.4，用 `channel="chrome"` 驱动系统 Chrome 155 无需下载浏览器且可用（不强制同版本，但随 Chrome 大版本升级可能漂移，真实验收记录版本）；`chrome_path` 校验保留。
5. **首次启动联网（观察）**：Playwright 自身与启动不联网取包（系统 Chrome）；**但全新 profile 的 Chrome 即使只开 `about:blank` 也会自行外联 Google（`:443` 多条、`:80` 一条，Chrome 后台服务如组件更新/Safe Browsing/variations）**，且当前机器出口经 VPN 隧道。这不是我们访问的“站点”，但**合同修订：worker 启动 Chrome 附加 `--disable-background-networking --disable-component-update --disable-sync --no-first-run --no-default-browser-check --disable-default-apps`（真实验收时核对是否减少外联；不影响登录页自身访问）**，并在页面/文档如实说明。
6. **进程树与回收**（headed/headless 相同）：Playwright 的 Python 进程 → node `run-driver`（与 worker **同进程组**）→ Chrome 主进程（**自成进程组/会话，pgid≠worker pgid**）→ GPU/Renderer 等 helper（与 Chrome 主进程同组）。对 worker 进程组 `killpg` **不会直接覆盖 Chrome**。实测回收（fork+setpgid+exec 复现 `proc_supervisor` 的子进程组语义；用记录的精确 PID 集核对，每轮后零残留）：
   - 仅 `SIGKILL` worker：Chrome 全部回收（≤3 秒）；
   - `killpg` TERM → 3 秒 → KILL（与 supervisor 控制管道 EOF 路径一致）：全部回收；
   - 直接 `killpg SIGKILL`（无 TERM 宽限，node driver 也被强杀）：Chrome 仍全部回收；
   - headless 与 headed 结果一致。
   机理（推断，行为已实测）：Playwright 以 `--remote-debugging-pipe` 与 node driver 通信，driver/worker 死亡导致管道 EOF，Chrome 随之自行退出；**并非靠进程组**。因此**不依赖按名字 pkill**，也未发现需要额外 reaper 的泄漏；但这是 Chrome 行为而非合同保证，S8-B 须保留**纵深兜底**：worker 在 Chrome 起来后经 stdout 事件 `chrome_started {pid, lstart}`（`ps -o lstart` 身份）上报；`VpnService` 在运行收尾与**后端启动清扫**时，对记录的精确 PID 核对 `lstart` 与命令行含本数据目录 profile 路径后，才对该 PID 所在进程组 TERM（→3 秒→KILL，仅限我们记录且身份核对过的 PID/组），绝不 `pkill`/按名杀。S8-A 假 worker 测试须包含“派生自建进程组的孙进程”用例并断言兜底路径回收它。
7. **探测环境清理**：全部由本任务启动的 Chrome/worker 均按记录 PID 回收；`ps` 复核无残留；临时 profile 留在 scratchpad。

**对 S8-A/B 合同的修订**：① S8-B 依赖增加 `pyobjc-framework-ApplicationServices==12.2.2`（见 1）；② 窗口筛选改按 owner PID，不按名称；③ 回调捕获去重（见 4）；④ Chrome 附加禁后台联网参数（见 5）；⑤ 回收：`chrome_started` 事件 + 精确 PID/lstart/profile 身份核对的兜底清扫，纵深而非依赖进程组（见 6）；⑥ 权限状态页文案按“宿主应用”表述（见 2）。其余沿用「S8 已决」。

**是否可以派 S8-A：可以。** S8-A 不依赖本节的浏览器/窗口实测（只经接缝 + 假实现），S8-0 无阻塞项；S8-B 在 S8-A 集成后按上述修订施工。仍**未**验证（留给真实验收）：新品牌 SSO 页面/选择器/`redirectUrl` scheme、真实窗口 OCR 文案、屏幕录制/辅助功能授予后的实际行为。派工前仍须先问用户。

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

# S9：交付（合同草案，2026-10-27，待用户确认「S9 待决」）

状态：**草案，未确认，不派工**。输入基线：`rewrite/next @ 3cae809`（S0–S8 已集成），旧版 `main @ 885d186`（只读）。本轮只读：旧 `BUILD_MAC_APP.md`、`pack_mac_app.sh`、`pack_mac_dmg.sh`、`release_github.sh`、`app_ado/release_updater.py`；已装旧 `.app` 的 `codesign -dv`/`spctl -a`；本机 `security find-identity`、`notarytool` 版本；新端 `tauri.conf.json`、`Cargo.toml`、`backend.rs`、`pyproject.toml`、`next/spikes/packaging/`（S0-D spike）、后端对外部可执行文件的依赖。**未**读任何凭据/Keychain 内容，未联网，未构建、未签名、未公证、未发布、未改旧应用。
依据：ARCHITECTURE §5/§7/§8、MIGRATION_PLAN S9 行（D14、D16）、S0-D spike 结论、各切片的所有权切换步骤（S4/S6/S7/S8）。

## S9 事实核实

### 旧端交付现状（决定“要替换什么”）
- 旧 `.app` 是**轻量包装**：`Contents/MacOS/launcher` 去调仓库 `.venv` 的 Python，**不自包含**，换机器或移动仓库即失效（`BUILD_MAC_APP.md`）。
- **完全未签名**：`codesign -dv` 为 “not signed at all”，`spctl` 为 rejected（本机已装 1.1.3 (42)，靠用户手动放行运行）。
- DMG 由 `hdiutil create -format UDZO` 简单打包，无背景、无公证；发布走 `release_github.sh`（`gh release create/upload`，tag `v<版本>`，版本来自 `app_version.py`，pre-commit hook 每次提交自动递增，发布脚本会提交并 `git push` 版本号）。
- 更新器 `app_ado/release_updater.py`（67 行）：调 GitHub API 取最新 Release 的 `.dmg` 资源链接，**只打开浏览器下载页**，不校验签名/摘要、不替换应用。D16 即指此类旧更新器/空占位。

### 新端现状
- Tauri 2 壳：`productName=TOOLBOX`，`identifier=dev.toolbox.next`（占位，ARCHITECTURE §8 “新应用名称与 bundle id”**未决**），`version=0.0.0`（Cargo/package.json/tauri.conf 各自 0.0.0；后端 `pyproject` 0.1.0），`bundle.targets=["app"]`，无签名/updater/外部资源配置。
- `backend.rs`：开发默认拉 `<repo>/next/backend/.venv/bin/python -m toolbox_backend --dev`（cwd `next/backend`），`TOOLBOX_BACKEND_CMD` 可整体覆盖；**尚无“打包态”命令解析**（`.app/Contents/Resources` 内的运行时）。握手/监督/回收契约已定且测试覆盖，打包不应改它。
- S0-D spike（Apple M4，CPython 3.14.8，PyInstaller 6.22.3）：方案 A python-build-standalone（含 pyc）解压 61.7 MB、zip 22.7 MB，热启动到 READY 约 0.27 s，新副本首跑 0.83 s；方案 B PyInstaller 31.2 MB、zip 17.0 MB，0.33 s / 1.05 s；两者可重定位、无非系统动态库、退出码 0 无残留。热启动差异不显著，zip 体积差约 6 MB；spike 倾向 A（可维护、同一解释器可复用）。**未测**：签名/公证（A 里每个 `.so`/可执行逐个签名）、Gatekeeper 首启开销、运行时接入 tauri bundle。
- 后端对外部程序的依赖（**不在内置范围，按现状探测**）：`git`、`ifconfig`、`ps`/`open`/`osascript`（系统自带）；`code-server`、`cloudflared`（用户自装，设置页探测/手填路径）；MCP 用的 Node/npm（后端从旧配置目录 `node/` 与 PATH 探测，`resources/mcp/*.js` 是随包补丁）；AI CLI（claude/codex/agy，用户自装）。因此“自包含”只指 **Python 运行时与后端依赖**，不含这些外部工具。
- 本机无可用签名身份：`security find-identity -v -p codesigning` → **0 valid identities**；`xcrun notarytool` 存在（1.1.3）。签名/公证所需的 Apple Developer ID 证书与公证凭据**用户是否拥有未知**，我不读取、不索取、不输入任何凭据。
- 新增事实（S8-0）：屏幕录制/辅助功能的授权**属于启动后端的宿主 `.app` 的签名身份**。打包后若只是 ad-hoc 签名，每次更新 cdhash 变化会使 TCC 授权失效（窗口自动化需重新授权）；稳定的 Developer ID 签名则授权可跨更新保留。这是“是否签名”不只是 Gatekeeper 问题的原因。

### 旧应用下线前提
旧应用下线 = 各所有权切换均已完成并验收：S4（主 Bot/三个 AI 机器人）、S6（Lark 刷新所有权，**用户已搁置**）、S7（code-server/cloudflared）、S8（VPN）。任一未切换，旧应用就仍是该能力的所有者，不能下线。

## S9 数据模型与访问边界

### 架构五问
1. **所有权**：打包态下后端仍由 Tauri 壳唯一监督（契约不变）；运行时在 `.app/Contents/Resources/backend/` 只读，数据与日志在用户数据目录，**绝不写入 `.app` 内**（签名后只读，pyc 必须随包预编译）。
2. **状态与持久化**：版本号单一来源；更新器只持有“当前版本/待装版本/校验结果”，不持久化凭据；更新中断后旧版必须仍可运行。
3. **失败与回收**：更新失败/中断/校验不通过 → 保留旧版并提示；不得出现新旧两份壳同时监督后端（单实例插件已在）。
4. **访问边界**：更新源只允许一个配置的 HTTPS 源（GitHub Releases）；下载物必须过签名/摘要校验才可安装；更新不接受页面传入的 URL。
5. **可观测与取消**：更新检查/下载/安装为一个带取消的运行；日志不含 token、不含完整下载预签名 URL。

### 打包布局（推荐方案 A，定案以待决3 为准）
```text
TOOLBOX.app/Contents/
  MacOS/toolbox-desktop            Tauri 壳
  Resources/backend/               python-build-standalone 运行时 + 锁定依赖 wheel + 后端包（含预编译 pyc，裁剪清单沿用 spike）
  Resources/mcp/                   figma/lark 补丁脚本与 package.json（现 `resources/mcp`）
```
- 打包态命令：`Resources/backend/bin/python3.14 -m toolbox_backend`（无 `--dev`），壳在“打包态”按 bundle 路径解析，`TOOLBOX_BACKEND_CMD` 仍可覆盖（仅调试）；开发态行为不变。
- 构建脚本由 spike 正式化为 `next/scripts/build_app.sh`（锁定依赖、裁剪、预编译、复制进 bundle）；**不得 `pip install` 联网到运行时**，依赖由 `uv.lock` 导出并可重复构建。
- 签名：先签运行时内全部 `.so`/可执行，再签 `bin/python3.14`，再签壳，最后签 `.app`（hardened runtime + 必要 entitlements：JIT/library validation 取最小集，实测后定）；公证用 `notarytool submit --wait` 并 `stapler staple`。**无证书时只产出未签名/ad-hoc 构建用于本机验证，明确标注不可分发。**
- 更新：推荐 Tauri updater 插件 + GitHub Releases 的静态清单（`latest.json`），更新包用 Tauri 自己的更新签名密钥（与 Apple 证书无关，私钥由用户保管，不入库）。

## S9 通用合同与模型分工

- **派工门禁**：用户确认本合同与「S9 待决」；主控写入「S9 已决」并提交输入 SHA。
- 模型分工（用户偏好）：**后端/脚本/Rust 施工 codex exec `gpt-6.1-sol` / medium（workspace-write、不联网）**或 Gemini 4（仅后端）；**前端更新提示 UI 用 agy `gemini-3.8-flash-high`**、`--sandbox`、`--print=`；lead 用 Sonnet；签名/公证/安全验收用 Opus；不做交叉审计；每包至多一个测试员。额度不足换下一候选；实际型号运行前核验，不可验证记 unknown。
- 每包 worktree `.local/worktrees/s9{a,b,c}`，detached 自输入 SHA；施工者不 commit；主控核对 diff 与沙箱外测试后以限定路径 binary patch 集成。
- 禁止：联网（构建依赖用已锁定缓存/离线）、读 Keychain/证书私钥、真实签名/公证/发布/`gh release`/`git push`、改旧应用、读真实配置。真实签名/公证/发布属真实验收，另行授权。

### S9-A：Rust 壳——打包态后端解析与 bundle 配置（codex）
- `backend.rs` 增加“打包态”命令解析（按可执行文件相对路径定位 `Resources/backend`；不存在则回退开发态；覆盖变量保留），单测覆盖路径解析与回退，握手/监督/回收契约与既有测试不变。
- `tauri.conf.json`：`bundle.resources` 引入运行时与 `mcp/`、`minimumSystemVersion`、版本号单一来源（见待决 11）、`identifier`/`productName` 按待决 2。
- 不含签名与更新。

### S9-B：构建与签名脚本（codex）
- 把 spike 正式化为可重复构建：运行时构建（锁定依赖、裁剪、预编译）、拷入 bundle、`verify_app.sh`（检查 bundle 布局、无绝对路径泄露、可重定位、启动握手 + 退出无残留、`codesign --verify --deep --strict` 在有签名时执行）。
- 签名/公证脚本**只读取环境变量或钥匙串中已存在的 profile 名**，不接触凭据值；无证书时脚本明确退出并说明；提供 ad-hoc 本机验证模式（标注不可分发）。
- DMG/zip 产物脚本（`hdiutil`/`ditto`），版本号写入文件名；不含发布。

### S9-C：更新机制（codex 壳/后端 + agy 前端）
- Tauri updater 插件集成与最小权限 capability；更新源固定配置；检查/下载/安装为带取消的运行，事件进 WS（沿用 events.schema 规范）；失败保留旧版。
- 前端：设置页“关于/更新”卡（当前版本、检查更新、下载进度、取消、失败文案、重启安装；无页面传入 URL）。
- 本包只在**本地假更新源**（回环静态服务器 + 自签更新包）下验证，不连真实 GitHub。

## S9 集成验收（主控）

- 后端/前端/Rust 全量检查与 S8 同级（含 `cargo test`、`cargo clippy -D warnings`）；构建产物检查：`verify_app.sh` 全过。
- 主控亲自核对（含 Opus 核对）：`.app` 内无可写数据路径、签名顺序与 entitlements 最小、更新校验失败路径保留旧版、无凭据进 argv/日志/产物、构建可重复（两次产物布局一致）。
- 本机验证（不签名/ad-hoc）：从临时目录拷贝运行 `.app` → 握手 → 退出无残留；隔离后端移动到另一路径仍可启动（可重定位）；本地假更新源走通检查→下载→校验失败/成功两条路径。
- PROGRESS 列 迁移 / 改进 / 有意推迟（含 D14、D16 对照）。

### 真实验收清单（仅用户另行授权；本合同提交不执行）
1. 用你提供的 Developer ID 签名 + 公证（上传 Apple，联网）；`spctl -a -vv` 通过；加 quarantine 属性后首启 Gatekeeper 通过。
2. 真实 `/Applications` 位置首启、关窗常驻、托盘、⌘Q 退出回收；屏幕录制/辅助功能授权在一次更新后是否保留。
3. 真实 GitHub Release 发布与客户端更新一次（需授权 `gh`/push，且用测试 tag）。
4. 旧应用与新应用并存、按各切片所有权切换步骤逐项切换后，旧应用下线（修改旧应用/删除旧 `.app` 均另行授权）。

## S9 待决（草案；每项给推荐与备选影响）

技术已定（无需拍板）：运行时只读放在 `Contents/Resources`，数据目录不进 bundle；打包态由壳唯一监督后端；构建不联网、依赖由 `uv.lock` 锁定；更新必须校验，失败保留旧版；真实签名/公证/发布不在本合同自动执行。

| 编号 | 需要拍板 | 推荐 | 备选与影响 |
| --- | --- | --- | --- |
| 1 | 是否用 Apple Developer ID 签名 + 公证 | **是**（稳定签名身份才能让屏幕录制/辅助功能授权跨更新保留，也避免每次手动放行）；证书与公证凭据由你自己配置在钥匙串，我只用 profile 名 | A：仅 ad-hoc（零成本，但每次更新授权失效、首启需手动放行，只适合个人自用）；B：先不签名，S9 只交付可签名的流水线，等有证书再签 |
| 2 | 新应用名称与 bundle id | **沿用 `TOOLBOX` / `dev.toolbox.next`？** 请你定最终值——它决定数据目录、TCC 授权身份与 Keychain 命名，发布后更名等于迁移 | 先沿用占位、发布前改一次：S9 内可改，已有开发数据需手动迁移；上线后再改代价最大 |
| 3 | 内置 Python 运行时 | **A python-build-standalone**（可维护，依赖即 wheel，zip 比 B 多约 6 MB） | B PyInstaller：体积更小，但隐式导入需维护、新依赖易漏收集 |
| 4 | Node（MCP 用）是否内置 | **不内置**，沿用现有探测并在设置页提示；列为有意推迟 | 内置 Node：真正自包含，但体积 +~100 MB、要随 Node 安全更新、MCP 补丁需随之核对 |
| 5 | 更新机制 | **Tauri updater + GitHub Releases 静态清单**（带更新签名；私钥你保管、不入库） | A：沿用旧式“检查最新 Release 并打开下载页”（最简单，无自动替换，也不校验）；B：不做应用内更新，手动 DMG |
| 6 | 分发形态与架构 | **DMG（UDZO）+ updater 用 zip；仅 arm64**（本机 Apple Silicon） | 通用二进制（arm64+x86_64）：兼容 Intel Mac，但运行时与签名工作量/体积翻倍，需 Intel 机器验证 |
| 7 | 旧应用下线时机 | **各切片所有权切换全部完成并验收后**另行授权下线（S6 Lark 切换被你搁置，所以下线可能晚于 S9）；S9 不改旧应用 | 先在 S9 就下线旧应用的更新器/占位（D16 清理）：需改旧代码，要你授权；会让旧版用户失去更新提示 |
| 8 | 版本号单一来源 | **以 `tauri.conf.json` 为准，构建脚本同步 Cargo/package.json/pyproject 并校验一致**；不再用 pre-commit 自动递增 | 沿用 hook 递增：每次提交 +1，噪声大且与发布版本不一致 |
| 9 | 开机自启/launchd 无界面常驻 | **S9 不做**（ARCHITECTURE §8 未决项维持未决） | 做登录项：增加 `SMAppService` 授权与退出语义，需单独设计 |
| 10 | 真实签名/公证/发布授权 | **S9 施工与本机验证不做，真实验收清单你另行授权时再逐项做**；全程不 `git push`、不 `gh release` | 授权主控在你在场时一次走完签名→公证→发布测试 tag |
| 11 | 版本起点 | **首个对外版本 `1.0.0`**（旧应用最近 1.1.3 (42)，新版用新版本线，避免被旧更新器误判为“更新”或“降级”） | 延续 `1.x`（如 `1.2.0`）：版本线连续，但新旧并存期旧更新器可能提示新应用 |

## S9 已决

- 用户 2026-10-27 原答复：**“S9 待决 1–11 全部按推荐，写入 S9 已决并提交，然后派 S9-A。”** 确认十一项：1 用 Apple Developer ID 签名 + 公证（证书与公证凭据由用户自己配置在钥匙串，主控只用 profile 名，不接触凭据值）；2 应用名/bundle id **沿用占位 `TOOLBOX` / `dev.toolbox.next`**，发布前可改一次，改名视为数据目录/授权身份迁移，需用户另行确认；3 内置 Python 运行时用 python-build-standalone（方案 A）；4 不内置 Node，沿用探测与设置页提示，列为有意推迟；5 更新用 Tauri updater + GitHub Releases 静态清单（更新签名私钥由用户保管、不入库）；6 DMG（UDZO）+ updater 用 zip，仅 arm64；7 旧应用下线待各切片所有权切换全部完成并验收后另行授权，S9 不改旧应用；8 版本号单一来源为 `tauri.conf.json`，构建脚本同步并校验 Cargo/package.json/pyproject 一致，不再用 pre-commit 自动递增；9 S9 不做开机自启/launchd；10 S9 施工与本机验证不做真实签名/公证/发布，真实验收清单另行授权，全程不 `git push`、不 `gh release`；11 首个对外版本 `1.0.0`。
- 本确认解除派工门禁；**不**授权真实签名、公证（联网上传 Apple）、读取证书/钥匙串私钥、发布/`gh release`/push、修改或下线旧应用、改 bundle id/应用名、联网访问真实更新源。无证书时本机只做未签名/ad-hoc 验证，产物标注不可分发。
- 派工顺序：S9-A（codex `gpt-6.1-sol` / medium，Rust 壳打包态解析）→ S9-B（构建与签名脚本）与 S9-C（更新机制，壳/后端用 codex，前端用 agy `gemini-3.8-flash-high`）在 S9-A 契约冻结后可并行；最后 S9 集成验收（签名/公证/安全核对用 Opus）。
- S9-A 取舍（主控裁决）：版本起点按待决 11 把 `tauri.conf.json` 的 `version` 设为 `1.0.0`；Cargo.toml/package.json/pyproject 版本同步与一致性校验属 S9-B；运行时与 `mcp/` 资源通过**构建时叠加配置 `tauri.bundle.conf.json`**（`tauri build --config`）引入，不写入默认 `tauri.conf.json`，使 `cargo test`/开发态不依赖尚未构建的资源目录；`minimumSystemVersion` 暂不设置，留待 S9-B 实测后定（记为开放项）。
