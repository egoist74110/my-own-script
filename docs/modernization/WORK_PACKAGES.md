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

当前切片：**S7 服务管理**（合同草案，待用户确认「S7 待决」，见下文「S7」；S6 已于 2026-10-26 集成验收并归档到 [archive/work-packages/S6.md](archive/work-packages/S6.md)）。确认前不派工。

# S7：服务管理（合同草案，2026-10-26，待用户确认「S7 待决」）

状态：**草案，未确认，不派工**。输入基线：新版 `rewrite/next @ 7dd246b`，旧版 `main @ 885d186`（旧目录有用户未提交改动，均不在服务相关文件内，核对时 `git status` 确认；只读）。本轮未读真实配置/凭据（`~/.config/my-own-script`、`~/.config/code-server`、`~/.dsh`、Keychain 均未读），未启动任何服务、未联网；仅对本机已装的 `cloudflared`、`code-server`、`dsh` 跑了 `--help`（只打印帮助，见「S7-0 已做部分」）。
依据：ARCHITECTURE §2/§4/§5（进程所有权、单例资源切换）、MIGRATION_PLAN S7 行（D03：凭据不进 argv）、README D03、旧 `docs/capabilities/services.md`、S4 已决 1（主 Bot 切换等 S6–S8 菜单迁完）、S5 `adapters/proc_supervisor.py`、S6 McpService 的运行组件/端口预检/状态机/健康/日志脱敏做法。
本合同覆盖：code-server 启停与只读状态、cloudflared 隧道（全局 quick tunnel、自定义 quick tunnel、dsh 命名隧道）、dsh web 启停/复用、dsh Basic Auth 网关（新实现）、网络地址展示（VPN IP 只读、局域网 IP）、桌面「服务」页、TG 主 Bot 的服务菜单、`services` 配置段与两条凭据。**不含**：VPN 连接/自愈/登录（S8；本切片只显示 VPN IP，TG 菜单里的 VPN 项先指向 S8）、主 Bot 所有权切换（S7/S8 验收后另议）、Windows、launchd 常驻、dsh 版本更新按钮（待决8）。

## S7 旧应用事实核实（主控亲自只读核对）

以下位置相对旧目录 `/Users/wesker/my-own-script`；是静态代码事实，不代表真实服务已验证。

### 文件与职责

- `app_ado/services_panel.py`（1503 行）：全部启停/状态/落盘/扫描逻辑（模块级函数，UI 与 TG 共用）；`app_ado/dsh_gateway.py`（370 行）：dsh 的 Basic Auth 反向代理，独立常驻进程；`app_ado/ui/services_tab.py`（493 行）：UI「服务」Tab；`app_ado/tg_control.py:915–1003 _handle_svc_callback`、`:1293–1298`（仅 owner）、`:520–538`（自定义隧道 URL 两步输入 `_cf_url_wait`）；`app_ado/tg_help_inline.py:59–110 services_menu/service_actions_menu`；`app_ado/secrets.py:80–118`（dsh 密钥 `dsh_web_password`、命名隧道 token `dsh_web_tunnel_token`，Keychain 服务 `my-own-script`）；`app_ado/vpn_ip.py`（`ifconfig` 扫 `utun*` 取 `10.254.` 地址，S8 连接逻辑不在此）。
- 状态与日志：`~/.config/my-own-script/services/<name>.json`（pid/启动时间/域名/端口，`write_text` 非原子、异常吞掉 `services_panel.py:73–78`）、同目录 `<name>.log`（`>>` 追加无轮换，`:95–120`）、`cloudflared_pref.json`（协议偏好 http2|quic，默认 http2，`:380–420`）、`cloudflared_custom.json`（自定义隧道 URL→pid，`:535–540`）。

### 启停与监督方式（D03 相关事实）

- **全部服务 detached 常驻**：`_spawn_detached`（`:95–120`）经 `/bin/sh -c "<env>=… nohup <argv> >> log 2>&1 < /dev/null & echo $!"` 拉起（`start_new_session`），sh 退出后服务由 launchd 接管；应用/Bot 退出后服务照常存活，靠状态文件 pid + 端口/进程签名重新找回。这是旧端“关了 bot 服务还在、关不掉”问题的解法，**与新架构 §2“退出=回收应用所属子进程组”相反**（待决2）。
- 状态判定：code-server = `lsof -iTCP:<port> -sTCP:LISTEN`（`:151–160,294–296`）；全局 cloudflared = `pgrep -f "cloudflared tunnel --url http://127.0.0.1:<code-server 端口>"`（`:353–360`）；dsh 本体 = 状态端口/默认 3080/命令行签名 `dsh.* web` + HTTP 探活 `__DSH_BOOT__` 指纹（`:734–850`）；网关/命名隧道/自定义隧道各按签名。
- 关闭：状态文件 pid `killpg` + 扫描补杀（`_kill_pid` `:134–148`：TERM→最多 4 秒→KILL，**KILL 后不等待、不核对进程身份**，pid 可能已被复用）。**`codeserver_stop` 会 kill 监听该端口的任意进程**（`:313–325`，不核对是不是 code-server）；cloudflared 按 `pgrep -f` 的未转义正则 + 前缀匹配（`:353–358,603–625`：`…:5173` 同时匹配 `…:51730`；URL 里的 `.`、`?` 是正则元字符）。
- **同步阻塞**：启动函数在调用线程里轮询 sleep（code-server ≤10 秒，cloudflared 域名 ≤15 秒，dsh ≤30 秒 + 网关 ≤5 秒 + 隧道，`:298–310,424–456,924–1017`）；TG 回调线程、UI 工作线程被占用。UI 每 3 秒轮询 `_refresh_all`（`services_tab.py:31–34`，探测起子进程 `ifconfig/lsof/pgrep`）。

### code-server

- 命令 `code-server`（`_bin` = `which` 或 `/opt/homebrew/bin/`，`:45–46,298–310`），**不传任何参数**：端口/bind/认证全来自它自己的 `~/.config/code-server/config.yaml`（`:32,252–276`，默认 bind `0.0.0.0:8080`）。
- 状态文本**直接显示 config.yaml 里的明文密码**，并给出 `PC(VPN)`、局域网、隧道三个访问地址（`:328–345`）；UI 与 TG 均可见。
- 全局 cloudflared（quick tunnel）固定指向 code-server 端口并把域名写回 state（`:348–470`），即**把 code-server 暴露到公网，仅靠 code-server 自身密码**；协议偏好 http2/quic，运行中切换会重启并换域名（`:403–420`）。

### 自定义隧道（“指定启动”）

- 用户（UI 文本框/TG 两步输入）给任意 `http(s)://` URL，起 `cloudflared tunnel --url <URL> --protocol <p>`（`:507–600`）：**URL 不限回环**（可穿透内网任意主机）、无数量上限、无二次确认；域名从日志里正则取 `*.trycloudflare.com`（`:36,362–376`）。

### dsh 与网关

- dsh 启动：`dsh web --no-open --host 127.0.0.1 --port 3080`；PATH 里没有 `dsh` 时回退 **`npx -y @deepseek-ai/dsh web …`（运行时联网拉包，`:705–732`）**；新起时钉死 `DSH_HOME=~/.dsh`、工作目录=旧仓库根（`:685–702`，让会话落到与主 dsh 相同的 cwd 桶）。优先**复用**已在跑的 dsh（任意端口，`:804–850,924–960`）；`state.pid` 为空 = 复用，停止时只拆网关/隧道、不杀 dsh（`:1020–1060`）。
- **网关**（`dsh_gateway.py`）：监听 `0.0.0.0:3081`（端口钉死：Cloudflare 命名隧道路由指向 `localhost:3081`，`services_panel.py:629–633,889–921`），上游 `127.0.0.1:3080`；**密钥经 `--key` 进 argv**（`:902`、`dsh_gateway.py:352`，旧文档 `services.md` 已承认“同机 ps 可见”）；手写 HTTP 解析的线程服务器（`socketserver.ThreadingTCPServer`，`:340–370`）；认证 = Basic Auth（常量时间比较 `:60–69`）通过后下发 `dsh_auth` cookie（`HMAC(进程随机 secret)`，`HttpOnly; SameSite=Lax`，**无 `Secure`**，`:72–88,285–286`）；WebSocket 升级**只认 cookie**（`:196–206`；注：旧 `services.md` “放行 WS、只对 HTTP 要 key”的描述与代码不符，以代码为准）；转发前**改写 `Host`→`127.0.0.1:3080`、剥掉 `Origin`**（`:112–135`），使 dsh 的 trusted-host 围栏当作回环请求放行——副作用：持 key/cookie 的人可调用 dsh 仅回环开放的特权方法（settings/credentials 等，旧文档已承认）；keep-alive 逐请求循环（`:183–335`）；**无失败限速/锁定**、无最大连接数、请求体仅按 `Content-Length` 读（`Transfer-Encoding: chunked` 的请求体不解析，存在请求边界错位风险）、`_MAX_BODY` 超限后只 `break` 读取（`:52,~255`）。
- `dsh_start`（`:924–1017`）：自动生成 16 位 hex 密钥存 Keychain；**每次启动都杀旧网关重起**；端口被无关进程占 3081 时**漂移**到 3082…（隧道路由随即失配→全 502，`:970–980`）；启动结果文本含明文密钥（`:1014`），`dsh_status` 同样（`:1482`）——经 TG 发送即留在 Telegram 服务器。
- 命名隧道（`:1062–1180`）：token 存 Keychain，**`cloudflared tunnel run --token <token>` 进 argv**（`:1119`），并用同一 token 的 `pgrep -f` 正则识别进程（`:1081–1087`）；所谓“域名”取 token base64 载荷里的 tunnel id 拼 `<id>.cfargotunnel.com`（`:1089–1103`）——这是路由 CNAME 的**目标**，不是用户访问的 `dsh.<域名>`（待 S7-0/用户核对后以可配置 `public_hostname` 替代）。无 token 时回退自定义 quick tunnel 指向网关。
- 换密钥（`:1180–1218`）：≥6 位、写 Keychain、重启网关；更新按钮（`:1392–1447`）：查 npm registry 最新版（HTTP）再 `npm install -g @deepseek-ai/dsh@latest` 或 `npx -y …@latest`，UI 后台线程循环刷新版本缓存（`services_tab.py:37–56`）。
- 局域网 IP：`ifconfig` 取 `en*` 上 192.168/10/172 私有地址，退回“到 8.8.8.8 的默认路由 IP”（`:170–230`）。

### 旧文档与代码的差异 / 已知坑（合同依据）

1. 状态与日志：非原子写、无轮换、pid 复用不核对；2. 按端口/正则杀进程；3. 同步 sleep 轮询占线程；4. 明文密码/密钥进 UI、TG、状态文本；5. 凭据进 argv（网关 `--key`、命名隧道 `--token`）与 `sh -c` 命令串；6. 网关 `0.0.0.0` + 无限速 + 手写 HTTP 解析 + Origin 剥离且无 WS Origin 校验；7. 端口漂移致隧道 502；8. 自定义隧道目标不受限、公网暴露无确认；9. `npx -y` 运行时联网与 `npm install -g` 更新；10. dsh 命名隧道进程靠 token 正则识别。以上均在下文逐项处置，处置方式不明确的列入「S7 待决」。

### 新端现状

- 无任何 S7 代码（`grep cloudflared|code-server|dsh` 仅命中 `mcp/runner.py` 的无关字样与 `server.py`）。配置 schema 当前 v4（`domain/settings.py:236`，`mcp` 段）；凭据适配器可只读旧 Keychain `my-own-script`、写 `toolbox-next`（`adapters/credentials.py`）；`adapters/proc_supervisor.py` + `ai_process.py SupervisedProcess` 与 S6 `services/mcp.py` 的“状态机 + 单飞 + 监督器持有进程 + 读任务脱敏写日志 + 端口预检 + 健康探测”可直接作为样板；TG 已有 owner-only 页面分发（`services/telegram_commands.py:449–580` 的 `menu` page）。依赖：httpx（带 h11）、websockets 已在 `pyproject.toml`；无 aiohttp。
- 本机已装 `cloudflared`（`/opt/homebrew/bin`）、`code-server`（`/opt/homebrew/bin`）、`dsh`（nvm node 下，`0.2.0-rc.2`）、node。

## S7-0：协议核对（主控）

### S7-0 已做部分（本机 `--help`，未启动服务、未联网、未读配置，2026-10-26）

- **cloudflared**：`tunnel run` 支持 `--token` **以及环境变量 `TUNNEL_TOKEN`、`--token-file`/`TUNNEL_TOKEN_FILE`** → 命名隧道 token 可不进 argv（采用环境变量，同 S6 凭据注入做法）。
- **code-server**：`--auth [password|none]`、`--bind-addr`、`--config`、`--user-data-dir`；**密码只能经 `$PASSWORD`/`$HASHED_PASSWORD` 或配置文件**（本就不在 argv）。新端因此无需读取、也不返回密码（待决4）。
- **dsh `0.2.0-rc.2`**：`dsh web --help` 打印 `dsh --profile web`，选项 `--host --port --no-open --trusted-host <authority...>`（“/api browser-trust 围栏额外接受的 authority”，可重复）。→ **可能不再需要网关改写 `Host`/剥 `Origin`**（改为 `--trusted-host <隧道域名>` / LAN IP）；需 S7-0 联网外的本地实测核对（见下）。另：启动时会因 profile 插件版本不兼容在 stderr 打印大量跳过提示（日志需限量/脱敏，不影响启动）。

### S7-0 待做（授权后，待决1）

在 scratchpad 临时 `DSH_HOME` 与随机端口**本机**起 `dsh web`（不联网、不登录任何账号）核对：`--trusted-host` 能否让带隧道 Host/Origin 的请求通过围栏、WS 升级是否同理；围栏对 `Sec-Fetch-Site`/`Origin` 的精确规则；指纹 `__DSH_BOOT__` 是否仍在；`dsh web` 与 `dsh --profile web` 是否等价；`DSH_HOME` 隔离是否生效。结论写回本节；若 `--trusted-host` 可用，则网关**不再改写 Host/剥 Origin**（缩小特权面），否则按旧做法并强制 WS Origin 同主机校验。**联网部分**（真实 quick tunnel 日志格式、命名隧道 token 载荷、`cfargotunnel.com` 解析）不属于本切片开发前提，列入真实验收。

## S7 数据模型与访问边界（主控技术裁决；涉及取舍的见「S7 待决」，下文“推荐”按待决推荐写，确认后以「S7 已决」为准）

实现完成须按 backend-architecture-review、backend-security-review、backend-business-safety、data-consistency-review、resource-lifecycle-audit、production-readiness-review 复核。

### 架构五问

1. **产生什么数据**：config schema v5 新增类型化 `services` 段；Keychain `toolbox-next` 新 account `dsh_gateway_key`（kind `dsh_gateway_key`）、`dsh_tunnel_token`（kind `dsh_tunnel_token`）；`<data-dir>/services/logs/{code-server,cloudflared,cloudflared-<id>,dsh,dsh-gateway,dsh-tunnel}.log`（脱敏、5 MiB×2 轮换、0600）。**不新增 SQLite、不写 pid/状态文件**：服务状态在内存，进程由监督器持有，重启后重新探测（外部实例按只读探测，见下）。不导入旧 `services/*.json`（它们是运行时状态而非配置）；`cloudflared_pref.json` 的协议偏好可经“从旧应用导入”只读取一个枚举值。
2. **数据流**：桌面 → S0 Bearer HTTP/WS → `ServicesService`（唯一持有服务进程；经 `proc_supervisor` 起 code-server / cloudflared / dsh / 网关子进程）→ 本机端口。手机/外部 →（LAN 或 Cloudflare 隧道）→ 网关进程（认证）→ `127.0.0.1:<dsh 端口>`。cloudflared 出站到 Cloudflare 发生在第三方进程内；后端自身**无新增 HTTP 外部出站**（仅回环探活：dsh 指纹、网关就绪、code-server 端口连接）。TG（仅 owner）→ 同一 `ServicesService` 方法。
3. **谁能访问**：HTTP/WS 仍为单一本机主体（S0）；凭据只写不读回（例外见待决3 的“显式显示密钥”）。网关面向 LAN/公网：任何持有效 key 或 cookie 的人可使用 dsh（等同拥有该用户的 dsh 权限），是本切片最高风险面，见安全核对表。code-server 的认证由其自身把关，新端不替代也不读取其密码。TG 的服务菜单只对 owner 开放，与桌面同一权限检查。
4. **并发冲突**：每数据目录一个 `ServicesService`（沿用后端 flock）；每个服务一个状态机（`stopped|starting|running|stopping|failed|external`），启停互斥（409 `service_busy`），**状态查询读快照、不等锁、不起子进程**（网络地址由后台任务每 5 秒刷新缓存）；dsh 链路（dsh→网关→隧道）作为一个单飞操作按序编排，任一步失败回滚已起的下游；配置写冲突沿用 revision 409；同一数据目录只有一个后端，故同名服务不会被两个新端实例争抢，与旧应用的冲突靠端口预检暴露（`service_port_in_use`）。
5. **失败/清理**：所有后端启动的子进程（含网关）经 `proc_supervisor`：后端被强杀 → 控制管道 EOF → TERM 进程组 → 3 秒 → KILL，**零残留**（待决2 推荐）；正常路径统一 `ServiceLifecycle` 上下文释放进程/管道/读任务/日志句柄；关闭只对**自己持有的进程组**（pgid + 启动时间身份核对），**绝不按端口/进程名/正则杀进程**；外部实例（非本后端启动）只读展示，停止=“断开”（只拆本后端的网关/隧道）。后端退出：lifespan 中 ServicesService 与 McpService、AISessionService 并行收尾，总预算不变（≤5 秒）。

### config schema v5（`services` 段；v4→v5 只新增，迁移快照/原子写/幂等同 S4/S5/S6 规则）

```
services:
  binaries: {code_server: null, cloudflared: null, dsh: null}   # 用户确认过的绝对路径；null=自动检测（which + /opt/homebrew/bin + nvm 目录，只读用）
  code_server: {start_timeout_s: 30}                            # 端口/bind/auth 只读自其 config.yaml，不写
  cloudflared: {protocol: "http2", max_tunnels: 5}              # http2|quic
  dsh: {port: 3080, gateway_port: 3081, lan_enabled: false,     # 待决5
        project_dir: null, home: null,                          # 新起 dsh 的 cwd / DSH_HOME；project_dir 必填才能新起（不再默认旧仓库根，待决10）
        public_hostname: "", tunnel_enabled: false}             命名隧道的公开主机名（展示/trusted-host 用，非密钥，待决11）
```
- 端口 1024–65535 且 `port != gateway_port`；`gateway_port` 变更时若命名隧道在跑 → 409 `service_busy`（路由钉在该端口）；`public_hostname` 为空或合法主机名（RFC1123，≤253，禁止 scheme/路径/端口）；`project_dir`/`home` 绝对路径、存在、目录、属主为当前用户、非符号链接。`dsh.tunnel_enabled` 仅表示“启动 dsh 链路时一并开隧道”的偏好（待决6），不是运行状态。
- **运行中的自定义隧道不持久化**（随后端退出而停止；常用 URL 不存）。

### 凭据

- `dsh_gateway_key`、`dsh_tunnel_token` 写入 `toolbox-next`；HTTP 只写（PUT/DELETE）与 `generate`（后端随机生成 ≥80 bit，写 Keychain，不回显）；GET 只返回 `configured`。`generate` 后默认**不**重启网关，需 409 提示“网关运行中，重启后生效”或携带 `restart:true`。用户自设密钥 ≥16 字符（旧端 6 位）。旧 Keychain 条目（`dsh_web_password`、`dsh_web_tunnel_token`）仅经显式“从旧应用导入”读取，旧条目不改不删。
- 子进程注入：网关密钥经**启动 JSON（stdin 管道）**传入、网关进程不继承任何其他凭据；命名隧道 token 经 `TUNNEL_TOKEN` 环境变量（S7-0 已核对支持，且 cloudflared 文档同时提供 `TUNNEL_TOKEN_FILE`；采用环境变量以与 S6 一致，限制如实记录：同用户进程可 `ps eww` 看到）；code-server 的 `PASSWORD` 等由它自己的 config.yaml 提供，我们**不读取不转发**。子进程环境 = S5 过滤后的环境 + PATH 补全（dsh 所在目录 + S6 `mcp/runtime` 检测到的 node 目录 + 系统目录）+ 该服务必需的一个变量（dsh 另有 `DSH_HOME`）。**任何凭据不进 argv，也不经 `sh -c` 命令串**（不再使用 `nohup sh -c` 拉起）。
- 显式显示密钥（待决3）：仅 `POST /api/services/dsh/key/reveal`（非 GET、响应 `Cache-Control: no-store`、不入事件/日志/WS、注册进脱敏器），TG **永不**发送密钥或 token。

### 服务托管（`services/services.py` 的 `ServicesService`；样板同 S6 `McpService`）

- 命令（均不经 shell；绝对路径 + 参数数组）：
  - code-server：`<code-server>`（不加参数，沿用其 config.yaml；**启动前只读解析 `auth` 与 `bind-addr`：`auth: none` 且 bind 非回环 → 拒绝启动 409 `service_unsafe_config`**，防止无认证暴露；读取失败按默认 `0.0.0.0:8080`+需要认证处理，即无法证明安全时只在 `auth` 明确为 `password` 时放行）。就绪=端口可连接（250 ms 轮询，≤`start_timeout_s`，不持状态锁）。预检：目标端口已可连接且不是本后端进程 → 状态 `external`（视为外部实例，不启动、不杀），而不是接管。
  - cloudflared quick tunnel：`<cloudflared> tunnel --url <target> --protocol <http2|quic>`；域名只从该进程 stdout/stderr 行里按严格正则 `^https://[a-z0-9-]+(\.[a-z0-9-]+)*\.trycloudflare\.com$` 取最后一次；超时 15 秒仍无域名 → 状态 `running`、域名“待刷新”（不当失败）。**全局隧道**固定 `http://127.0.0.1:<code-server 端口>`；**自定义隧道**：目标必须是 `http|https` 且主机 ∈ `{localhost, 127.0.0.1, [::1]}`、端口 1–65535、不含 userinfo/路径之外的怪异字符、总数 ≤`max_tunnels`，请求须带 `ack_public:true`（页面二次确认“该地址将可被公网任何人访问，隧道本身无认证”），否则 409 `tunnel_target_forbidden`/422；每条隧道一个独立进程与日志，id=随机 uuid，状态 `stopped|starting|running|failed`。
  - dsh：`<dsh> web --no-open --host 127.0.0.1 --port <port>`（**不再回退 `npx -y`**，待决7；找不到 dsh → 409 `service_binary_missing`）+ `DSH_HOME`，工作目录=`dsh.project_dir`（未配置且无可复用实例 → 409 `dsh_project_dir_unset`）。**复用**：启动前对配置端口与 3080 做 loopback HTTP 探活（GET `/`，超时 2.5 秒、只读前 64 KiB、认 `__DSH_BOOT__` 指纹、不转发响应），命中 → dsh 状态 `external`（不起新进程）；**不再做命令行签名扫描**。就绪=端口可连接且指纹命中，≤30 秒。
  - 网关：`python -m toolbox_backend.services.dsh_gateway`（**独立受监督子进程**（技术已定：面向 LAN/公网的解析器不放进持有凭据的后端进程）；密钥经 stdin 启动 JSON）。监听地址 = 回环，`dsh.lan_enabled=true` 时 `0.0.0.0`（待决5）；**端口固定 `gateway_port`，被占 → 409 `service_port_in_use`，不漂移**；仅在 dsh 链路启动/重启/换密钥时重启，状态查询不触发。
  - 命名隧道：`<cloudflared> tunnel run`（token 经 `TUNNEL_TOKEN`）；需 `dsh_tunnel_token` 已配置，否则 409 `tunnel_token_missing`；**只识别本后端启动的进程**（不再按 token 正则扫描外部实例，列入“有意放弃”）。无 token 时的回退：不自动起 quick tunnel，页面给出“开临时隧道”（待决6）。
- 编排：`dsh/start` = 探活复用或新起 dsh → 起网关 → 按 `tunnel_enabled` 起隧道；失败回滚本次新起的下游；`dsh/stop` = 停隧道 → 停网关 → 仅当 dsh 为本后端启动时停 dsh（外部实例只断开，永不杀）。
- 日志：每个服务一条读任务逐行脱敏（S4 统一脱敏 + 已注册密钥 + `Bearer …`），写 `<data-dir>/services/logs/`；`GET …/logs?tail=` 只返回脱敏尾部（≤64 KiB）；dsh 的“插件不兼容”提示行限量去重。
- 健康：运行中每 30 秒探端口/指纹，连续 3 次失败且进程仍在 → `unhealthy`（不自动重启）；进程退出 → `failed(exited)` 带日志尾。
- 网络信息：`adapters/net_info.py` 只做**固定参数** `ifconfig`（超时 5 秒、输出 ≤1 MiB）解析：`vpn_ip`（`utun*` 上 `10.254.` 段，沿旧规则，仅展示）、`lan_ip`/`on_lan`（`en*` 私有地址；**不再回退到“默认路由 IP”**，避免把 VPN 地址当 LAN 地址展示）；后台每 5 秒刷新缓存。VPN 连接/登录属 S8。

### HTTP / WS 接口（全部在 S0 Host/CORS/Bearer/BodyLimit 之后；错误沿用 S1 detail 结构）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/services` | 全部快照：`code_server`、`cloudflared{global, tunnels[]}`、`dsh{dsh, gateway, tunnel}`（每项 `state/owned/port/url/last_error/log_tail_available`）、`network{vpn_ip, lan_ip, on_lan}`、`binaries{found/version/path 是否已确认}`、`settings`、`credentials{dsh_gateway_key, dsh_tunnel_token: configured}`、`revision` |
| PATCH | `/api/services/settings` | `services.*`（revision 409；运行中改端口/绑定 → 409 `service_busy`） |
| PUT/DELETE | `/api/services/credentials/{dsh_gateway_key\|dsh_tunnel_token}` | 只写；key 另有 `POST …/dsh_gateway_key/generate` |
| POST | `/api/services/credentials/import-legacy` | `{kinds:[…], protocol:bool}` 从旧 Keychain / `cloudflared_pref.json` 只读导入（旧条目不改不删） |
| POST | `/api/services/dsh/key/reveal` | 显式显示（待决3）；非幂等审计字段 `revealed_at` 不含值 |
| POST | `/api/services/{code-server\|cloudflared\|dsh}/{start\|stop}` | `request_id` 幂等；立即返回，进度经 WS；`cloudflared/start` 起全局隧道 |
| POST | `/api/services/cloudflared/tunnels` | `{target_url, ack_public}` 自定义隧道 |
| DELETE | `/api/services/cloudflared/tunnels/{id}` | 只关这一条 |
| POST | `/api/services/dsh/tunnel/{start\|stop}` | 仅隧道（dsh/网关仍在，LAN 直连不受影响） |
| POST | `/api/services/cloudflared/protocol` | `{protocol}`；运行中的隧道需重启才生效，返回 `restart_required:true`（不自动重启、不自动换域名） |
| GET | `/api/services/{name}/logs` | 脱敏日志尾部，`name` 为枚举 |
| WS 主题 | `services` | `services.status`（任一服务/网络状态变化）；回放/水位同 S3 规则 |

新错误码：`service_busy`、`service_port_in_use`、`service_binary_missing`、`service_unsafe_config`、`dsh_project_dir_unset`、`dsh_key_missing`、`tunnel_token_missing`、`tunnel_target_forbidden`、`tunnel_limit`（全部 409/422，文案不含凭据与路径细节）。

### dsh 网关（新实现 `toolbox_backend/services/dsh_gateway.py`；独立进程，纯 asyncio）

- 协议面（行为对齐旧网关已踩过的坑，**不照搬实现**）：HTTP/1.1 keep-alive 逐请求循环（Cloudflare 复用 origin 连接池，一个请求处理完不得卡住连接）；有 `Content-Length` 时按长度转发并留在连接上，无长度（SSE/chunked 响应）泵到 EOF；WS 升级双向管道；认证 = Basic（常量时间）+ `dsh_auth` cookie（`HMAC(进程随机 secret)`，`HttpOnly; SameSite=Lax`，经 HTTPS 隧道到达时加 `Secure`——依据 `X-Forwarded-Proto`/`CF-Visitor`；secret 随进程轮换）；WS 只认 cookie。
- **与旧网关的加固差异**：① 请求解析用 `h11`（经 httpx 已在依赖，施工时显式声明）或同等严格解析：拒绝 `Transfer-Encoding` 与 `Content-Length` 同时出现/重复/非法值、请求体 chunked 要么正确解码要么 411/400、头 ≤64 KiB、体 ≤8 MiB（超限回 413 而不是继续转发）、空闲超时、最大并发连接数 64；② **认证失败限速**：每来源 IP 5 次/分钟后 429 并指数退避（全局另设总速率），不泄露“用户名/密钥哪个错”；③ **WS 握手校验 `Origin` 与 `Host` 同主机**（拒绝跨站页面借 cookie 开 WS）；④ `Host`/`Origin` 处理按 S7-0 结论：`--trusted-host` 可用则**透传**，否则改写 Host 并仅在上述 Origin 校验通过后剥 Origin；⑤ 转发时去掉入站 `Authorization`/`Cookie: dsh_auth` 后再交给上游（上游不需要也不应看到）；⑥ 不记录请求头/体，只记 方法+路径（脱敏 query）+状态码；⑦ 上游连接失败回 502 且不重试风暴；⑧ stdout 就绪行 `[dsh-gateway] listening <host>:<port>`，其余输出受限量。
- 与后端的关系：网关进程不含后端代码路径中的凭据读取能力——只拿到自己的密钥；崩溃只影响 dsh 远程访问，后端据 `exited` 置 `failed`（不自动重启）。

### 安全核对表（施工与验收都按此）

1. 任何子进程 argv、`sh -c` 命令串**不含**密钥/token（静态扫描 + 替身打印 argv/env 断言；不再使用 `nohup sh -c`）。
2. 子进程环境：S5 过滤后只加该服务必需的一个凭据变量；网关不继承 `TUNNEL_TOKEN`；cloudflared 不继承网关密钥。
3. 凭据只写不读回；密钥仅 `key/reveal` 显式返回；日志/事件/WS/错误/日志尾/TG 全部脱敏并扫描假密钥；TG 永不出现密钥、token、code-server 密码。
4. **杀进程纪律**：只对本后端持有的进程组（身份=pgid+启动时间）发信号；不按端口、进程名、`pgrep -f`、`lsof` 结果杀任何进程；外部实例（`external`）停止=仅断开本后端部分；单测断言“占同端口的无关替身进程毫发无损”。
5. 绑定：dsh 本体仅回环；网关默认回环，`lan_enabled` 才 `0.0.0.0`（待决5）；端口固定不漂移，被占 409；code-server `auth:none`+非回环 bind 拒绝启动。
6. 自定义隧道：目标仅回环主机、数量上限、`ack_public`；全局隧道固定指向 code-server；命名隧道需 token 已配置。
7. 网关：见上节加固清单；单测/协议测试覆盖 smuggling 变体、限速、Origin 校验、cookie 属性、超限、慢速连接。
8. 所有进程经监督器，后端 SIGKILL 后零残留（含网关、隧道、孙进程）；状态查询不被启动阻塞、不起子进程；无 `time.sleep` 轮询占线程。
9. 二进制解析：绝对路径、可执行、属主为当前用户或 root 且非 world-writable；不 `npx -y`、不 `npm install -g`、不联网取包（待决7/8）；`binaries.*` 用户确认路径优先。
10. 日志 0600、目录 0700、拒绝符号链接、5 MiB×2 轮换；`project_dir`/`home` 校验见 config 节。
11. 路由全部 Pydantic DTO，契约重新生成；无新增 HTTP 外部出站（仅回环探活）。
12. TG 与桌面走同一应用服务方法；TG 仅 owner；TG 自定义隧道输入沿用同一目标校验并要求二次点击确认。

## S7 通用合同与模型分工

- **派工门禁**：用户确认本合同与「S7 待决」；主控写入「S7 已决」并提交输入 SHA；若待决1 授权，主控先完成 S7-0 并把结论写回本节，再派 S7-B。
- 模型分工（用户偏好）：**后端施工 codex exec `gpt-6.1-sol` / medium（workspace-write、不联网）或 Gemini 4（`gemini-4-argon`，仅限后端）**，两者可互为额度不足时的下一候选；测试 codex `gpt-6-luna` / high 或 Claude Haiku 5.5（每包至多一个，仅写 `tests/independent/s7x/`）；**前端施工 agy `gemini-3.8-flash-high`**、`--sandbox`、`--print=`；lead 用 Sonnet，S7-0 与集成验收的安全核对用 Opus；不做交叉审计。实际型号/档位运行前核验，不可验证记 unknown。
- 每包 worktree `.local/worktrees/s7{a,b,c}`，detached 自输入 SHA；施工者不 commit；主控核对 diff 与沙箱外全量测试后以限定路径 binary patch 集成。
- 测试只用临时数据目录、内存凭据、**替身**：Python 写的假 `code-server`（可配 config.yaml 的 auth/bind、监听随机端口、忽略 TERM、派生孙进程）、假 `cloudflared`（打印 quick tunnel 域名行 / 不打印 / 提前退出 / 读 `TUNNEL_TOKEN` 并回显 argv/env 到临时文件）、假 `dsh`（回环 HTTP 返回 `__DSH_BOOT__` 页、可配置 trusted-host 围栏行为、大量 stderr）、假 `ifconfig`（固定输出）；**禁止调用真实 code-server/cloudflared/dsh/node/npx/npm/ifconfig/lsof**（PATH 只含替身目录，命中即失败）；沿用 conftest keyring/socket 守卫；端口用例用随机端口（网关固定端口用例用配置覆盖为随机端口，不占真实 3080/3081/8080），沙箱拒绝时主控沙箱外跑。
- 禁止：按进程名/端口 kill、裸 git stash、删除/放宽既有测试、仓库内留报告、改旧应用、读真实配置/凭据/`~/.config/code-server`/`~/.dsh`、联网、启动真实服务（S7-0 本机核对与真实验收除外，均需授权）。

## S7-A：后端——config v5、二进制解析、凭据、服务托管核心、code-server、cloudflared、网络信息、HTTP/WS

- write_scope：`next/backend/**`、`next/contracts/**`；测试员仅 `next/backend/tests/independent/s7a/`。
- 结果：v4→v5 迁移；凭据两 kind 与旧 Keychain/`cloudflared_pref` 导入；`adapters/net_info.py`；`services/services.py`（状态机、单飞、`ServiceLifecycle`、读任务脱敏日志、健康、外部实例探测）；code-server 启停（config.yaml 只读解析、`service_unsafe_config`、端口 `external`）；cloudflared 全局/自定义隧道（目标校验、数量上限、域名提取、协议）；`GET /api/services`、settings/credentials/logs/start/stop/tunnels 路由；`services` WS 主题；契约重新生成；lifespan 接入与关闭预算。
- 自动验收：后端 pytest/ruff/contracts exit 0，覆盖：迁移幂等与快照；端口被无关替身占用 → `external` 且停止不杀；`auth:none`+非回环拒绝；启动超时/提前退出/忽略 TERM/孙进程全部零残留；域名提取（有/无/多次/伪造行）；自定义隧道目标校验（非回环、userinfo、`localhost.evil.com`、IPv6、超限、无 ack）；后端 SIGKILL 后全部替身退出；状态查询在启动进行中立即返回且不起子进程；日志脱敏与 argv/env 无假密钥；网络信息解析（有/无 VPN、多网卡、不回退默认路由）；shutdown 预算 ≤5 秒（与 MCP、AI 会话并存）。

## S7-B：后端——dsh、网关、命名隧道、密钥、TG

- 依赖：S7-A 集成、S7-0 结论。write_scope 同上；测试员仅 `tests/independent/s7b/`。
- 结果：dsh 启动/复用探活/`project_dir`/`DSH_HOME`/PATH；新网关进程（见加固清单）；命名隧道（`TUNNEL_TOKEN`）；`dsh/start|stop|tunnel`、`key/generate|reveal`；编排与回滚；TG 服务菜单（见下）；`services` 页所需的 DTO 补全。
- TG（待决9）：主 Bot `menu` 增 `services` 页（owner-only）：服务列表与状态；code-server / dsh 启停、dsh 隧道开关、全局隧道启停与协议显示；自定义隧道经两步输入 + 确认按钮；**状态文本只含 状态/端口/域名/局域网地址，不含密钥、token、code-server 密码**；VPN 项显示“VPN 管理见 S8”。
- 自动验收：网关协议用例（keep-alive 多请求、Content-Length/无长度/SSE、WS 升级与双向流、smuggling 变体 CL.TE/TE.CL/双 CL/非法 TE、超限 413、限速 429 与退避、Origin 同主机校验、cookie 属性与 `Secure` 推导、转发前剥离入站凭据、上游不可达 502、并发上限、慢速连接超时）；网关 argv 无密钥（密钥只在 stdin）；dsh 复用（指纹命中=`external`，停止只断开网关/隧道，替身 dsh 毫发无损）；dsh 新起时 `project_dir` 缺失 409、`npx` 不被调用（PATH 无 npx 也不报错）；命名隧道 token 不在 argv/日志、缺 token 409；编排回滚（网关起不来→不留 dsh、隧道失败→保留 dsh+网关并报错）；`key/reveal` 仅此处返回、TG/WS/日志/错误扫描无密钥；端口 3081 被占 409 不漂移；后端 SIGKILL 零残留（dsh/网关/隧道三层）；TG 菜单权限（非 owner 拒绝）与文本无密钥；shutdown ≤5 秒。

## S7-C：前端——服务页（agy）

- 依赖：S7-A 契约（code-server/cloudflared/网络部分可先做）、S7-B 契约。write_scope `next/desktop/**`；测试员仅 `tests/independent/s7c-*`。
- 结果：新增「服务」页（R1 macOS 原生风格；**不得改动 MCP 页及其组件（S6-ACC-009 的修复由其他会话负责）；路由/导航等共用文件只做追加式最小改动**）：顶部网络信息条（VPN IP、局域网 IP，只读，复制）；code-server 卡（状态/端口/访问地址、启停、外部实例提示“非本应用启动，不会被停止”、不安全配置错误文案）；cloudflared 卡（全局隧道启停、协议选择、自定义隧道列表 + 添加 Sheet（含公网暴露二次确认勾选）、逐条关闭、域名复制）；dsh 卡（dsh/网关/隧道三段状态、启停、隧道开关、LAN 直连开关与风险说明、密钥：生成/设置（提交后清空）/“显示”按钮（二次确认，显示后 30 秒自动隐藏，不入 store/URL/storage）、命名隧道 token 写入/导入、`public_hostname`、`project_dir` 目录选择、从旧应用导入）；运行时二进制状态（找到/缺失/路径确认）；各错误码文案。选项只来自后端枚举。
- 自动验收：前端 frozen install/typecheck/lint/test/build/guard:dist/contracts:check；DOM/存储/URL 无凭据（密钥仅在“显示”态的内存中，定时清除）；各错误码文案。

## S7 集成验收（主控）

- 后端完整 pytest/ruff/contracts；前端 frozen install/typecheck/lint/test/build/guard:dist/contracts:check；Rust 未改则 `cargo test --offline` 复跑一次确认退出不超时；`git diff --check` 与限定路径检查。
- 主控亲自核对（含 Opus 安全核对）：所有子进程关闭点（resource-lifecycle-audit 逐项清单）、后端 SIGKILL 零残留、argv/env/日志/TG 无密钥、网关加固项逐条对照、“绝不按端口/名字杀进程”的代码路径审计、外部实例只断开、端口不漂移、自定义隧道目标校验。
- dev:web 端到端（假 code-server/cloudflared/dsh + 假 ifconfig）：网络信息 → code-server 启停（含端口被占 `external`）→ 全局隧道域名 → 自定义隧道（拒绝非回环、确认后成功、超限）→ dsh 启动（复用替身 / 新起）→ 网关认证流程（无凭据 401、错误 key 429 退避、正确 key 200+cookie、WS 带 cookie 通过、无 cookie 拒绝）→ 命名隧道替身读 `TUNNEL_TOKEN` → 停止 → 退出后 `ps` 无替身残留；TG 服务菜单走一遍（假 Telegram，owner/非 owner）。
- PROGRESS 列 迁移 / 改进 / 有意推迟清单（对照旧 `docs/capabilities/services.md`）。

### 迁移 / 改进 / 有意放弃（草案，随待决确认；放弃项需用户确认）

- 迁移：code-server 启停与访问地址展示；全局 quick tunnel 与协议偏好；自定义隧道；dsh 启停与复用已在跑实例；Basic Auth + cookie 网关与 keep-alive；命名隧道；换密钥；局域网直连；VPN IP 展示；TG 服务菜单。
- 改进：不再按端口/正则杀进程；服务随后端回收且强杀零残留；凭据不进 argv；不显示/不转发 code-server 密码与密钥（TG 永不发送）；网关限速、严格解析、WS Origin 校验；端口不漂移；自定义隧道目标受限；`auth:none` 暴露拒绝；启动不阻塞线程；日志脱敏轮换；二进制路径校验。
- 有意放弃（待确认）：服务脱离应用常驻（待决2）；“按命令行签名发现外部 dsh/cloudflared/命名隧道”；`npx -y` 回退与 dsh 一键更新（待决7/8）；状态文本里明文密码；`_lan_ip` 回退默认路由 IP；网关 6 位弱密钥。

### 真实验收清单（仅用户另行授权后执行；本合同提交不执行）

1. 本机真实 code-server 启停（确认其 config 为 `auth: password`）；端口被另一真实进程占用时只显示 `external` 且停止不影响它。
2. 真实 cloudflared quick tunnel：域名提取、协议切换提示、自定义隧道（仅回环目标）、强杀后端后隧道进程消失。
3. 真实 dsh：复用已在跑的 dsh（会话/模型在）；新起（`project_dir` 落到正确会话桶）；S7-0 的 `--trusted-host` 结论在真实隧道域名下成立；手机经 LAN 直连与经命名隧道各验证：页面 401→登录→侧栏出现工作区（WS 通）、`host.describe` 200；错误密钥限速；网关重启后 cookie 失效。
4. 命名隧道：导入 token、`TUNNEL_TOKEN` 方式能连上；确认 `public_hostname` 与 Cloudflare 路由（`dsh.<域名>` → 网关端口 3081）一致，核对旧端“显示的 `cfargotunnel.com` 域名”是否真的不可直接访问。
5. 所有权切换（见下）与回退演练；TG 服务菜单在测试 Bot 上走一遍；回收：退出应用/强杀后端后 `ps` 核对无 code-server/cloudflared/dsh/网关残留（外部复用的 dsh 除外）。
6. 未测逐项记账。

### 服务所有权切换步骤（ARCHITECTURE §5；真实执行另行授权）

1. 前置：S7 集成验收通过；新端已导入网关密钥与命名隧道 token（旧条目不动）；`binaries`、`project_dir` 已确认。
2. 旧应用：服务 Tab 依次「关闭」dsh（含隧道/网关）、cloudflared、code-server，确认 `3080/3081/8080` 无监听（旧端的 detached 进程不会随旧应用退出而停，**必须在旧应用里点关闭**）；此后不在旧应用启动服务，直到回退。
3. 新端：启动 code-server → 全局隧道（可选）→ dsh 链路；端口预检通过即说明旧端已停（若 409 回到第 2 步）；命名隧道路由仍指向 3081，**Cloudflare 侧无需改动**。
4. 观察：手机经 LAN/隧道访问；退出新应用后确认服务全部停止（与旧端“退出不停”不同，需知会）。
5. 回退：新端停止全部 → 旧应用重新启动服务。密钥与 token 在两端 Keychain 各一份，互不影响。

## S7 待决（草案；每项给推荐与备选影响）

技术已定（无需拍板）：网关为独立受监督进程；所有服务进程经 `proc_supervisor` 持有、绝不按端口/名字杀进程、外部实例只读与断开；凭据不进 argv/`sh -c`；网关独立重写并加固；端口不漂移；自定义隧道目标仅回环；code-server `auth:none`+非回环拒绝启动；不读取不返回 code-server 密码；不新增 SQLite、不写 pid/状态文件；状态查询不阻塞不起子进程；TG 永不发密钥；VPN 连接留给 S8。

| 编号 | 需要拍板 | 推荐 | 备选与影响 |
| --- | --- | --- | --- |
| 1 | S7-0 本机核对授权 | **授权主控在 scratchpad 临时 `DSH_HOME` + 随机端口本机起 `dsh web`（不联网、不登录）核对 `--trusted-host`/围栏/指纹/`dsh web` 等价性** | 不核对：按旧做法（Host 改写 + Origin 剥离）施工，特权面更大，且 dsh 升级后围栏规则变化只能在真实验收时发现 |
| 2 | 服务进程生命周期（旧端 detached 常驻 vs 新架构回收） | **服务随后端回收（退出应用=停止全部；后端被强杀同样零残留）**，符合 ARCHITECTURE §2/§5；关窗只是隐藏，服务继续 | A：每服务可选“应用退出后继续运行”（旧端行为）：保留 detached 常驻，但要自建 pid+启动时间身份文件、重启后接管校验、强杀后会留孤儿，回到旧端“关不掉”类问题；B：仅 code-server 可常驻（dsh/网关/隧道仍回收）。**注**：这改变你现有习惯——退出应用后手机立刻失联 |
| 3 | dsh 网关密钥怎么给你看 | **桌面“显示”按钮（二次确认、30 秒自动隐藏、`POST key/reveal`）+ 随机生成；TG 永不发送；后端不提供 GET 明文** | A：沿用旧端（状态文本直接显示，TG 也发）：最方便但密钥进 Telegram 服务器；B：TG 仅 owner 私聊显示且 60 秒后自动 `deleteMessage`（仍经 Telegram 服务器一瞬）；C：只能复制到剪贴板、永不显示明文 |
| 4 | code-server 密码 | **不读取、不显示、不转发**（它在自己的 config.yaml，你在那里查看/修改；新端只读 `auth`/`bind-addr`/端口） | 沿用旧端显示/复制：需要读 config.yaml 密码字段并返回前端，违反“凭据不回显”；或新端接管密码（`PASSWORD` 环境变量 + Keychain）：要改你现有 code-server 配置与使用习惯 |
| 5 | 网关监听范围（LAN 直连） | **默认只监听回环，设置里“允许局域网直连”显式开启（页面说明 Basic Auth 走明文 HTTP，勿在公共 Wi-Fi 开启）**；公网仍走命名隧道 | A：沿用旧端 `0.0.0.0` 默认开启（手机在家直连开箱即用，但认证在明文 HTTP 上、任何同网设备可试密钥——已加限速）；B：移除 LAN 直连只留隧道（最安全，但 Cloudflare 边缘需可用） |
| 6 | 隧道回退与开关策略 | **无命名隧道 token 时不自动起 quick tunnel**，页面提供显式“开临时隧道”；`dsh.tunnel_enabled` 默认 false（启动链路不自动暴露公网） | 沿用旧端：无 token 自动回退 quick tunnel 并随 dsh 启动自动开隧道（省一步，但公网暴露变成默认行为） |
| 7 | dsh 的 `npx -y` 回退 | **取消**：只用已安装的 `dsh`（可在页面确认路径），找不到则提示先安装 | 保留回退：GUI 环境 PATH 受限时仍能起，但每次可能联网拉包且版本不受控 |
| 8 | dsh 版本检查/一键更新 | **本切片不做更新**，只显示本机 `dsh --version`（一次探测后缓存）；更新由你在终端自行 `npm i -g` | A：保留版本检查（HTTPS 查 npm registry）与“更新”按钮，作为显式 job（联网、`npm install -g` 改全局环境、需确认）；B：只做版本检查不做更新 |
| 9 | TG 主 Bot 服务菜单范围 | **与桌面同能力但不含密钥与密码**：状态、code-server/dsh 启停、dsh 隧道开关、全局隧道启停、自定义隧道（两步输入 + 确认）；VPN 项指向 S8 | A：只做状态查看 + 启停（不含自定义隧道/协议）；B：不提供 TG 服务菜单（只能桌面操作）。注意：S4 已决 1 要求 S6–S8 迁完菜单后才切主 Bot，选 B 会让 S7 的这一项失效 |
| 10 | dsh `project_dir` 默认值 | **必填，不默认旧仓库根**（页面用目录选择；未配置且无可复用 dsh 时拒绝新起并提示）；若你填旧仓库根则会话桶与主 dsh 一致 | 沿用旧默认（旧仓库根）：新端要硬编码一个会在重构完成后失效的路径；或默认用户主目录：会话落到新的空桶（旧端“手机看到空白 dsh”的根因之一） |
| 11 | 命名隧道“域名”展示 | **新增可选 `public_hostname`（如 `dsh.<域名>`）用于展示/复制；未填时不展示 `cfargotunnel.com`** | 沿用旧端从 token 推导 `<id>.cfargotunnel.com`（若其实不可直接访问则误导）；真实验收时核对后再定 |
| 12 | 切换时机与旧应用 | **S7 验收通过后按上面步骤另行授权切换；不改旧应用代码**（旧端 detached 服务不会自动停，须在旧应用里手动关闭；端口预检互斥）；主 Bot 切换仍待 S8 后统一择时 | 在旧应用热修：新端接管时旧端禁用服务按钮（更防误操作，但要改旧应用并验证） |
