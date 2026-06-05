# 接入 / 编写 MCP server 规范

> 起因:2026-06-04 排查 Lark MCP "登录后约 2 小时就掉线(错误码 20038)"。根因不是 Lark
> 策略,而是本地把它跑坏了 —— 每个 AI CLI 会话各起一个 lark-mcp 进程、退出不回收,几十个
> 进程共抢同一个**会轮换的 refresh_token**,互相把对方的刷新 token 作废。Figma / ADO 也在
> 泄漏进程(只是用静态凭据,不会互毁)。本文把当时踩的坑固化成规范,新增 MCP 前对照检查。

## 两类致命问题

### 1. 进程泄漏(所有 stdio MCP 都会中招)

**现象**:`ps -axo command | grep mcp` 看到几十上百个常驻进程,最老的好几天前。

**原因**:stdio MCP 是"一个客户端连接一个进程"。Claude / Codex / Gemini 把 MCP 配成
**用户级常驻**后,每开一个会话就 spawn 一个 server 子进程;会话被强杀 / 客户端不回收时,
子进程变孤儿常驻。本项目的 wrapper 早期用 `os.execvp`,叠加 `npx → npm exec → node` 多层,
信号传不到底层 node,孤儿更顽固。

**规范**:任何由本项目托管或 wrap 的 stdio server,必须能在"客户端走了"时自杀。三条信号都要覆盖:

- **stdin EOF**:客户端关掉管道 = 最可靠的"会话结束"信号。纯 Python server 用
  `for line in sys.stdin:` 自然在 EOF 退出即可(见 `app_ado/mcp_ado_work_items_server.py`)。
- **SIGTERM / SIGINT**:客户端正常关闭会发。wrapper 要捕获并连子进程一起回收。
- **孤儿(父进程消失)**:兜底。父进程一死、本进程被 reparent 到 launchd(ppid→1)就自杀。

统一用 `app_lark/proc_supervise.py`:
- wrapper 形态(本来要 `os.execvp` 一个 npx/node):改成 `sys.exit(spawn_supervised(argv))`。
  它 spawn 子进程到**独立进程组**(`start_new_session=True`),装 SIGTERM/SIGINT 处理 + 孤儿
  监视线程,任一触发就 `killpg` 整组回收。stdio 直接继承,无代理层、无额外延迟。
- 纯 Python server 形态:在 `main()` 开头调 `install_orphan_reaper()` 兜底。

> ⚠️ 实现坑(已修):信号处理器 / 监视线程里**绝不能调 `proc.wait()`**。主线程已经阻塞在
> `proc.wait()`,对同一子进程并发/重入 waitpid 会卡死,导致 `os._exit` 都执行不到。处理器/线程
> 只负责**发信号**,`wait` 只在主线程做。

### 2. 共享可变 / 会轮换的凭据(只有 OAuth 类 MCP 中招)

**现象**:Lark 登录后约 2h 必掉,日志反复 `Failed to refreshToken ... 20038`(refresh_token
not found / 已被消费)。

**原因**:Lark `user_access_token` 仅 ~2h,靠 refresh_token 续命,而 **refresh_token 每次刷新
会轮换、旧的立即作废**。多个 lark-mcp 进程共用同一份全局加密 token 存储(`storage.json`),
并发刷新时只有一个赢,其余拿着已消费的旧 token → 20038。**进程一多必坏。**

**规范**:凡是带"会轮换的共享凭据"的 MCP(OAuth + offline_access 之类),**必须收敛成单实例**:

- 用 server 的 **streamable / sse(HTTP)模式**,由本 App 托管**一个**进程持有并刷新 token,
  各 AI CLI 用 **URL** 连同一个(见 `app_lark/mcp_server_manager.py` 的 `start_lark_mcp`)。
  单进程 = 单刷新器,从根上没有并发刷新竞争。
- 反例:stdio 模式天生做不到单实例(一个客户端一个进程),多会话并发时必然重现此问题。
- 静态凭据(Figma PAT / ADO PAT,不会自动轮换)没有互毁问题,多实例只是浪费,可暂用 stdio,
  但仍要按"问题 1"加回收。

## 新增一个 MCP 前的检查清单

- [ ] 凭据是**静态**还是**会自动轮换**?轮换的 → 必须单实例 HTTP;静态的 → stdio 可接受。
- [ ] 凭据**不进进程参数**(`ps` 能看到!)。一律用环境变量 / 配置文件 / header 传;
      Lark 用 `APP_SECRET` env,Figma 用 `FIGMA_API_KEY` env(均已完成,勿回退)。
- [ ] 凭据明文只进**系统钥匙串**(keyring),不落磁盘明文(本项目惯例)。
- [ ] wrapper 用 `spawn_supervised`(不要 `os.execvp`);纯 Python server 调 `install_orphan_reaper`。
- [ ] App 托管的常驻 server:用独立进程组启动,`stop` 时 `killpg`,并注册 `atexit` 在 App 退出时回收。
- [ ] 健康探测别误判:`--oauth` 的 HTTP server,`POST /mcp` 需 Bearer 鉴权会 401;用**不过鉴权**
      的探针(如 `GET /mcp` 返回 405 即"在监听")。
- [ ] 页面要有**有效期/存活检测 + 过期提醒**(见 `app_lark/token_status.py`、`app_figma/token_status.py`),
      别让用户在 AI 调用报错时才发现凭据早废了。
- [ ] 给客户端的接入配置(Claude/Codex/Gemini)生成正确:stdio 用 command+args;HTTP 用 URL
      (Claude `--transport http`;Gemini `httpUrl`;Codex `url`)。

## 排查命令

```bash
# 看各 MCP 进程是否堆积
ps -axo pid,etime,command | grep -iE 'lark-mcp mcp|figma-developer-mcp|mcp_ado_work_items_server' | grep -v grep

# 清理泄漏的僵尸 MCP 进程(会连带杀掉其它 AI CLI 会话起的,确认后再跑)
pkill -f 'lark-mcp mcp'; pkill -f '@larksuiteoapi/lark-mcp'
pkill -f 'figma-developer-mcp'; pkill -f 'mcp_ado_work_items_server'

# Lark 真实 token 状态(解密 storage.json) / 续期失败日志
ls -la ~/Library/Logs/lark-mcp-nodejs/
grep -i '20038\|refreshToken' ~/Library/Logs/lark-mcp-nodejs/*.log | tail
```
