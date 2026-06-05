# MCP 接入 / 编写 —— 提示词规则（可直接贴进别的项目的提示词）

> 这是把一次真实排查（Lark/Figma MCP 反复掉线、20038、进程泄漏、token 进 argv）里
> **当初提示词写漏 / 写错的点**沉淀成的规则集。给 AI 生成或接入 MCP server 时注入这些规则，
> 就不会重蹈覆辙。通用原则 + 具体踩坑，去掉了本仓库路径，照搬即可。

---

## 动手前先分辨：凭据是「静态」还是「会自动轮换」

这一步决定整个架构，先判再写。

- **会自动轮换的凭据**（OAuth + offline_access / refresh_token，如 Lark/飞书 user_access_token）：
  refresh_token 每次刷新会换新值、旧的立即作废。
- **静态凭据**（Personal Access Token / API key，不轮换，如 Figma PAT、ADO PAT）：
  多实例不会互毁，但仍会泄漏进程。

---

## 规则 1 ·「会轮换的凭据」必须收敛成单实例

stdio 是「一个客户端一个进程」，多会话并发时多个进程共用同一份全局 token 存储、各自去刷新，
只有一个赢、其余拿到已消费的旧 refresh_token → 刷新失败（Lark 表现为错误码 **20038**）。
**进程一多必坏。**

- 用 server 的 **streamable / sse（HTTP）模式**，由 App 托管**一个**进程持有并刷新 token，
  各 AI 客户端用 **URL** 连同一个。单进程 = 单刷新器。
- 换成 HTTP 后，要把所有工具里**残留的 stdio 配置全部迁成 URL**，否则残留 stdio 会继续起进程、
  继续抢轮换 token。
- 静态凭据没有互毁问题，多实例只是浪费，可暂用 stdio，但仍要按规则 3 加回收。

## 规则 2 ·「会轮换的凭据」刷新路径必须 single-flight（最隐蔽、最容易漏）

收敛单实例只消了「多进程抢」，**消不掉「单进程内并发抢」**。客户端库若刷新无去重：
令牌过期后第一波**并发**调用各自拿同一个会轮换的 refresh_token 去刷 → 第一个轮换掉、
其余拿旧值 → 失败。表现为「单实例了、平时正常，但闲置一段时间后第一次用又掉、要重登」。

- 刷新路径**必须 single-flight**：同一时刻只放一个刷新在途，并发的其余复用同一个
  in-flight Promise/Future，拿同一结果。
- 库自带这把锁最好；没有就**加上**。不便 fork 时，可用注入式补丁包住刷新方法
  （Node 可 `NODE_OPTIONS=--require <preload>` monkeypatch）。补丁必须「目标方法不存在
  （上游改版）时静默跳过」，绝不能把 server 带挂。
- **别用「定时保活去调一下」代替**：库通常**到期才刷、无提前量**，保活只能缩小竞争窗口、
  消不掉它。
- 兜底：页面检测到刷新失败时给**一键重登**（后台 logout → 重新 OAuth），把多步恢复压成一步。

## 规则 2.1 · `--oauth` 服务端模式：HTTP 鉴权层在刷新逻辑之前（极易被漏）

**背景**：lark-mcp `--oauth` 模式让 server 充当 MCP OAuth 2.0 授权服务器。其 flag 描述写的是
"auto **request user login** when token expires"——设计意图是过期后要求用户重新登录。

**坑**：该模式下有两层鉴权：

1. **HTTP 层**（`requireBearerAuth` 中间件）：请求到达工具处理器前，先检查 Bearer token 是否
   在 store 里且未过期。过期 → 返回 401 + WWW-Authenticate（OAuth challenge）→
   MCP 客户端（Claude Code 等）弹浏览器让用户重新登录。
2. **应用层**（`ensureGetUserAccessToken`）：检测 UAT 过期后用 refresh_token 静默刷新。

**问题**：HTTP 层的 401 拦截发生在应用层之前——`ensureGetUserAccessToken` 里的静默刷新路径
从来不会被执行，用户每 120 分钟就要被迫浏览器重登一次。single-flight 补丁解决的是应用层的
并发问题，无法绕过 HTTP 层的 401 拦截。

**修法（需注入三段补丁，全部在同一个 --require preload 里）**：

- **补丁 A — `verifyAccessToken`（OIDC provider）**：若 token 过期但存有 refreshToken，对
  HTTP 中间件返回伪造的"未过期"时间戳（+120s），让请求通过。authStore 里的真实 expiresAt
  不变，`ensureGetUserAccessToken` 读 `isTokenValid` 仍拿到"真实过期"，正常触发刷新。

- **补丁 B — `authStore.storeToken` / `removeToken`**：刷新后 handler 会调
  `storeToken(newToken)` 再调 `removeToken(oldToken)`。截住 `removeToken`，改为：把
  newToken 的 expiresAt + refreshToken 写进旧条目（`tokens[oldToken]`），建立接替映射
  `_supersededBy: oldToken → newToken`，旧条目不删除。

- **补丁 C — `ensureGetUserAccessToken` 外层 wrapper（supersession 追踪）**：返回
  `{userAccessToken: T0}` 时，沿接替链找到当前有效 token Tn，改为返回
  `{userAccessToken: Tn}`。这样 MCP 客户端缓存的旧 bearer T0 可以永久使用：
  - T0 未过期：中间件放行，wrapper 把 T0 换成 Tn
  - T0 已过期：补丁 A 让中间件放行，补丁 B + C 触发刷新拿到 Tn+1

**最终效果**：用户在 MCP 客户端（Claude Code/Gemini 等）第一次连接时走一次浏览器 OAuth，
此后 token 在服务端自动轮换、透明续期，永不再要求重登（直至 refresh_token 30 天到期）。

**额外守则**：

- 补丁文件里用 `_pendingNewToken` 记录最近写入的 token（TTL 10s），在 `removeToken` 里
  读取新 token 数据。TTL 保护防止跨无关调用的状态污染。
- `_supersededBy` 映射在每次刷新后更新（T0→T1 → T0→T2 → ...），调用链长度上限 20 跳，
  防死循环。
- `saveToStorage()` 在修改 `storageDataCache` 后调用，保持文件与内存一致；文件监视器
  reload 读到相同数据，不产生副作用。

## 规则 3 · 每个 stdio MCP 进程必须能在客户端断开时自杀

否则被强杀 / 不回收时会变孤儿常驻，日积月累几十上百个进程。三条信号都要覆盖：

- **stdin EOF**：客户端关管道是最可靠的「会话结束」信号，纯 server 读到 EOF 自然退出。
- **SIGTERM / SIGINT**：捕获后连子进程一起回收。
- **孤儿兜底**：父进程消失（被 reparent，ppid → 1）就自杀。
- wrapper **不要 `exec` 掉自己**：用监管式 spawn，子进程放独立进程组，触发即 `killpg`
  整棵树（npx → node）一起带走。
- ⚠️ 信号处理器 / 监视线程里**绝不能调 `proc.wait()`**——主线程已阻塞在 wait，重入同一
  子进程的 waitpid 会卡死，回收失效。处理器/线程只发信号，wait 只在主线程做。
- App 托管的常驻 HTTP server：独立进程组启动，`stop` 时 `killpg`，并注册 `atexit`
  在 App 退出时回收。

## 规则 4 · 凭据不进命令行参数

`--api-key=xxx` / `-s <secret>` 会被 `ps` 任何用户看到明文。一律用**环境变量 / 配置文件 /
header** 传；明文只存**系统钥匙串（keyring）**，不落磁盘明文。

## 规则 5 · 健康探测要避开鉴权

`--oauth` 的 HTTP server，需 Bearer 的 `POST` 端点未授权会 401，不能当存活判据；
用**不过鉴权**的探针（如 `GET /mcp` 返回 405 即「在监听」）。

## 规则 6 · 页面要做有效期检测 + 过期提醒，别等调用报错才发现

- 以**真实凭据状态**为准（读 token 真实过期时间 / 刷新失败日志）。
- 在线探活只做「确认有效」的**加分**，**不据歧义响应判失效**——例：Figma `/v1/me` 对只有
  文件读权限的有效 token 也返 403，据此判「失效」是错的。

## 规则 7 · 优先官方 MCP，但看清门槛

- 官方 MCP 通常走登录 / OAuth，无 token、无过期，优先用。
- 第三方 PAT 方案有过期硬限制（如 Figma PAT 最长 90 天，绕不开）。
- 但官方常需付费席位（如 Figma 官方 Dev Mode MCP 需 Dev/Full 席位，只读 / 免费用不了）——
  按用户**实际套餐 / 权限**选，不能默认官方一定能用。

---

## 接入配置（按各客户端格式生成）

- Claude Code：`claude mcp add --transport http <name> <url>`（stdio 用 `claude mcp add <name> -- <cmd> <args>`）
- Codex：`[mcp_servers.<name>]` + `url = "<url>"`（stdio 用 `command` + `args`）
- Gemini CLI：`{"<name>": {"httpUrl": "<url>"}}`
- opencode：`{"type": "remote", "url": "<url>", "enabled": true}`
- 只有 stdio 才用 command + args。

## 新增一个 MCP 前的检查清单

- [ ] 凭据**静态**还是**会轮换**？轮换 → 单实例 HTTP；静态 → stdio 可接受。
- [ ] 轮换凭据：刷新路径是否 **single-flight**（并发只刷一次）？库缺锁就加锁 / 注入补丁。
- [ ] 凭据**不进进程参数**（`ps` 可见），用 env / 文件 / header。
- [ ] 凭据明文只进**系统钥匙串**，不落磁盘明文。
- [ ] stdio：stdin EOF + SIGTERM + 孤儿三信号回收；不要 exec 掉自己；信号处理器不调 wait。
- [ ] 常驻 server：独立进程组 + `killpg` + `atexit` 回收。
- [ ] 健康探测**不过鉴权**。
- [ ] 页面有**有效期检测 + 过期提醒**，刷新失败给**一键重登**。
- [ ] 客户端接入配置按各自格式生成（HTTP 用 URL，stdio 用 command+args）。
- [ ] 换 HTTP 后，**清掉所有残留 stdio 配置**。
