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

# S6：MCP 管理（用户已确认，2026-10-26）

状态：**已确认**（见「S6 已决」）；S6-0 由主控先做，结论写入「S6-0」节后派 S6-A。输入调查基线：新版 `rewrite/next @ 2a92606`，旧版 `main @ 885d186`（旧目录有用户未提交改动，均不在 MCP 相关文件内；只读）。本轮未读真实配置/凭据/CLI 配置（`~/.config/my-own-script`、Keychain、`~/.claude*`、`~/.codex`、`~/.gemini`、`~/Library/Application Support/lark-mcp-nodejs` 均未读），未连真实 ADO/Lark/Figma，未启动旧应用 MCP、node/npx。
依据：ARCHITECTURE §2/§4/§5（Lark 刷新所有权）、MIGRATION_PLAN S6 行与 §4（WP-14→S6）、README D08/D13、WP-14、WP-16、旧 `docs/MCP_SERVER_GUIDELINES.md`、`docs/MCP_PROMPT_RULES.md`、S1 凭据与导入、S2 出站读取与附件同源规则、S4 TelegramService、S5 `adapters/proc_supervisor.py` 与工单 AI 分析。
本合同覆盖：ADO 工单 MCP server（新端实现）、Lark MCP（共享 streamable HTTP 单实例 + OAuth 登录/登出 + 刷新补丁）、Figma MCP（stdio wrapper + 限流补丁）、Node 运行时与 npm 包、各 CLI 接入片段、S5 工单 AI 分析切到新 ADO MCP、Lark 刷新所有权切换步骤。**不含**：`ai_policy` 编辑界面（仍推迟）、主 Bot 所有权切换（S7/S8 前另议）、Windows、launchd 常驻。

## S6 旧应用事实核实（主控亲自只读核对）

以下位置相对旧目录 `/Users/wesker/my-own-script`；是静态代码事实，不代表真实 MCP 已验证。

### 托管方式总览

- `docs/capabilities/mcp-servers.md:4–6,10–25`：MCP配置 Tab 三张卡（`app_ado/ui/mcp_config_tab.py`）；TG 主机器人 `/mcp` 菜单与 UI 共用单例（`:36`）。
- **ADO/Figma 是 stdio：每个 AI CLI 会话各自 spawn 一个 server 进程**（CLI 全局注册见下）；应用“启动”出来的那个 stdio 进程**不服务任何客户端**，实际只是一次握手自检后挂着的空闲进程（两个 manager 的 docstring“UI 与 TG 共用、避免多个 server”名不副实）。只有 Lark 是应用托管、客户端连 URL 的真单实例。
- UI 每 1 秒查运行状态、每 120 秒后台跑一次过期检测（`mcp_config_tab.py:167–183`）；TG 菜单 `mcp:<ado|lark|larkinject|figma>` 切换启停/注入（`app_ado/tg_control.py:1162–1228`）。

### ADO 工单 MCP（`app_ado/mcp_ado_work_items_server.py`、`mcp_server_manager.py`、`ai_work_item_flow.py`）

- server：纯 Python JSON-RPC over stdio，`SERVER_NAME="ado-work-items"`、协议 `2024-11-05`（`:38–40`），initialize 直接回显客户端 protocolVersion（`:783–795`）；`for raw in sys.stdin` 在 EOF 退出 + `install_orphan_reaper()`（`:855–866`）。
- 上下文（`:72–112`）：每次调用读**旧配置** `load_ui_settings()` 与**旧 Keychain** PAT（`get_pat`）；显式 `library_id/library_name/project_id/project_name` 优先，都不传才回落 UI 的 `active_library_id/active_project_id`。
- 8 个工具（`TOOLS` `:627–780`）：`ado_get_work_item`、`ado_get_work_item_comments`、`ado_query_work_items`（**AI 直接给原始 WIQL**，`:233–239`，结果无条数上限）、`ado_list_board_columns`、`ado_list_work_items_by_column`、`ado_get_attachment`、**`ado_create_work_item`（写操作，`:548–622`；缺类型默认“用户情景” `:556–558`；`extra_fields` 任意键值 `:578–583`；支持 `validate_only`）**、`ado_evaluate_change_policy`。
- 附件（`:412–492`）：只比对 netloc（不比 scheme/端口，`:419–425`），下载走 `fetch_attachment_bytes(trusted_base_url=…)`；缓存在**旧仓库目录** `.cache/ado-attachments/<library>/<wi>/`（`:353`），无大小/条数/过期上限，图片原地压缩，结果把本地路径交给 AI 用 Read 读取。
- 策略：`ai_policy.py:17–18` 基线是旧仓库 `config/ai_change_policy.yaml`（该文件有用户未提交改动），`:108–119` 与旧配置 `ai.default_policy`、`ai.project_overrides[<旧 project_id>]` 合并。
- manager（`mcp_server_manager.py`，**D08**）：全局锁内 `Popen(stdin/stdout/stderr=PIPE)`（`:36–43`）后 `readline()` **无截止地等握手**（`:51–58`，锁被一直持有，状态查询同锁 `:24–26` 一起卡住）；stderr PIPE 从不消费；响应只做子串判断（`:66`）；停止只对 pid `terminate`+`wait(5)`，异常时**丢句柄并返回**（`:80–85`）；不建进程组。
- CLI 注册片段（`ai_work_item_flow.py:68–91`）：Claude `claude mcp add ado-work-items --scope user -- <旧 .venv python> <旧脚本>`；Codex `[mcp_servers.adoWorkItems]`；Gemini/agy `ado-work-items`；python 取旧仓库 `.venv`（`:53–58`）。提示词（`:15–43`）写死 `mcp__ado-work-items__*` 且依赖 UI active_*。

### Lark MCP（`app_lark/*`）

- 设置（`store.py`）：旧配置目录 `lark_settings.yaml`（`:45–46`），默认 domain `https://open.larksuite.com`、tools 预设 + 两个读图工具（`:12–23`）、端口 **3000**、host `localhost`（`:24–26`）；回调 `http://localhost:<port>/callback`、客户端 URL `http://localhost:<port>/mcp`（`:84–91`）；登录态 `lark_login_state.json` 只存 app_id/domain/scope/时间（`:49–81`）。App Secret 在旧 Keychain `my-own-script`/`lark_app_secret:<app_id>`（`secrets.py:8–19`）。
- 启动（`mcp_server_manager.py:181–270`）：`npx -y @larksuiteoapi/lark-mcp mcp`（**未锁版本**，`:196`）`-a <app_id> -d -t -m streamable --host localhost -p <port> --oauth --token-mode user_access_token -l zh --debug`，**故意不传 `--scope`**（不传才走 OIDC provider、才发 refresh_token，`:205–213`）；Secret 经 `APP_SECRET` 环境变量（`:235–237`）；`NODE_OPTIONS=--require lark_mcp_singleflight.js`（`:105–118,239`）；输出写 `~/Library/Logs/lark-mcp-nodejs/managed.log`（5 MiB 轮换，`:47–48,243–245`）；`start_new_session=True`（`:254`）；**持锁轮询健康 ≤10 秒**（`:224,261–270`）；健康探针 `GET /mcp` 任意 HTTP 响应即算在监听（`:156–173`，**无法区分端口上是不是自己的进程**）。停止 `killpg` TERM→5 秒→KILL（`:121–143`），`atexit` 回收（`:146–153`，后端被强杀时不执行）。
- 登录（`:301–391`）：先停共享 server（同端口作回调），`npx -y @larksuiteoapi/lark-mcp login -a <id> **-s <secret>**`（`:333–337`，**Secret 进 argv，违反其自身规则 4**），无进程组，`communicate(timeout=300)`；成功写登录态并按原状拉起 server（`:382–386`）。登出（`:408–436`）：清本地登录态 + `lark-mcp logout -a <id>`（60 秒）。
- **令牌存储是 lark-mcp 全局的**：`~/Library/Application Support/lark-mcp-nodejs/storage.json`（AES-256-CBC），密钥在 Keychain `lark-mcp`/`encryption-key`（`token_status.py:1–10,28–29,36–60`）——**任何应用跑的 lark-mcp 都共用这一份**；过期检测靠 node 解密该文件（`:82–100,149–230`）并扫 lark-mcp 日志里的 20038（`:122–147`）。
- 补丁（`lark_mcp_singleflight.js`，**D13**）：`Module._load` 拦截（`:67–69`），single-flight + 三段 supersession（verifyAccessToken 对过期但有 refreshToken 的 bearer 伪造“未过期”、removeToken 改写接替链、ensureGetUserAccessToken 换成链尾 token，`:1–40,186–259`）；按 lark-mcp 0.5.1 内部结构编写，上游改版时只打印 `[lark-mcp patch] … skip/failed` 并跳过（`:96–114,221`）。结合未锁版本 = 刷新/撤销语义可随上游静默漂移。
- **Bearer 注入**（`lark_token_inject.py:1–10,68–144`）：把当前 UAT 作为静态 `Authorization` 写进 Claude/Gemini/Codex 的 MCP 配置文件（备份 + 原子替换），靠补丁让过期 bearer 长期可用；UI 按钮（`mcp_config_tab.py:668–695`）与 TG `mcp:larkinject`（`tg_control.py:1200–1209`）触发。
- 监督（`proc_supervise.py`）：`spawn_supervised`（`:62–108`，独立进程组，信号处理只发信号）、孤儿监视每 2 秒查 `ppid==1`（`:44–59`）、`install_orphan_reaper`（`:111–116`）；stdio 兼容入口 `mcp_lark_server.py:65–94`。
- Node（`node_bootstrap.py`）：内置 `v20.18.1`（`:34`）；运行时查 npm registry 最新 lark-mcp 的 engines（`:40,57–75`）；从 nodejs.org 下载（`:145–147`）**无校验和**，`tarfile.extractall` **无过滤**（`:550–556`）。

### Figma MCP（`app_figma/*`）

- wrapper（`mcp_figma_server.py:44–83`）：PAT 在旧 Keychain `my-own-script`/`figma_api_token`（`secrets.py:8–12`），`npx -y figma-developer-mcp --stdio`（**未锁版本**，`:64–69`），子进程继承**整个** `os.environ` 再加 `FIGMA_API_KEY`（`:73–74`），`NODE_OPTIONS=--require figma_mcp_concurrency.js`（`:28–41`；默认串行 1、间隔 350 ms、重试 4，`figma_mcp_concurrency.js:24` 起），`spawn_supervised`（`:83`）。
- manager（`mcp_server_manager.py:38–105`）：同 ADO 的 D08 形态，另在无响应时 `stderr.read()` 读到 EOF（`:76–79`，子进程不退就永久阻塞）。
- 过期（`store.py:18–20,63–80`）：PAT 最长 90 天，保存时记录天数推算到期；在线探活 `/v1/me` 403 不判失效（`token_status.py:22–38`）。注册片段 `figma`（`figma_mcp_flow.py:27–47`）。

### 债务与新端现状

- **D08**（README）：握手无截止、管道未持续消费、停止失败丢句柄——见 ADO/Figma manager；Lark 持锁 10 秒轮询。
- **D13**（README）：Lark 内部补丁与未锁版本漂移影响刷新与撤销语义；另：补丁 1 让过期 bearer 在 refreshToken 有效期内一直被接受，叠加 Bearer 注入，等于长期静态凭据落在三个 CLI 配置文件里。
- 其他：登录 Secret 进 argv；Node 下载无校验/解包无过滤；`npx -y` 运行时拉包；ADO 写工具对 AI 默认开放；附件缓存无上限且在仓库目录。
- 新端：S1 已把 `lark_settings.yaml`/`figma_settings.yaml` 原样保留在 `imported.lark`/`imported.figma`（`next/backend/src/toolbox_backend/domain/settings.py:204–208`，`adapters/legacy_config.py:15`）；凭据适配器可只读旧 Keychain `my-own-script`、写新服务名（`adapters/credentials.py:67,80–94`）；S5 监督器 `adapters/proc_supervisor.py` + `adapters/ai_process.py:87–98 SupervisedProcess`（pipe/pty，控制管道 EOF 回收进程组）。
- **S5 工单 AI 分析当前依赖旧 MCP 注册名**：`domain/ai.py:136–143 McpToolPrefix`（Claude 固定 `mcp__ado-work-items__`，Codex 默认 `mcp__adoWorkItems__`，agy 默认 `mcp__ado-work-items__`）、`services/ai_prompt.py:9,34–60`（显式 library/project 名称；新端独有项目 `proj:` 前缀给警示，因为旧 server 读旧配置解析不到）。

## S6 数据模型与访问边界（主控技术裁决；涉及取舍的见「S6 待决」，下文“推荐”按待决推荐写，确认后以「S6 已决」为准）

实现完成须按 backend-architecture-review、backend-security-review、backend-business-safety、data-consistency-review、resource-lifecycle-audit 复核。

### 架构五问

1. **产生什么数据**：config schema v4 新增类型化 `mcp` 段（ado/lark/figma/runtime）与 `ai.analysis.mcp_source`；Keychain `toolbox-next` 新 account `lark_app_secret:<app_id>`（kind `lark_app_secret`）、`figma_token`（kind `figma_token`）；`<data-dir>/mcp/` 下：ADO 附件缓存、Node 运行时与 npm 包前缀（含锁文件）、Lark 托管日志（已脱敏、轮换）、策略基线 `ai_change_policy.yaml`（待决5）。**不新增 SQLite**（状态在内存，重启后由进程实况重建）。不复制 lark-mcp 的 `storage.json`，不存 UAT/refresh_token。
2. **数据流**：AI CLI →（stdio）新 ADO server `python -m toolbox_backend.mcp.ado_server --data-dir <dir>` → 只读打开新 config + 新 Keychain PAT → S2 `adapters/ado_read.py` 出站 → ADO。AI CLI →（stdio）`python -m toolbox_backend.mcp.figma_wrapper --data-dir <dir>` → node `figma-developer-mcp` → api.figma.com。AI CLI →（HTTP URL）→ 后端托管的 lark-mcp（`services/mcp.py` McpService 经 `proc_supervisor` 唯一持有）→ Lark。桌面 → S0 Bearer HTTP/WS → McpService（状态、自检、Lark 启停/登录/登出、凭据、运行组件安装 job、接入片段）。工单 AI 分析 → `ai_prompt` 按 `ai.analysis.mcp_source` 取前缀。
3. **谁能访问**：HTTP/WS 仍为单一本机主体（S0）；凭据只写不读回。stdio server 由 CLI 以当前用户身份启动，读取范围限于 `--data-dir` 指定的新数据目录（拒绝符号链接、属主校验）与新 Keychain 条目；AI 可调用的工具集合见待决3。lark-mcp 只监听 `localhost:<port>`，其 OAuth 由 lark-mcp 自身把关。TG（待决10）仅 owner。
4. **并发冲突**：每数据目录一个 McpService（沿用后端 flock）；Lark 状态机单写者（`stopped|starting|running|stopping|logging_in|failed`），启停/登录/登出互斥（409 `mcp_busy`），**状态查询不等锁**（读快照）；自检每 server 同时 ≤1；安装 job 同时 1 个。stdio server 多实例并发安全：只读 config（不加写锁，按 S1 原子替换读到完整版本）、附件缓存写 `O_EXCL` 临时文件后 `rename`，LRU 清理用目录 flock。配置写冲突沿用 revision 409。
5. **失败/清理**：所有后端启动的子进程（自检、lark-mcp、login、logout、npm/node 安装）都经 `proc_supervisor`：后端被强杀 → 控制管道 EOF → TERM 进程组 → 3 秒 → KILL；正常路径统一 `McpLifecycle` 上下文释放进程、管道、读任务、日志句柄。stdio server/wrapper 自身三信号自杀（stdin EOF、SIGTERM/SIGINT → 回收子进程组、父进程变化）。后端退出：lifespan 中 McpService 与 AISessionService 并行收尾，总预算不变（≤5 秒）。

### config schema v4（`mcp` 段；v3→v4 只新增，迁移快照/原子写/幂等同 S4/S5 规则）

```
mcp:
  ado:   {allow_create_work_item: false, attachment_cache_mb: 500, attachment_max_mb: 25, query_max_items: 200}
  lark:  {app_id: "", domain: "https://open.larksuite.com", tools: <旧默认>, language: "zh", port: 3000,
          scope_hint: <旧默认 scope，仅作缺权提示，不进 argv>, owner_confirmed_at: null, autostart: false,
          login: {logged_in_at: null, scope: null}}   # 仅元数据，不含令牌
  figma: {token_set_at: null, expiry_days: 90, max_concurrency: 1, min_interval_ms: 350, max_retry: 4}
  runtime: {node: {source: "detected|managed|none", path: null, version: null},
            packages: {"@larksuiteoapi/lark-mcp": "<S6-0 锁定>", "figma-developer-mcp": "<S6-0 锁定>"}}
ai.analysis.mcp_source: "legacy" | "toolbox"   # 默认 legacy（待决4）
```
- 迁移：`imported.lark` 的 app_id/domain/tools/language/oauth_port/scope 规范化进 `mcp.lark`（旧 legacy 默认值升级规则同旧 `store.py:118–123`）；`imported.figma` 的到期天数/设置时间进 `mcp.figma`；`owner_confirmed_at` 一律 null、`autostart` false；`imported.*` 原样保留。端口 1024–65535；domain 只允许 https 且 host 在 `open.larksuite.com|open.feishu.cn`；tools 逗号分隔、每项 `^[A-Za-z0-9_.]{1,80}$`、≤40 项。

### 凭据

- `lark_app_secret:<app_id>`、`figma_token` 写入 `toolbox-next`；HTTP 只写（PUT/DELETE），GET 只返回 `configured`/`state`。旧 Keychain 只经显式“从旧应用导入”读取（S1 模式，旧条目不改不删）。
- 子进程注入：lark-mcp 只经 `APP_SECRET`、Figma 只经 `FIGMA_API_KEY`，**任何凭据不进 argv**（含 login，见 S6-0）；子进程环境 = S5 过滤后的环境 + PATH 补全 + 该 server 必需的一个变量；`NODE_OPTIONS` 由我们整体设置（不继承用户值）。合同如实记录限制：环境变量对同用户进程不是保密的（`ps eww`）。
- 新 ADO server 每次调用从新 Keychain 取 PAT（不缓存到磁盘）；PAT 缺失 → 工具错误“请在设置中配置该库的 PAT”。

### ADO 工单 MCP server（`toolbox_backend/mcp/ado_server.py`，新实现）

- 协议：MCP stdio JSON-RPC 2.0，支持 `2025-06-18|2025-03-26|2024-11-05`，客户端给的版本在此集合内则回显、否则回最新（不回显任意字符串）；`initialize`/`notifications/initialized`/`tools/list`/`tools/call`/`ping`；单行 ≤4 MiB，超限回 -32600；未知方法 -32601。serverInfo `{name:"toolbox_ado"}`。
- 工具名与入参与旧 server 兼容（便于提示词与习惯迁移），**但不再回落 UI active_\***：必须给 `library_name`+`project_name` 或 `library_id`+`project_id`（新 store 中的 id），否则工具错误；名称匹配规则同旧 `_normalize_name`。读取统一走 S2 `adapters/ado_read.py`（超时、重定向、同源、响应大小上限）。
- `ado_query_work_items`：WIQL 原样提交到该 project 的只读 WIQL 端点（ADO 自身限定 project），结果截断到 `query_max_items` 并返回 `truncated`；`fields` 每项 `^[A-Za-z][A-Za-z0-9_.]{0,127}$`、≤50 项。
- `ado_get_attachment`：URL 必须与 library `base_url` 同 scheme+host+port（S2 `trusted_base_url` 规则）；单文件 ≤`attachment_max_mb`；缓存 `<data-dir>/mcp/ado-attachments/<library_id 摘要>/<wi>/<attachment_id>_<安全文件名>`，目录 0700/文件 0600、`O_NOFOLLOW`、总量 ≤`attachment_cache_mb` LRU + 14 天过期；图片压缩沿用旧规则（Pillow 已在依赖中则用，否则跳过并在结果标注）。
- `ado_create_work_item`：仅 `mcp.ado.allow_create_work_item=true` 时出现在 `tools/list` 且可调用（待决3），`extra_fields` 键同 fields 正则、≤20 项、值为字符串/数字且 ≤8 KiB，禁止 `System.Id|System.Rev|System.State|System.Reason` 等系统写字段（清单在实现中固定并测试）；支持 `validate_only`。
- `ado_evaluate_change_policy`：移植旧 `ai_policy.evaluate_change_policy` 为纯函数；基线来源见待决5，覆盖层读新 store `imported.ai.default_policy` 与 `imported.ai.project_overrides[<project_id>]`（新端独有项目只用全局层）。
- 三信号：stdin EOF 退出；SIGTERM/SIGINT 立即退出；父进程变化（与启动时 ppid 比较，每 2 秒）退出。纯 Python，不派生子进程。stderr 只写脱敏后的错误摘要。

### stdio 自检（替代旧“启动/停止”，D08）

- `POST /api/mcp/{ado|figma}/self-test`：经 `SupervisedProcess`（pipe）启动与 CLI 完全相同的命令 → 发 initialize → initialized → tools/list；stdout 由独立读任务持续消费（行 ≤4 MiB）、stderr 64 KiB 环形缓冲；**总截止 15 秒**（Figma 首次可能较慢，可配置 ≤60 秒）；成功/失败/超时/取消都走：关 stdin → 等 2 秒 → 关控制管道（监督器 TERM 组 → 3 秒 → KILL）→ 等 ≤2 秒，未退出记 `kill_failed`。结果 `{ok, protocol_version, server_name, tools[], duration_ms, error_code, stderr_tail(脱敏)}`，不保留常驻进程。

### Lark 托管（McpService，D08/D13）

- 运行命令：`<node> <prefix>/node_modules/@larksuiteoapi/lark-mcp/<bin> mcp -a <app_id> -d <domain> -t <tools> -m streamable --host localhost -p <port> --oauth --token-mode user_access_token -l <lang> [--debug]`（不经 npx；不传 `--scope`；版本由 S6-0 锁定；`--debug` 是否保留看 S6-0 对日志是否含令牌值的核对）。`NODE_OPTIONS=--require <资源目录>/lark_mcp_patches.js`（旧补丁移植，**增加**：启动时把每个补丁的结果按固定标记 `[toolbox-lark-patch] <name>=applied|skipped|failed` 打到 stderr）。
- 启动：需 `owner_confirmed_at`（409 `lark_owner_unconfirmed`）、App Secret 已配置（409 `lark_not_configured`）、运行组件就绪（409 `mcp_runtime_missing`）；登录元数据为空只提示“未在新端登录过（共享存储下可能已有旧端登录）”，不阻止启动；**预检端口**：若 `localhost:<port>` 已可连接 → 409 `mcp_port_in_use`（多半是旧应用仍在运行），不启动；经监督器启动，stdout/stderr 由读任务逐行脱敏后写 `<data-dir>/mcp/logs/lark-mcp.log`（5 MiB×2 轮换，0600）并抽取补丁标记；每 250 ms 探 `GET /mcp`（任意 HTTP 响应 = 在监听）直至 15 秒；进程提前退出 → `failed` + 日志尾；超时 → 回收 + `failed(start_timeout)`。启动过程**不持状态锁**（状态机 + 单飞任务），状态查询读快照。
- 补丁状态：三项任一不是 `applied` → 状态 `running_degraded`，桌面提示“刷新补丁未生效：过期后可能需要重登”。
- 健康：运行中每 30 秒探一次 `GET /mcp`，连续 3 次失败且进程仍在 → `unhealthy`（不自动重启）；进程退出 → `failed(exited)`。
- 停止/退出：关控制管道 → 监督器 TERM 组 → 3 秒 → KILL；后端被强杀同样回收（旧端靠 `atexit` 做不到）。
- 登录：需 owner 确认；若 server 在运行先停（记住原状），以监督器启动 `lark-mcp login -a <id> -d <domain> -p <port>`，Secret **只经环境变量**（S6-0 核对 login 是否支持；不支持则停下交主控，不退回 argv），超时 300 秒、可取消；成功 → 写 `mcp.lark.login`（时间与 scope，不含令牌）→ 按原状拉起；失败 → 日志尾（脱敏）。
- 登出：停 server → `lark-mcp logout -a <id>`（60 秒）→ 清登录态；提示“已写入各 CLI 的旧 bearer（若有）随之失效，各客户端需重新授权”。
- 令牌状态（待决8）：只用登录时间 + 托管日志与 `~/Library/Logs/lark-mcp-nodejs` 中刷新成功/20038 标记推断（`ok|refresh_failing|unknown`，附最近事件时间），不解密 `storage.json`、不读 `lark-mcp` Keychain 条目；20038 时给“一键重登”（登出 → 登录）。
- 令牌存储（待决6 推荐 A）：沿用 lark-mcp 全局 `storage.json`（新旧应用同一份）——所有权 = 谁在运行 lark-mcp 进程；端口预检让新旧不能同时运行。

### Figma wrapper（`toolbox_backend/mcp/figma_wrapper.py`）

- CLI 以 `python -m toolbox_backend.mcp.figma_wrapper --data-dir <dir>` 启动 → 读新 Keychain `figma_token`（缺失则 stderr 提示并 exit 2）→ 以内建监督（复用 `proc_supervisor` 的 fork/进程组/TERM→3 秒→KILL/后代清理函数，抽成共享函数；S5 行为与测试不变）运行 `<node> <prefix>/node_modules/figma-developer-mcp/<bin> --stdio`，stdio 直通；环境 = 过滤后环境 + `FIGMA_API_KEY` + `NODE_OPTIONS=--require figma_mcp_concurrency.js`（参数来自 `mcp.figma`）；三信号同 ADO server。

### Node 运行时与 npm 包（待决9 推荐）

- 检测顺序：`mcp.runtime.node.path`（用户确认过的）→ 托管目录 → 系统/brew/fnm/旧应用 bootstrap 目录（只读用其 node，不改）；版本需满足锁定包的 engines。
- 安装 job（显式操作，联网）：Node 从 nodejs.org 下载固定版本 + 同版本 `SHASUMS256.txt` 校验，`tarfile` 用 `filter="data"` 解包到 `<data-dir>/mcp/runtime/`；npm 包按仓库内锁文件（`next/backend/resources/mcp/package.json` + `package-lock.json`，S6-0 生成）`npm ci --prefix <data-dir>/mcp/packages`；600 秒，可取消，输出脱敏 ≤256 KiB，WS `mcp.job`。运行时**不再 `npx -y`、不再在线查 registry**。

### CLI 接入片段与 S5 工单分析切换

- `GET /api/mcp/client-config?server=ado|lark|figma&cli=claude|codex|agy` 返回可复制片段（无凭据）：ADO/Figma 为 stdio `command`+`args`（打包后的内置 python 绝对路径 + `-m …` + `--data-dir`），Lark 为 URL。**注册名统一 `toolbox_ado`、`toolbox_figma`；Lark 保留 `lark`**（URL 不变时客户端无需改）。新端不写任何 CLI 配置文件（待决7）。
- 切换方案（待决4 推荐）：新 ADO server 以新名字与旧 `ado-work-items`/`adoWorkItems` **并存**；`ai.analysis.mcp_source=legacy|toolbox`（默认 legacy）决定提示词前缀：`toolbox` 时三家 CLI 都用 `mcp__toolbox_ado__`（`McpToolPrefix` 保留给 legacy）；`toolbox` 下去掉“新端独有项目”警示（新 server 读新 store）。切换步骤：①在各 CLI 按片段注册 `toolbox_ado` → ②桌面自检通过 → ③用户在设置里把来源切到“新端 ADO MCP”（需勾选“已在 Claude/Codex/agy 注册”）→ ④一次桌面工单 AI 分析验证 → ⑤（可选）各 CLI 删除旧注册。回退：来源切回 legacy。

### HTTP / WS 接口（全部在 S0 Host/CORS/Bearer/BodyLimit 之后；错误沿用 S1 detail 结构）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/mcp` | 三个 server 状态快照、runtime、包版本、owner、登录态、令牌/补丁状态、revision |
| PATCH | `/api/mcp/settings` | `mcp.*` 设置（revision 409）；Lark 运行中改端口/app_id → 409 `mcp_busy` |
| PUT/DELETE | `/api/mcp/credentials/{lark_app_secret\|figma_token}` | 只写；Figma 同时记录 `token_set_at`/`expiry_days` |
| POST | `/api/mcp/credentials/import-legacy` | `{kinds:[…]}` 从旧 Keychain 导入（不改旧条目）；`lark_app_secret` 同时只读导入旧 `lark_login_state.json` 的元数据（不含令牌） |
| POST | `/api/mcp/{ado\|figma}/self-test` | 自检（同步返回，≤截止） |
| POST | `/api/mcp/lark/{start\|stop\|login\|login/cancel\|logout}` | `request_id` 幂等；login 立即返回、进度经 WS |
| POST/DELETE | `/api/mcp/lark/ownership` | POST 需 `{ack_old_app_stopped:true}`；DELETE 需已停止 |
| POST | `/api/mcp/runtime/install`、`/api/mcp/jobs/{id}/cancel` | 安装 job |
| GET | `/api/mcp/client-config` | 接入片段 |
| WS 主题 | `mcp` | `mcp.status`（状态变化）、`mcp.job`（安装进度），回放/水位同 S3 规则 |

新错误码：`mcp_busy`、`mcp_port_in_use`、`mcp_runtime_missing`、`lark_owner_unconfirmed`、`lark_not_configured`、`mcp_self_test_failed`（200 内结果字段，不作 HTTP 错误）。

### 安全核对表（施工与验收都按此）

1. 任何子进程 argv 不含 Secret/PAT/Token（静态扫描 + 替身打印 argv 断言）；login 同样。
2. 子进程环境：S5 过滤后只加该 server 必需的一个凭据变量；`NODE_OPTIONS` 只含我们的 preload。
3. 凭据只写不读回；日志/事件/WS/错误/托管日志/自检 stderr_tail 全部脱敏（S4 统一脱敏 + Lark `u-`/`ur-` 令牌形态 + `Bearer …`），扫描假密钥。
4. ADO server：不回落 active_*；附件同源 scheme+host+port、大小上限、`O_NOFOLLOW`、0700/0600、LRU；WIQL 结果上限；写工具默认关闭、字段黑名单。
5. `--data-dir` 必须是属主为当前用户、非符号链接、权限不宽于 0700 的目录，否则 exit 2。
6. lark-mcp 只绑 localhost；端口预检；不解密 storage.json；不写 CLI 配置文件。
7. 运行组件：锁版本 + 锁文件完整性；Node 下载 SHA256 校验；解包 `filter="data"`；不在运行时联网取包。
8. 所有进程经监督器，后端 SIGKILL 后零残留；状态查询不被启动/握手阻塞。
9. 路由全部 Pydantic DTO，契约重新生成；无新增 HTTP 外部出站（ADO 读走 S2 客户端；Figma/Lark 出站发生在第三方进程内）。

## S6 通用合同与模型分工

- **派工门禁**：用户确认本合同与「S6 待决」；主控写入「S6 已决」并提交输入 SHA；若待决1 授权，主控先完成 S6-0 并把结论写回本节，再派 S6-B。
- 模型分工（同 S5）：后端施工 codex exec `gpt-6.1-sol` / medium（workspace-write、不联网；额度不足按 prefs 换下一个候选）；测试 codex `gpt-6-luna` / high 或 Claude Haiku 5.5（每包至多一个，仅写 `tests/independent/s6x/`）；前端施工 agy `gemini-3.8-flash-high`、`--sandbox`、`--print=`；不做交叉审计。
- 每包 worktree `.local/worktrees/s6{a,b,c}`，detached 自输入 SHA；施工者不 commit；主控核对 diff 与沙箱外全量测试后以限定路径 binary patch 集成。
- 测试只用临时数据目录、内存凭据、**替身**：Python 写的假 stdio MCP server（正常、无响应、错响应、提前退出、大量 stderr、忽略 TERM、派生孙进程）、假 `node`/假 lark-mcp（`GET /mcp` 405、login 成功/失败/挂起、打印 argv/env、补丁标记缺失）、假 npm、假 ADO（S2 MockTransport）；**禁止调用真实 node/npx/npm/lark-mcp/figma-developer-mcp/claude/codex/agy**（PATH 只含替身目录，命中即失败）；沿用 conftest keyring/socket 守卫；端口用例用随机端口，沙箱拒绝时主控沙箱外跑。
- 禁止：按进程名 kill、裸 git stash、删除/放宽既有测试、仓库内留报告、改旧应用、读真实配置/凭据/CLI 配置/lark-mcp 存储、联网（S6-0 与安装 job 的真实执行除外，均需授权）。

## S6-0：协议与版本核对（主控；已完成 2026-10-26，结论见下）

在 scratchpad 临时前缀 `npm install` 当前最新的 `@larksuiteoapi/lark-mcp` 与 `figma-developer-mcp`（联网仅 npm registry），不登录、不调真实 API：记录版本与 engines；`lark-mcp mcp --help`/`login --help`/`logout --help`、`figma-developer-mcp --help`；核对 `login` 是否支持 Secret 经环境变量、`--debug` 日志是否会写令牌值（读源码）、补丁目标（`ensureGetUserAccessToken`、`authStore.storeToken/removeToken`、`LarkOIDC2OAuthServerProvider.verifyAccessToken`）在该版本是否存在且签名一致、figma 是否仍用全局 fetch。结论写回本节并生成锁文件；与本合同不符时先改合同再派工。

### S6-0 结论（主控，2026-10-26；本节优先于上文 S6 各节与旧代码注释）

环境：scratchpad 临时前缀 `npm install --ignore-scripts`（仅 npm registry），系统 Node v24.13.0；运行 `--help` 与离线握手时 HOME 指向临时目录、`keytar` 用 `--require` 假模块拦截（不碰真实 Keychain），APP_ID/Secret/FIGMA_API_KEY 均为假值，未登录、未调真实 API。

1. **版本与锁定**：`@larksuiteoapi/lark-mcp` 最新仍为 **0.5.1**（与旧补丁编写版本相同），engines `node>=20.0.0`，bin `dist/cli.js`；`figma-developer-mcp` 最新 **0.13.2**（旧端为 0.12），engines `node>=20.20.0`，bin `dist/bin.js`；均 MIT。锁文件已生成：`next/backend/resources/mcp/package.json`（两包精确版本）+ `package-lock.json`（lockfileVersion 3，238 个包，`resolved` 全部为 registry.npmjs.org 且带 integrity）。
2. **Node**：两包要求取高者 `>=20.20.0`；旧端内置 v20.18.1 不满足 figma。检测按此下限判定；托管下载的固定版本定为 **v24.13.0**（本机已用它跑通两包）。
3. **Secret 不进 argv**：`lark-mcp` 的 `mcp` 与 `login` 都把 `APP_ID/APP_SECRET/LARK_DOMAIN/LARK_TOOLS/LARK_TOKEN_MODE/USER_ACCESS_TOKEN` 环境变量并入选项（`utils/constants.js:23–30`、`cli.js:43,90`）→ login 与 mcp 一样只经环境变量 `APP_SECRET` 传 Secret，**不需要 `-s`**。子进程环境须显式去掉这组变量里除 `APP_SECRET` 以外的、来自父环境的值。
4. **`.env` 注入面**：lark-mcp 启动即 `dotenv.config()`（读 cwd 的 `.env`），figma 以 `override:true` 读 cwd 的 `.env`（可覆盖 `FIGMA_API_KEY`）→ 两者子进程 **cwd 必须是新端专用空目录**（`<data-dir>/mcp/run/<lark|figma>/`，0700），不得继承 CLI 的项目目录。
5. **`--debug` 与日志**：源码中**没有任何 `logger.debug` 调用**；`--debug` 只把级别从 WARN 降到 DEBUG，从而写出 INFO 行。INFO/DEBUG 只写 lark-mcp 自己的日志文件 `~/Library/Logs/lark-mcp-nodejs/lark-mcp-YYYY-MM-DD.log`（保留 7 天），stderr 只有 WARN/ERROR。令牌在日志中只以 `Boolean(...)` 出现；授权 URL（含 client_id/state/code_challenge）会写入；**授权失败时会写出 authorization code**（`auth/handler/handler.js:53`、`handler-local.js:55`，一次性、短时有效）。裁决：**保留 `--debug`**（刷新成功标记只在 INFO 级），托管读任务对 `code=`/`code:` 后的值与 `Bearer` 值脱敏。
6. **令牌状态标记**（待决8）：刷新成功 = `Successfully refreshed token`（INFO，只在 lark-mcp 自己的日志文件）；失败 = `Token refresh failed:`（ERROR，同时到 stderr）。20038 只有在 HTTP 200 + 业务码时才出现在文本中（`Token parse failed: invalid response: 20038, …`）；非 2xx 时响应体被打成 `[object Object]`。裁决：任何 `Token refresh failed` 即 `refresh_failing`，不以 20038 为必要条件。
7. **补丁目标**：`LarkMcpTool.prototype.ensureGetUserAccessToken`（`mcp-tool/mcp-tool.js:92`）、`authStore.storeToken/removeToken`（`auth/store.js:116,122`，`authStore` 为单例，原型方法）、`LarkOIDC2OAuthServerProvider.prototype.verifyAccessToken`（`auth/provider/oidc.js:158`，`async (token)`）均存在且签名与旧补丁一致。
8. **旧补丁缺陷（新发现，S6-LEAD-001）**：旧 `lark_mcp_singleflight.js` 用**请求字符串**预过滤（含 `lark-mcp`/`mcp-tool`/`auth` 才解析），而 OIDC provider 由 `auth/provider/index.js` 以 `require("./oidc")` 加载，不命中 → **服务模式下 verifyAccessToken 补丁从未生效，且不打印 skip/failed**（主控以 `require.cache` 探针在 `mcp -m streamable --oauth` 下复现：oidc 已加载、`__sfPatched=false`；预过滤加 `oidc` 后为 true，三条补丁日志齐全）。旧端同样受影响（npx 解析到的也是 0.5.1），可能是“过期后需要重登”的原因之一。新补丁：按 `Module._resolveFilename` 后的路径判定（不按请求字符串预过滤），并输出合同要求的 `[toolbox-lark-patch] <name>=applied|skipped|failed` 标记；S6-B 回归须覆盖“以相对路径 `./oidc` 加载”的场景。旧应用不改（已决11），只记账。
9. **keytar 原生模块**：lark-mcp 依赖 `keytar@7.9.0`（安装脚本 `prebuild-install || node-gyp rebuild`，N-API v3）。`authStore` 在 require 时即初始化存储并访问 Keychain；keytar 不可用时只打印 WARN 并**静默退回内存存储**（令牌重启即失）。裁决：安装 job 用 `npm ci --ignore-scripts` 后**单独 `npm rebuild keytar`**（预编译包从 GitHub Releases 下载，失败退回本机 node-gyp 编译；本机有 Xcode）——这是 npm registry 之外唯一的联网目标，仍只在你点“安装运行组件”时发生；`protobufjs` 的安装脚本只做版本提示，跳过。Lark 启动时 stderr 出现 `Builtin User Access Token Store will be disabled` → 状态 `running_degraded`（文案“令牌存储不可用，重启后需重登”）。未验证：`npm rebuild keytar` 实际下载与编译（超出本次 registry-only 授权，留到 S6 真实验收）。
10. **Keychain 访问提示风险**：`lark-mcp`/`encryption-key` 条目由旧端所用的 node 二进制创建；新端换用别的 node 路径时，macOS 可能在首次访问弹出钥匙串授权。写入真实验收清单第 3 项与所有权切换步骤 4 的注意事项，不在代码里规避。
11. **登录窗口**：`login` 内部固定等待 **60 秒**（`cli/login-handler.js` `timeout=60000`，CLI 不可配），超时 exit 1；后端 300 秒上限仅作外层兜底，桌面提示“请在 60 秒内完成浏览器授权”。登录完成判定靠轮询存储，存储不可用时登录必然失败（见 9）。
12. **健康探针**：`mcp -m streamable --oauth` 冷启动约 1.25 秒后 `GET /mcp` 返回 **405**，`/.well-known/oauth-authorization-server` 返回 200；SIGTERM 后 1 秒内退出。合同的“任意 HTTP 响应 = 在监听”成立。
13. **Figma 0.13.2**：
    - 默认开启 PostHog 遥测（`us.i.posthog.com`）→ wrapper 必须传 `--no-telemetry` 并设 `FRAMELINK_TELEMETRY=off`、`DO_NOT_TRACK=1`；测试断言 argv/env 含这三项。
    - 图片下载默认写子进程 cwd → wrapper 以 `--image-dir <CLI 启动 wrapper 时的 cwd>` 显式保持旧行为（写入项目目录），子进程 cwd 仍用第 4 条的空目录。
    - 仍用全局 `fetch`（ESM 自由引用），旧 `figma_mcp_concurrency.js` 的 `globalThis.fetch` 包装可沿用；设置代理环境变量时它会 `setGlobalDispatcher`，不影响包装。离线握手通过：协议 `2025-06-18`，工具 `get_figma_data`、`download_figma_images`，stdin EOF 后 exit 0；限流路径未在真实 API 上验证。
    - 凭据只读 `FIGMA_API_KEY`/`FIGMA_OAUTH_TOKEN` 环境变量或 `--figma-api-key`；新端只用环境变量。


## S6-A：后端——config v4、凭据、ADO MCP server、自检、接入片段、分析来源切换

- write_scope：`next/backend/**`、`next/contracts/**`；测试员仅 `next/backend/tests/independent/s6a/`。
- 结果：v3→v4 迁移；两个新凭据 kind 与旧 Keychain 导入；`mcp/ado_server.py`（协议、8 工具、上下文、附件缓存、策略移植、写工具开关、三信号）；`proc_supervisor` 抽出共享监督函数（S5 测试全过）；stdio 自检；`client-config`；`ai.analysis.mcp_source` 与提示词前缀；`GET /api/mcp`（ADO 部分）、settings/credentials 路由；契约重新生成。
- 自动验收：后端 pytest/ruff/contracts exit 0，覆盖：迁移幂等与快照；ADO server 每个工具（假 ADO）、协议版本协商、坏 JSON/超长行/未知方法、必须显式上下文、附件跨源/超限/符号链接/LRU、WIQL 截断、写工具关闭时不在列表且调用被拒、字段黑名单、PAT 缺失；三信号（关 stdin、TERM、父进程被杀）均退出；自检的无响应/错响应/提前退出/大量 stderr/忽略 TERM/孙进程/取消，全部零残留且 ≤截止；状态查询在自检进行中立即返回；提示词前缀随来源切换；argv/env/日志无假密钥。

## S6-B：后端——运行组件、Lark 托管与所有权、Figma wrapper、WS、TG

- 依赖：S6-A 集成、S6-0 结论。write_scope 同上；测试员仅 `tests/independent/s6b/`。
- 结果：runtime 检测与安装 job（校验和、安全解包、`npm ci`）；Lark 状态机（端口预检、监督启动、健康、补丁标记、degraded/unhealthy、停止、登录/取消/登出、owner 确认/撤销、令牌状态推断）；`figma_wrapper`；`mcp` WS 主题；TG（按待决10）；后端 lifespan 接入与关闭预算。
- 自动验收：端口被占 409；启动超时/提前退出/补丁缺失 degraded；后端 SIGKILL 后 lark 替身与孙进程全部退出；登录挂起超时与取消、Secret 不进 argv、登录期间启动被拒；登出清状态；owner 未确认全部 409；安装 job 校验和不符拒绝、tar 路径穿越被拒、取消回收；Figma wrapper 三信号与子进程组回收；shutdown 预算 ≤5 秒（与 AI 会话并存）；日志脱敏。

## S6-C：前端——MCP 页（agy）

- 依赖：S6-A 契约（ADO/通用部分可先做）、S6-B 契约。write_scope `next/desktop/**`；测试员仅 `tests/independent/s6c-*`。
- 结果：设置下新增「MCP」分区（R1 macOS 原生风格）三张卡：ADO（自检、写工具开关 + 二次确认、附件缓存用量/清空、接入片段复制、分析来源切换步骤 Sheet）；Lark（凭据/导入、运行组件状态与安装、所有权确认 Sheet（四步说明 + 勾选“旧应用已停止且不再在旧应用登录/登出”）、启停、登录/取消/登出/一键重登、补丁与令牌状态、URL 复制）；Figma（Token/导入/到期提醒、限流参数、自检、片段）。选项只来自后端枚举；凭据输入提交后清空。
- 自动验收：前端 frozen install/typecheck/lint/test/build/guard:dist/contracts:check；DOM/存储/URL 无凭据；各错误码文案。

## S6 集成验收（主控）

- 后端完整 pytest/ruff/contracts；前端 frozen install/typecheck/lint/test/build/guard:dist/contracts:check；Rust 未改则 `cargo test --offline` 复跑一次确认退出不超时；`git diff --check` 与限定路径检查。
- 主控亲自核对：所有子进程的关闭点（resource-lifecycle-audit 逐项清单）、后端 SIGKILL 零残留、argv/env/日志无密钥、ADO server 显式上下文与附件边界、写工具开关。
- dev:web 端到端（假 ADO + 假 node/lark-mcp + 替身 CLI）：ADO 自检 → 片段复制 → 切换分析来源 → 桌面工单 AI 分析提示词前缀正确；Lark 导入凭据 → 所有权确认 → 启动（模拟端口被占 409）→ 补丁 degraded 提示 → 停止；Figma 自检；退出后 `ps` 无替身残留。
- PROGRESS 列 迁移 / 改进 / 有意推迟清单（对照旧 `docs/capabilities/mcp-servers.md`）。

### 真实验收清单（仅用户另行授权后执行；本合同提交不执行）

1. 安装运行组件（联网）；ADO：在 Claude/Codex/agy 注册 `toolbox_ado`，桌面自检；一次真实只读工单分析（读详情/评论/附件/策略），切换来源后再做一次；可选验证写工具开关（`validate_only`）。
2. Figma：导入 PAT，三家 CLI 注册 `toolbox_figma`，一次读取设计数据（含并发 5 个调用不 429）。
3. **Lark 所有权切换**（按下节步骤）；切换后客户端调用成功；闲置 >2 小时后首次调用自动续期（日志有刷新成功、无 20038）；登出后旧 bearer 失效；回退演练。
4. 回收：AI 会话运行中退出应用、强杀后端，`ps` 核对 lark-mcp 与 stdio MCP 进程全部退出（CLI 自己 spawn 的 stdio server 随 CLI 回收）。
5. 未测逐项记账。

### Lark 刷新所有权切换步骤（ARCHITECTURE §5；真实执行另行授权）

1. 前置：S6 集成验收通过；新端运行组件就绪；新端已导入 App Secret（旧条目不动）。
2. 旧应用：MCP配置 Tab 停止 Lark MCP；确认没有登录进行中；此后**不在旧应用点登录/登出/一键注入**（会改写同一份全局存储）。
3. 新端：所有权 Sheet 勾选确认 → `owner_confirmed_at` 写入；启动——端口预检通过即说明旧端已停（若 409 回到第 2 步）。
4. 新端显示补丁全部 applied、令牌状态 ok；用一个 CLI 调用 Lark 工具验证（URL 未变，已授权的客户端无需改动）。
5. 观察：闲置超过 2 小时后首次调用成功；新端令牌状态无 refresh_failing。
6. 回退：新端停止 → 撤销所有权 → 旧应用启动。共享存储下令牌连续，无需重登（待决6 选 B 时需在旧端重登）。

## S6 待决（已决，保留选项以便追溯；备选均不实施）

技术已定（无需拍板）：后端经 `proc_supervisor` 持有所有 MCP 相关进程并在被强杀时回收；stdio“启动”改为有界自检、不留常驻；ADO server 不回落 UI active_\*、附件缓存迁到数据目录并设上限；凭据不进 argv、环境只加必需变量；lark-mcp 端口预检；补丁结果标记与 degraded 状态；不新增 SQLite；运行时不 `npx -y`；新端不解密 storage.json 之外的取舍见下。

| 编号 | 需要拍板 | 推荐 | 备选与影响 |
| --- | --- | --- | --- |
| 1 | S6-0 协议与版本核对 | **授权主控在派 S6-B 前，于 scratchpad 临时前缀联网 `npm install` 两个包并跑 `--help`、读源码核对**（不登录、不调真实 API） | 不核对：按旧代码（lark-mcp 0.5.1、figma 0.12）锁版本施工，真实验收才发现 login 仍需 argv 传 Secret 或补丁目标已变 |
| 2 | ADO MCP 形态 | **stdio：每个 CLI 会话 spawn 新端 `toolbox_ado` server**（静态 PAT，应用没开也能用，与旧端一致；进程靠三信号回收） | 后端内置 streamable HTTP 单实例：零额外进程，但应用不运行时不可用，且各 CLI 配置里要放一个访问后端的静态 Bearer |
| 3 | ADO 写工具 `ado_create_work_item` | **保留，默认关闭**；在 MCP 页打开（二次确认），关闭时不出现在工具列表 | A：始终开放（旧端行为，AI 可直接建单）；B：删除写工具（需要建单时手工在 ADO 做） |
| 4 | 注册名与 S5 工单分析切换 | **新名字 `toolbox_ado`/`toolbox_figma` 与旧注册并存**；设置项 `ai.analysis.mcp_source` 默认 `legacy`，你注册并自检后手动切到新端，可随时切回 | 沿用旧名字 `ado-work-items`/`adoWorkItems`：提示词不用改，但必须一次性替换各 CLI 注册，旧应用的「MCP 分析」也会改用新 server（解析不到旧 project id） |
| 5 | 变更策略基线（`ado_evaluate_change_policy`） | **一次性从旧仓库 `config/ai_change_policy.yaml` 只读导入到新数据目录**（显式按钮），再叠加 `imported.ai` 覆盖层；编辑界面仍推迟 | 新端内置一份默认基线：不读旧仓库，但你本地对该文件的修改不会带过来 |
| 6 | Lark 令牌存储 | **A：沿用 lark-mcp 全局存储（新旧同一份）**——所有权=谁在运行进程；切换/回退不需重登，URL 不变客户端不动 | B：新端隔离存储（子进程改 HOME 等）：新端重新 OAuth、各客户端重新授权；旧端存储不受新端影响，回退时旧 refresh_token 可能已过期需重登 |
| 7 | Lark Bearer 注入各 CLI 配置 | **不移植**：各客户端首次连接各走一次浏览器授权（补丁保证之后自动续期），新端不写 `~/.claude*`、`~/.codex`、`~/.gemini` | 移植为显式操作（确认对话框、备份、列出写入文件）：免各客户端授权，但 UAT 明文长期留在三个配置文件里 |
| 8 | Lark 令牌状态的精度 | **只用登录时间 + 日志中的刷新/20038 标记推断**，不读 `lark-mcp` Keychain 条目、不解密 `storage.json` | 沿用旧端解密：显示精确到期时间，但新端要读第三方 Keychain 条目（会弹 Keychain 授权）并解析其私有存储格式 |
| 9 | Node 与 npm 包 | **优先用已装 Node；npm 包按仓库锁文件显式“安装运行组件”到数据目录**（联网只在你点安装时；Node 需下载时校验 SHA256）；运行时不联网 | 沿用 `npx -y <包>@<锁定版本>`：免安装步骤，但每次冷启动可能联网、经 npx→npm 多层进程 |
| 10 | TG 主 Bot 的 MCP 菜单 | **只做 owner 的状态查看 + Lark 启停**（不含注入、不含 ADO/Figma“启动”，它们改为自检） | 不提供 TG MCP 菜单：只能在桌面操作 |
| 11 | Lark 切换时机与旧应用 | **S6 验收通过后按上面步骤另行授权切换；不改旧应用代码**（靠端口预检互斥 + 步骤约束旧端不再登录/登出） | 在旧应用热修：检测到新端已接管时禁用 Lark 卡片按钮（更防误操作，但要改旧应用并验证） |

## S6 已决

- 用户 2026-10-26 原答复：**“S6 待决 1–11 全部按推荐，写入 S6 已决并提交，然后做 S6-0。”** 确认十一项：1 授权主控在派 S6-B 前于 scratchpad 临时前缀联网 `npm install` 两个包、跑 `--help`、读源码核对（不登录、不调真实 API）；2 ADO MCP 为 stdio，每个 CLI 会话 spawn 新端 `toolbox_ado`；3 `ado_create_work_item` 保留、默认关闭，MCP 页二次确认后打开，关闭时不在工具列表；4 新名字 `toolbox_ado`/`toolbox_figma` 与旧注册并存，`ai.analysis.mcp_source` 默认 `legacy`，用户自检后手动切换、可切回；5 变更策略基线显式按钮一次性从旧仓库 `config/ai_change_policy.yaml` 只读导入，再叠加 `imported.ai`，编辑界面仍推迟；6 Lark 令牌沿用 lark-mcp 全局存储（A），所有权 = 谁在运行进程；7 不移植 Bearer 注入，新端不写 `~/.claude*`、`~/.codex`、`~/.gemini`；8 令牌状态只用登录时间 + 日志刷新/20038 标记推断，不读 lark-mcp Keychain、不解密 `storage.json`；9 优先已装 Node，npm 包按仓库锁文件显式“安装运行组件”，Node 下载校验 SHA256，运行时不联网；10 TG 主 Bot MCP 菜单只做 owner 状态查看 + Lark 启停；11 S6 验收通过后按步骤另行授权切换 Lark，不改旧应用代码。
- 本确认解除派工门禁；**不**授权 Lark 所有权切换、真实 ADO/Figma/Lark 调用、读取真实配置/凭据/CLI 配置/lark-mcp 存储、修改旧应用，也不授权真实验收清单（均另行授权）。
- 派工顺序：S6-0（主控）→ S6-A（codex `gpt-6.1-sol` / medium）→ S6-B（同会话续接）；S6-C（agy `gemini-3.8-flash-high`，`--sandbox`）在 S6-A 契约冻结后可与 S6-B 并行；最后 S6 集成验收。
- lead 模型（用户 2026-10-26 偏好）：S6-0 与 S6 集成验收的安全核对用 Opus；S6-A/B/C 派工、集成与常规验收可由 Sonnet 担任 lead。
