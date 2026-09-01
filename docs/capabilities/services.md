# 服务管理（code-server / cloudflared 隧道 / dsh web / VPN 地址）

## 这个能力做什么
「服务」Tab（与 TG 服务面板共享同一套后端）管理本机临时服务：code-server 启停、cloudflared quick tunnel 启停（暴露本地服务）、**dsh web 启停（带密钥登录）**、显示当前 VPN IP。核心解决「关了 bot 服务还在、重启后找不回/关不掉」。

## 关键文件

| 做什么 | 文件 |
| --- | --- |
| 服务后端（启停/状态/落盘/端口与签名扫描） | `app_ado/services_panel.py` |
| dsh 的 Basic Auth 网关（纯标准库，独立常驻） | `app_ado/dsh_gateway.py` |
| UI 服务 Tab | `app_ado/ui/services_tab.py` |
| TG 服务菜单（inline 回调） | `app_ado/tg_control.py`（`_handle_svc_callback`） |
| dsh 密钥存取（钥匙串） | `app_ado/secrets.py`（`get/set/clear_dsh_password`） |
| VPN IP 读取 | `app_ado/vpn_ip.py` |

## 设计要点（都在 `services_panel.py` 注释里）
- 进程 **detached 启动**（`start_new_session`），脱离 bot 独立常驻。
- PID/启动时间/cloudflared 域名落盘 `~/.config/my-own-script/services/<name>.json`，bot 重启能读回。
- 查状态不只信状态文件，还**主动扫端口**（code-server）/**进程签名**（cloudflared），状态文件丢了或手动起的服务也能发现。
- 关闭双兜底：状态文件 PID 杀进程组 + 端口/签名扫描。
- cloudflared 只认 quick tunnel 签名 `cloudflared tunnel --url`，绝不误伤 root 的 `tunnel run --token` 常驻命名隧道。

## dsh web（带密钥）
dsh 的 Web UI 本身**没有密码登录**。为了像 code-server 那样「手机访问先过密钥」，在 dsh 前面加一个 **Basic Auth 网关**（`app_ado/dsh_gateway.py`，纯标准库、独立常驻进程）：
- 监听 `0.0.0.0:3081`（**端口钉死 3081**：Cloudflare 命名隧道路由固定指向 `localhost:3081`，端口漂移 = 路由失配 = 隧道全 502；启动时杀旧网关后**轮询等端口真正释放**再起，只有被无关进程占着才后移），上游指向 dsh 的 `127.0.0.1:3080`（dsh 本体仍只监听回环）。**为什么监听 `0.0.0.0` 而非 `127.0.0.1`**：让**同一内网（家里 Wi-Fi / 同一 VPN）的手机能直连 Mac**——`http://<Mac 内网 IP>:3081`（`_lan_ip()` 优先取 en* 上的 `192.168.x`，其次 `10.x`）。这条路**完全绕开 Cloudflare**，WS 原生工作、不会被 Cloudflare 边缘 403，是手机访问 dsh 的**首选**；访问仍由网关的 Basic Auth key 把关（没 key 连页面都看不到）。
- **认证 = Basic Auth + Cookie（关键，手机可靠的前提）**：dsh web 有两类请求——`/api/events.mux`、`/api/events.host` 是 **WebSocket**（客户端 `doFetch` 对 GET 走 `new WebSocket`，dsh 对非升级请求回 `426 Upgrade Required`），`/api/host.describe`、`/api/workspace.list` 等 unary 是 **fetch POST**。浏览器开 WS **发不了 Authorization 头**，且**手机浏览器常常不把原生日志框的 Basic Auth 缓存到同源 XHR/fetch**（桌面 Chrome 会、手机常不会）——于是 WS 和 unary POST 都可能缺认证 → UI 就绪失败（要求 `host.describe` 成功 + 两条流打开）→ 界面空白。
  解法：网关在**页面那次 Basic Auth 通过时下发一个 cookie（`dsh_auth`）**；之后**同源 WS 握手 + 同源 fetch 都会自动带 cookie**（fetch 默认 `credentials:'same-origin'`、WS 握手带同源 cookie），手机也稳。认证规则：**WS 只认 cookie**（带不了 Authorization）；**HTTP 认 Basic Auth（并下发 cookie）或有效 cookie**；都没有 → `401 + WWW-Authenticate`。cookie token = `HMAC(本进程随机 secret, "dsh-auth")`，**不含 key**、网关重启后旧 cookie 失效（重输一次 key 即可）。Cloudflare 只挡「带 Authorization 头的 WS 升级」，这里 WS 带的是同源 cookie（不是 Authorization 头），正常放行。
- **隧道 = Cloudflare 命名隧道（主用、稳）/ 快速隧道（兜底）**：
  - **命名隧道（主用）**：在 Cloudflare **主控制台** Networking → Tunnels 建（面向公共应用的 tunnel，**免费计划可用、无需绑卡**——注意区别于 Zero Trust 版，那个要绑卡）。token 存钥匙串（`secrets.get_dsh_tunnel_token()`，service=`my-own-script`、key=`dsh_web_tunnel_token`）；「隧道」按钮起 `cloudflared tunnel run --token <token>`（**按完整 token 精确匹配进程**，绝不误伤账号里其它项目的命名隧道；面板外手动起的也能识别）。域名固定（路由 CNAME 如 `dsh.<域名>` → `<tunnel-id>.cfargotunnel.com`，面板从 token 的 base64 JSON 载荷 `t` 字段自动推导），持久稳定，无快速隧道的间歇 502。
  - **快速隧道（兜底）**：钥匙串没 token 时回退，随机 `*.trycloudflare.com` 域名，已知会间歇 502（某次 502 打在 `/plugins/.../client.js` 上 → 前端报 `HTML did not preload ...`，UI 空白）。
  - 手机在外网（蜂窝 / 异网 Wi-Fi）走隧道域名：页面先过密钥（Basic Auth 弹窗），之后 WS + unary 全靠 cookie 过网关——手机一定会带 cookie，所以工作区/会话正常。
  - **同内网直连（手机和 Mac 同网时的替代）**：`http://<Mac 内网 IP>:3081`（`_lan_ip()` 给出），不经 Cloudflare，更直接。
- **网关的两个线协议硬要求（缺一手机就是空白 UI，2026-08 实测踩坑）**：
  1. **必须支持 HTTP keep-alive**：Cloudflare 隧道**复用 origin 连接池**。网关若「一个请求处理完就卡住连接等上游 EOF」（dsh/node 的响应是 keep-alive 的，EOF 永远不来），CF 把后续请求分配到这些卡死的连接上 → **POST 502、WS 升级失败**（症状：页面能打开、插件脚本能拉，但 `host.describe`/WS 全挂，UI 停在 "Loading plugins…" 或空白）。正确做法：响应带 `Content-Length` 时按长度泵完就**留在连接上读下一个请求**（循环处理）；无 `Content-Length`（chunked/SSE 长流）才泵到 EOF 关连接。
  2. **转发前必须改写 Host、剥掉 Origin**（`_rewrite_for_upstream`）：dsh 的 `client-connection` 插件对每个 `/api` 请求和 WS 升级有 **trusted-host 围栏**——`Host` 必须是回环（或 CLI 派生的 LAN IP 字面量，隧道域名不在其中）；`Sec-Fetch-Site: cross-site` 直接拒；带 `Origin` 必须与 `Host` 完全一致。隧道的 `Host: dsh.<域名>` + `Origin: https://dsh.<域名>` 三条全不过 → **403 "forbidden"**（HTTP）/ WS 直接拒。解法：网关把 `Host` 改写成上游 `127.0.0.1:3080`（回环）、`Origin` 整个剥掉（无 Origin 即同源）——网关已用 key/cookie 把过关，从 dsh 视角这就是「回环上的已认证请求」。副作用是**连 loopback-only 的特权方法**（`settings.*`、`credentials.*`、`agentPreset.read` 等）也放行了（Host 已是回环），正好补齐 UI 需要的全部 API。
  - 验证三件套（经隧道、真浏览器）：`/` 200 + Set-Cookie、`POST /api/host.describe`（cookie）200 JSON、`wss://<域名>/api/events.mux` 握手成功（UI 侧栏出现工作区/会话 = WS 通了）。注意：curl 经隧道测 WS 会 403（CF 按 **TLS 指纹**识别 curl，与 UA 无关），必须用真浏览器验证。

密钥只进**钥匙串**（红线）：首次启动 `dsh_start()` 自动生成 16 位 hex 存 `keyring`（`dsh_web_password`），状态里显示、可复制、可换（`dsh_set_password`，换完会重启网关使其生效）。

启停一条链（`dsh_start` / `dsh_stop`）：
- **优先复用**：`_find_running_dsh()` 扫**任意端口**上已在跑的 dsh web，找到就直接挂隧道、**不新起进程**——这样手机连到的就是「你那份」dsh，会话历史/模型/知识全在（会话按工作目录分桶，复用它本身就落在正确的桶里，不会空白）。
  - 识别两道判据：①命令行签名 `dsh.* web`（宽，覆盖 `dsh web` 与 `npx @deepseek-ai/dsh web` 两种拉起，npm/pnpm wrapper 命令行虽含这些词但不监听端口，靠「只保留 LISTEN 的 pid」过滤）；②**HTTP 探活**（`_is_dsh_web_port`，GET 根页面认 `__DSH_BOOT__` 指纹）——与启动方式无关，GUI 拉起 / `dsh web` / npx 拉起都认得出，命令行漏判时兜底。
  - 候选端口优先级：state 记录的端口 > 默认 3080 > 签名命中的监听端口。
- **找不到才新起**：只用两种官方命令（红线，别的都不许）——PATH 里有 `dsh` 就 `dsh web --no-open --host 127.0.0.1 --port 3080`，否则回退 `npx -y @deepseek-ai/dsh web …`。新起时**钉死 `DSH_HOME=~/.dsh` + 工作目录=本仓库根**（`_dsh_node_env_with_home` / `_dsh_project_dir`），让它和主 dsh 共享同一份数据，绝不再出现「全新空 dsh」。node 目录显式补进 PATH。
- 起/换新 Basic Auth 网关（指向上面 dsh 的端口）→ 隧道：钥匙串有 token 走**命名隧道**（`_ensure_dsh_named_tunnel`，固定域名、幂等），没有才回退 `cloudflared_custom_start` 快速隧道。
- 关闭：`cloudflared_custom_stop` 关隧道 → 杀网关 → **只在该 dsh 是面板自己起的**（state.pid 非空）时才杀 dsh 本体；**复用的那份只拆隧道+网关，绝不误杀用户自己的 dsh**。按端口杀时只认 `dsh web` / `dsh_gateway` 进程签名，绝不误伤占同端口的无关进程。
- 状态/端口：`dsh_status()` 显示 运行中/未运行、dsh 端口、网关端口、密钥、隧道域名、局域网地址。
- 端口被占（无关进程）自动后移（3080→3081→… 扫 50 个）再新起。

## 怎么用
- UI：服务 Tab 里对 code-server / cloudflared / dsh 点启动/停止，看 VPN IP。
- dsh 卡片：启动/停止、复制隧道域名、复制密钥、换密钥（网关在跑会重启生效）。
- cloudflared 可切协议（`set_cloudflared_protocol`）；域名从 quick tunnel 日志里解析（`*.trycloudflare.com`）。
- code-server 端口/密码读自 `~/.config/code-server/config.yaml`。
- TG：服务面板里 dsh 与 code-server 一样有「启动/关闭/刷新状态」按钮（`svc:dsh`）。

## 注意坑
- 依赖 `cloudflared` / `code-server` 二进制（`_bin` 优先 `which`，兜底 `/opt/homebrew/bin/`），没装会报找不到；dsh 同理（找不到会报「请先安装 dsh」）。
- dsh 是 node 脚本，nvm/homebrew 的 node 目录不一定在 GUI app 的 PATH 里，`_dsh_node_env()` 会显式补上。
- 杀进程用进程组（`killpg`），避免残留子进程。
- 别把命名隧道（`tunnel run --token`）当 quick tunnel 处理，会误杀 root 常驻服务。
- dsh 的隧道走「指定启动」自定义隧道（按 URL 一条独立），**不碰**全局 code-server 隧道；关 dsh 只关它自己那条。
- 网关密钥经 `--key` 命令行参数传入（不落盘），但同机 `ps` 可见；密钥本身只进钥匙串。
- **DSH 会话按工作目录分桶**（`~/.dsh/sessions/<cwd 编码>/`，如 `--Users-wesker-my-own-script--`）；模型/密钥/知识在 home 全局（`~/.dsh/settings.yaml`、`profiles/`、`storages/`）。所以「手机看到空白 dsh」的根因是面板拉起的 dsh 落在了**另一个 cwd 桶**（或不同 home）——这正是为什么启动要**优先复用**已在跑的 dsh、新起时**钉死 `DSH_HOME` + 工作目录**。
- **别给隧道上的 WS 上认证**（这是「手机 dsh 空白」的第二根因，比 cwd 桶更隐蔽）：dsh web 靠 WS 交换数据，浏览器 WS 带不了 Authorization、Cloudflare 又 403 带认证/cookie 的 WS，两头堵死。网关必须**放行 WS、只对 HTTP 要 key**。验证三件套（经网关、回环到 dsh）：`workspace.list` 返回工作区、`host.describe` 成功、dsh 端口上有 2 条来自网关的 ESTABLISHED（= 两条 WS 连上）。若用 URL 内嵌 `user:key@` 测会假阴性——内嵌凭据不缓存到 XHR，`host.describe`/`workspace.list` 会 401；真实用户走原生日志框才会缓存到所有请求。
