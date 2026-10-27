# toolbox-backend (S0 / S1 / S2 / S3 / S4-A)

TOOLBOX next 的本地后端进程：FastAPI + uvicorn，Python >= 3.14，uv 管理依赖（`uv.lock` 入库）。
接口合同见仓库 `docs/modernization/archive/work-packages/` 下 S0–S5 各文件（含 S1.md「S1-A 主控裁决」）；当前切片在 `docs/modernization/WORK_PACKAGES.md`。

## 分层

`src/toolbox_backend/`：`api/`（路由、WS、安全中间件）、`services/`（事件总线、系统服务）、
`domain/`（Pydantic 数据/事件模型）、`adapters/`（store、只读旧配置、凭据、ADO HTTP、stdin）。
`services/settings.py` 是设置变更的唯一写入所有者。
`server.py` 为进程入口，`contracts.py` 为契约生成器。

## 运行

```sh
cd next/backend
.venv/bin/python -m toolbox_backend --help
```

使用已同步的 `.venv`，运行无需联网或写 uv 缓存。生产启动命令为
`.venv/bin/python -m toolbox_backend`。开发时必须隔离目录和凭据，例如在 `next/backend` 内：

```sh
TOOLBOX_LEGACY_CONFIG_DIR="$PWD/tests/fixtures/legacy" TOOLBOX_CREDENTIALS=memory \
  .venv/bin/python -m toolbox_backend --dev --data-dir /tmp/toolbox-next-demo
```

| 配置 | 默认值 / 规则 |
| --- | --- |
| `--data-dir` / `TOOLBOX_DATA_DIR` | CLI 优先于环境变量；默认 `~/Library/Application Support/toolbox-next/` |
| `TOOLBOX_LEGACY_CONFIG_DIR` | 默认 `~/.config/my-own-script/`；开发/测试指定假旧配置目录 |
| `TOOLBOX_CREDENTIALS` | 默认 `keyring`；`memory` 仅在 `--dev` 下允许，否则启动失败；内存值不持久化 |
| `TOOLBOX_DEV_FAKE_CREDENTIALS` | 指向 `{"legacy": {account: 值}, "current": {account: 值}}` 的 JSON 文件，分别预置旧/新内存凭据；**仅 `--dev` 且 `TOOLBOX_CREDENTIALS=memory` 时接受**，否则启动失败；仓库样例 `tests/fixtures/dev-credentials.json`（全为明显假值），`pnpm dev:web` 使用 |
| `TOOLBOX_DEV_FAKE_ADO` | 虚构 ADO fixture 目录（含 `fixture.json`），仅 `--dev` 且 `TOOLBOX_CREDENTIALS=memory` 时接受；用进程内 MockTransport 替换出站，不监听假 ADO 端口 |
| `--dev` | 允许 Vite 的两个本机 Origin；不会自动替换生产凭据后端或目录 |
| `TOOLBOX_HEARTBEAT_INTERVAL_S` | 默认 5 秒，用于测试缩短心跳间隔 |

- 只绑 `127.0.0.1`，端口自行 `bind(("127.0.0.1", 0))`，无监听地址选项。
- 服务开始接受连接后 stdout 只打印一行 `TOOLBOX_READY {"v":1,"port":..,"token":"..","pid":..}`；
  之后 stdout 无输出，日志走 stderr 且脱敏 token。
- 退出：stdin EOF、SIGTERM、SIGINT 均协调退出，退出码 0；启动失败非 0 且不打印 READY。
- 测试钩子：环境变量 `TOOLBOX_HEARTBEAT_INTERVAL_S`（默认 5）缩短心跳间隔。
  进程内可通过 `Settings(heartbeat_interval_s=..., ws_auth_timeout_s=..., ws_queue_size=...)` 注入。
- 手动试用（token 在 READY 行里）：
  `curl -H "Authorization: Bearer <token>" http://127.0.0.1:<port>/health`

## S2 虚构 ADO 联调

在上述开发命令基础上，同时设置 `TOOLBOX_DEV_FAKE_CREDENTIALS=$PWD/tests/fixtures/dev-credentials.json`
和 `TOOLBOX_DEV_FAKE_ADO=$PWD/tests/fixtures/fake-ado`。保持 `TOOLBOX_CREDENTIALS=memory`、
`--dev`，数据目录使用独立临时目录；在设置页预览并执行导入虚构旧配置，然后选择示例项目。
fixture 全部为虚构数据：101/102 两张工单、同源 PNG、跨源图片占位、附件、子项、评论与历史。
媒体同源 URL 使用 `/tfs/…` 相对路径，兼容虚构 library 的 http/https origin。
非法 fake 模式在监听端口之前失败；正常开发后端仍按 S0 监听随机回环端口。

## store 与凭据

- 新 store 为 `<data-dir>/config.json`，schema v2；目录 0700，文件、锁及导入快照 0600。
  新 Keychain service 为 `toolbox-next`，account 为 `ado_pat:<library_id>`。
  旧 service `my-own-script` 只有只读适配器，S1 只读取 ADO PAT。
- 普通读取不创建文件、不迁移。文件不存在时返回内存中的空配置（revision 0）。
  写入在线程中执行：进程内锁（最多等待 5 秒）→ flock（最多等待 5 秒）→ 重读 → 比较 revision → 副本变更与完整校验
  → 同目录临时文件 flush/fsync → `os.replace` → fsync 目录 → 释放锁 → `settings.changed {revision}`。
  每次成功提交 revision +1；旧 revision 返回 409 `revision_conflict`。replace 是提交点，替换后的异常会核验已提交内容。
- 启动时显式调用 `ConfigStore.initialize()`；生产注册 v1→v2 的 Telegram 迁移。
  测试或后续版本可注入 `{from_version: step_fn}`；每个纯函数接收独立字典，返回 schema_version +1 的字典。
  迁移持有同一进程锁和 flock，重读后校验完整迁移结果，先把原文字节写为
  `migrations/config-v1-<时间戳>*.json`（v1）并 fsync，再原子替换；迁移提交 revision +1。
  测试注入的 v0 迁移仍用 `config.json.bak-v0-*`。
  替换前失败保留原件及已经完成的备份；未完成的备份和临时文件会清理。
- 未注册的低版本、高版本、JSON/模型损坏、迁移失败均暴露只读错误态；不自动重置原件。
  设置接口显示错误及数据目录，写接口返回 503 `store_unavailable`。
- PAT 只写不读回，存储索引只有来源、引用、状态、更新时间。Keychain 失败不会伪装为“不存在”。
  删除 library 先提交配置删除和 pending_delete，再删除新凭据；删除失败保留索引供凭据页重试。
  被任务引用的 library/project 不允许删除。

## 一次性导入

只读取旧目录中的 `ui_settings.yaml`、`tasks.yaml`、`lark_settings.yaml`、`figma_settings.yaml`；
每个文件最多 1 MiB，使用 `yaml.safe_load`，拒绝目录外符号链接。运行状态和缓存不导入。

1. `POST /api/settings/import/preview` 不写任何文件或凭据；返回源指纹、摘要、警告和阻断错误。
   原始 `tasks` 键存在（包括 `[]`）即保留其意图；缺失时才从非空 flows 生成任务并映射 ACL 引用。
   `flows` 原样保留，非 S1 配置及未知顶层键保留到 imported 段。
2. 执行请求携带 fingerprint；在锁内重新核对。源变化时不写 config.json、导入快照或新凭据；
   允许提前创建基础设施目录和 config.lock。仅在配置为空且状态 none/failed 时允许执行。
3. 锁外读取旧 PAT 到内存，锁内重读源文件并核对指纹；先提交 in_progress 和计划 account，
   再将内存中的 PAT 写入新 service，记录已写 account。
   最后复制四个文件的原文快照，并一次提交 ado/tasks/imported/凭据索引及 completed。
4. 凭据、快照或最终提交失败时保留已写的新凭据，配置保持空，记录 failed，支持重试。
   快照复制失败会清理不完整目录；最终提交失败会删除本次快照。进程中断遗留 in_progress 时，启动将其转为 failed，
   保留写入意图供重试或清理。若故障同时令错误状态写入失败，则保留磁盘上的状态，不能保证即时落盘 failed。
5. none/failed 可跳过为 declined，不要求配置仍为空；failed 放弃时先删除已记录的新凭据再提交 declined。
   失败导入中尚未进入索引的新凭据以 orphan 显示，可在凭据页删除。
   completed/declined 为终态，不提供再次导入。任何路径均不回写旧目录或修改旧 Keychain 条目。

## HTTP 与安全边界

全部 HTTP 路由经过 Host → CORS → Bearer → BodyLimit；默认请求体上限 64 KiB，含分块累计限制。
WS 必须带允许的 Origin，随后通过首帧 token 认证。CORS 方法恰好为 GET、POST、PUT、PATCH、DELETE、OPTIONS。

PAT 输入长度为 8–1024；短于 8 的旧值不会登记到脱敏器。
S1 ADO 请求在锁内取得同一快照的 library/PAT，释放锁后发送；collection/project 拒绝点路径段，
最终请求路径必须在 base_url 路径下。不跟随重定向，总时长截止 10 秒（响应流逐块检查）/连接 5 秒，
响应最多读取 1 MiB。修改 origin 且已有 PAT 时必须替换 PAT 或显式 keep_pat。
候选 PAT 测试不保存；响应、错误、事件和日志不返回 PAT 或远端响应原文。
远端项目列表成功返回最多 500 个 `{name}`；非法参数返回 422 `validation_error`，无 PAT 返回
409 `no_credential`，出站失败返回 502 `ado_request_failed`，detail 包含测试连接同一分类集合的 category 和脱敏 message。

## S2 工单与媒体

- `GET /api/work-items/columns` 返回固定五列；列表 `GET /api/work-items?project_id=&column=`
  只查当前列，WIQL `$top=500`，每批 ≤200 项，不带 relations；含 `truncated`/`omitted`。
- `GET /api/work-items/{id}` 及 `/{id}/comments`、`/{id}/updates`、`/{id}/children`
  接收 store 中的 `project_id`；工单 id 为 1..2147483647。详情返回网页地址、清洗后 HTML、
  关系摘要和不透明媒体 id，不返回原始 fields/relations 或附件 URL。评论和历史各 ≤100 项；
  子项按 BFS 最深 8 层、最多 500 项、环去重。
- `adapters/ado_read.py` 是 S1/S2 的同一出站实现；S1 兼容入口保留 10 秒/1 MiB/既有分类。
  S2 JSON 总时长 15 秒、4 MiB；媒体 30 秒，图片 10 MiB/附件 25 MiB；连接最多 5 秒。
  进程级并发 6，排队超过 15 秒返回 503 `busy`。响应和客户端由上下文关闭；取消请求时等待线程关闭再归还并发许可。
- 媒体登记表只在事件循环内操作：随机 128 bit id、同 project/URL 复用、登记起 TTL 30 分钟、
  最多 4096 项，按登记顺序淘汰。媒体字节与工单 JSON 均不缓存、不落盘。取媒体时重新核对
  project/library、来源与路径前缀以及 PAT；已过期返回 404 `media_expired`。
- `GET /api/work-items/media/{media_id}` 不接受任意 URL。首跳和每次重定向均检查所属 library
  的 origin 与 base 路径前缀，最多 5 跳；跨源、降级、userinfo、路径越界立即终止，目标零请求。
  图片仅接受 PNG/JPEG/GIF/WebP/BMP 魔数，其他返回 415 `unsupported_media`；附件强制下载、
  文件名清理并编码。成功响应都有 nosniff、sandbox CSP、private/no-store 三项头。
- HTML 经 nh3 HTML5 解析和白名单清洗；图片仅保留后端生成的 `data-media-id` 或来源占位。
  禁止 style/src/srcset/on* 等属性；单字段原文 >1 MiB 标记 `omitted: too_large`。
  Updates 字段转纯文本并截断到 2000 字符。前端仍须按 S2-B 做第二次清洗和 blob 生命周期管理。
- `POST/PATCH/DELETE /api/ado/local-repos[/id]` 由 SettingsService 单次 store 提交，沿用 revision
  冲突规则。新/修改路径须绝对、≤1024、无控制字符与 `..` 段，仅规范化、不 resolve。
  存量条目保持可读，`GET /api/ado` 增加 `exists` 与 `warnings`，只调用 isdir、不读取目录内容。
- 全部新路由走 S0 认证；PAT 不进响应/事件/配置，远端 JSON 的凭据回显递归脱敏，包含凭据的
  媒体拒绝返回。生产日志关闭 HTTPX/httpcore 的 URL 诊断，出站失败只返回固定分类/文案。

## S3-A 任务与运行内核

- 新增 `/api/tasks` 读取、增删改、`PUT /api/tasks/order` 与预检接口；写入沿用
  SettingsService 的 ConfigStore、revision CAS 和单次提交。请求只接受表单字段；存量任务及
  git_flow/targets 中的未知字段保留，执行快照只投影已知字段。`legacy_flows` 不再生成任务。
  ACL 引用阻止删除；活动/unknown 任务及其项目、library 在同一协调边界内阻止变更。
- 生产 preflight/start 已接入 `AdoTaskExecutor`，支持同步→构建→发布、只发布、回滚。
  HTTP 不接受 executor、cwd、URL、argv、owner 或测试远端开关。
  `create_app(task_executor=..., task_git=...)` 仅为可信进程内依赖注入；临时 file 远端例外仅限下述完整 dev 假模式。
- 运行库 `<data-dir>/runs.sqlite3` 为 schema v1，WAL / FULL / foreign_keys / 5 秒 busy timeout；
  DB、WAL/SHM、runner.lock 与仓库锁为 0600，目录为 0700，拒绝符号链接 DB/锁文件。
  一个数据目录一个运行器。配置不参与伪跨库事务：锁内冻结配置，再一次事务提交 run、步骤、
  预约和首事件；成功之后才排队。四 worker，最多 100 个 queued，等待许可可取消。
- `runs/run_steps/run_effects/run_events/run_reservations` 保存七态、CAS 版本、白名单快照、
  request_id/hash、意图/回执和持久 run_seq。未知结果保留预约；重启不重发写操作。
  无意图 queued 转 cancelled，其余活动运行转 unknown。损坏/高版本库不重置；兼容历史可读，
  写入返回 `run_store_unavailable`，普通设置与工单功能继续使用配置库。
- `GET /api/runs` 使用 created_at/run_id 游标（默认 50、最多 100），`/{id}` 返回步骤/效果，
  `/{id}/events` 从 after_seq 分页（默认 200、最多 1000）。`/{id}/cancel` 幂等落盘，
  终态重复取消 200；`/{id}/reconcile` 202 只读核实。unknown 每 30 秒核实，15 分钟后
  manual_required，预约保留；无执行适配器时不会发送远端请求。
- 已认证 `/ws/events` 接收 `{type:"subscribe",topic:"run",run_id,after_seq}` 与对应
  unsubscribe。先登记，再按持久水位回放，缓冲实时增量并按 run_seq 去重；完成后发送
  `run.subscribed {run_id,last_seq}`。每连接最多 8 个 run，队列 256/4408；未订阅不收运行日志。
  envelope.seq 仍为进程序号，不能用于重连补齐。S0 已认证后的无关/垃圾帧仍忽略。
- 日志使用有界跨块行缓冲，先去终端控制码再脱敏，超长无换行输出丢弃整行并继续排空。
  每条最多 8 KiB，每 run 原始输出预算 20 MiB，预算落库并只追加一次截断提示。
  不持久化 PAT、Basic/Bearer、进程环境或任意远端响应体。

S3-B 继续使用 `domain/task_execution.py` 中的 `TaskExecutor`，不是另建运行模型：

1. `prepare(snapshot, operation, rollback_offset) -> PreparedExecution` 只读验证来源/定义/stage，
   返回有序 steps、显示 targets、资源键、冻结的制品/部署尝试信息及总预算。
2. `execute(ExecutionContext) -> ExecutionOutcome` 用 `context.operation/snapshot/deadline_at` 执行。
   设置 `step_no`，通过 `checkpoint` 保存类型化进度；每次远端写先 `intent`，可靠响应后
   `receipt`，步骤完成 `complete_step`。`current()` 可读持久步骤/效果；`log` 接受脱敏前的
   文本和可选 raw_bytes。SQLite 提交后由唯一回调广播，adapter 不直接发 WS。
3. `reconcile(context)` 只查询，不能调用 `intent`。观察结果可写本地 receipt/步骤状态，
   但不能创建、取消或部署远端资源；全部效果核实后才返回终态。不明结果继续 unknown。

`adapters/task_git.py` 使用固定 argv、隔离 Git/SSH 环境、显式 origin refs 与非强制 push；
生产只支持 `user@fqdn:path`、`ssh://user@fqdn[:port]/path` 及现有 SSH agent/known_hosts。
禁用用户 SSH 配置、代理、私钥文件/交互认证、Git 全局配置、hooks/外部 helper/driver。
HTTPS、SSH 别名、远程 PR 写均不在本版支持范围。file 远端仅由测试构造器的
`test_remote_root` 允许，路径必须位于该临时根目录内。
root/common-dir 的 flock 由监督进程和 Git 子进程继承；控制管道 EOF（含后端 SIGKILL）
会 TERM → 最多 5 秒 → KILL → wait，直到子进程退出才释放锁。不会按落盘旧 pid 回收进程。
失败只 abort 本次 merge；已 push 的分支不撤回，结束尽力恢复原 checkout，构建提交单独解析
build_branch 并与 origin 精确核对。禁止 force/reset --hard/clean/stash，也禁止操作新旧应用源码目录。

S3-A 新增无需端口的测试为 `tests/test_s3_{runs,faults,git,ws,lead_regressions}.py` 和
`tests/independent/s3a/`，自动包含在下述沙箱子集中。Git 网络测试只有临时 bare 的 file 协议；
另有 fake 进程的输出失败、锁继承与真实 SIGKILL 孤儿回收测试。真实 SSH/ADO/Keychain 与
真实端口 HTTP/WS 由主控另行验收，不能把注入执行器的结果当真实远端验收。

## 测试

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

`tests/` 为主测试（子进程测试均有超时并在 finally 回收进程）；`tests/independent/` 为独立测试者的用例。
部分测试会真实等待约 5 秒（WS 未认证 4401）。

自动夹具使用 tmp_path 数据/旧配置目录，将 keyring 替换为任何调用都记录并抛错的守卫；
子进程通过 `PYTHON_KEYRING_BACKEND=tests.guards.GuardKeyring` 使用同等守卫。
socket 守卫拦截非 127.0.0.1 连接，子进程通过测试专用 sitecustomize 安装同等守卫；会话结束断言无违规。
S1 出站请求只使用 MockTransport，测试扫描响应、日志、事件、config.json 和导入快照确保没有假 PAT。
仅修改 HOME 不能隔离 macOS Keychain。

禁止监听端口的沙箱内使用以下子集；真实 HTTP/WS/进程启动回归由主控在沙箱外执行：

```sh
.venv/bin/python -m pytest -q \
  --ignore=tests/test_http.py --ignore=tests/test_ws.py --ignore=tests/test_process.py \
  --ignore=tests/test_s1d_process.py --ignore=tests/independent/test_fault_http.py \
  --ignore=tests/independent/test_fault_ws.py --ignore=tests/independent/test_fault_lifecycle.py \
  --ignore=tests/independent/s1/test_s1_live_boundaries.py \
  --deselect=tests/test_slow_client.py::test_stalled_client_does_not_affect_fast_client_end_to_end
```

上述忽略文件内的全部 HTTP/WS/进程测试，以及被 deselect 的慢客户端端到端用例，均交主控沙箱外运行。
新增 `tests/test_s2_{work_items,ado_read,sanitize_regressions}.py` 与 `tests/independent/s2a/`
均不需要端口，已包含于子集中。

S1-D 进程 stderr 用例 `tests/test_s1d_process.py::test_cr006_dev_memory_process_stderr_never_contains_pat`
需要回环端口，由主控在沙箱外运行（或沙箱外运行完整 `pytest -q`）。

## 契约生成

```sh
.venv/bin/python -m toolbox_backend.contracts          # 写 ../contracts/
.venv/bin/python -m toolbox_backend.contracts --check  # 漂移时 exit 1
```

输出 `next/contracts/openapi.json` 与 `events.schema.json`（排序键、末尾换行，确定性）。
`tests/test_contracts.py` 比对仓库内文件与当前生成结果，改了模型/路由后必须重新生成；是否提交由主控授权决定。

## 实现要点

- READY 时序：uvicorn 以已绑定 socket 服务；轮询 `server.started`（监听已创建且 lifespan 已启动）后才写 READY。
- 信号：覆盖 uvicorn 的 `capture_signals`，自行用 `loop.add_signal_handler` 置 `should_exit`，避免 uvicorn
  退出后重发信号导致非 0 退出码。stdin 监视线程直接读 fd（读 `sys.stdin` 缓冲会在解释器退出时 abort）。
- 事件：`EventHub` 进程内 `seq` 单调；hello 与订阅注册同步完成（无 await），故后续事件 seq 必大于 hello 的 seq。
  每连接队列 256，满则标记溢出，处理器以 4408 关闭；对完全不读的对端，uvicorn 的发送背压会使关闭帧
  无法送达，处理器等待 2 秒后连接被拆除（不影响其他连接）。
- WS 缺少 Origin 或不在允许列表时，握手拒绝。

## S3-B 执行与恢复

`adapters/ado_tasks.py` 实现唯一 TaskExecutor；请求使用同一 `AdoRead.request_json` 与
`services.work_items.outbound`，S1/S2/S3 合计 6 个许可。连接 5 秒、JSON 总计 15 秒/4 MiB、
排队 15 秒；不跟随 3xx、不使用远端 URL 发请求。每次请求重新取得同来源的当前凭据，
配置内部 project/library id、base URL、collection、project 全部须与冻结来源一致。
Build/Pipeline 固定 7.0；Release 定义只读 GET 先 6.0，只有 400/404 且结构化 typeKey 为
`VssVersionNotSupportedException`、`UnsupportedApiVersionException` 或
`ApiVersionNotSupportedException` 时探测 7.0。版本冻结后写请求不重试、不换版本。

预检读取全部启用目标的 Build/Release 定义和环境，按数组索引关联。只支持单 Build artifact，
核对项目/构建定义。只有全部选定 stage 唯一存在才继续；旧名称必须唯一解析为 id。
Release 创建的 `manualEnvironments` 包含定义全部环境名称；创建后再核实手动条件和未启动状态，
不满足即停止后续写，保留已经创建的 Release，等待核实。只有选定环境会收到部署 PATCH。
HTTPS Git、SSH 别名/代理、无本地路径但存在 git 规则、缺少可信 Pipeline↔Build 关联、多 artifact、
无法验证环境手动条件等返回 `unsupported_task` 或在受理后进入需要核实的运行状态。
这些拒绝不会通过切换协议、猜同 id、自动重发或修改定义来绕过。

构建复用读取可信 Build 详情，逐项核对项目、仓库、定义、分支、commit、可选队列；
只复用 notStarted/inProgress/postponed，永远 owned=false。新 Build/Pipeline 固定提交；
Pipeline 只有同来源、同项目的 `_links.build.href` 精确 Build API 路径可作为关联，
提取数字 id 后用安全 builder 重建请求。无法关联则 unknown，不能发布或猜 id 取消。
只取消持久创建 intent 和成功回执证明为本 run 创建的构建；Pipeline 取消使用已核实关联的
Build PATCH，不探测/猜测另一种取消端点。partiallySucceeded 不能发布。

只发布冻结具体成功 Build 与 commit，执行前重新核对，不换最新。回滚冻结最近六条列表中的
offset 1..5 对应 Release、Build 制品、环境 id 和 attempt；历史列表、环境身份或 attempt 变化要求重做计划。
回滚不创建 Release、不触发构建、不运行 Git。禁用目标在三种操作中均跳过。

每次 POST/PATCH 之前提交 effect intent，成功回执提交后才能继续。传输错误、坏响应、回执落盘失败
都保留不明 intent，禁止重发。恢复只 GET/本地只读 git 检查，不续写剩余步骤。
丢失的 Release 响应用精确 run/effect description 标记有限查询；Build 缺少可靠唯一关联标记时，
即使发现同 commit 的候选也不认领。环境对账要求 attempt 大于写前基线，旧 succeeded 不算成功。
有未核实/仍运行的任何相关远端操作都保留 unknown 和预约；每 30 秒后台核实，15 分钟后
manual_required 并停止自动查询，手动 reconcile 仍仅重新查询。响应丢失后的 intent 可能一直需人工核实。

CR-S3A-001：本地异常/总超时不能一律 unknown。无 effect 且检查点未记录任何 Build/Pipeline/Release
观察时，异常落 failed，总超时/关闭落 cancelled，释放预约；存在复用 owned=false Build 的观察，
即使 effects 为空也保持 unknown。DB 不可写时不伪造终态，沿用 lost worker 恢复机制。
本地子进程、锁、DB/HTTP 的释放归原有生命周期所有者；unknown 只保留数据库预约。

## S3 冻结 DTO 字段

HTTP 形状见 `../contracts/openapi.json`，WS 形状见 `../contracts/events.schema.json`。
下列字段均有具体 Pydantic 模型；`?` 表示可为 null 或有默认值。UTC 时间使用 ISO 8601 字符串。
未知配置扩展保留在 TaskView 中；StepView.checkpoint 是跨版本动态检查点容器。

| DTO | 字段及含义 |
| --- | --- |
| TaskSummary | id（任务标识）、name（显示名） |
| PlanStep | kind（git/build/release/rollback）、target_index?（配置数组索引，Git 无索引） |
| PlanTarget | target_index、name、definition_id（Build 定义）、release_definition_id、stage_ids（完整选定定义环境 id）、build_id?、commit?（只发布/回滚制品）、release_id?、created_at?（历史 Release 创建时间） |
| PlanResponse | plan_id、expires_at（5 分钟）、revision、task_summary:TaskSummary、steps:PlanStep[]、targets:PlanTarget[]、warnings:string[] |
| SourceSnapshot | project_id/library_id（内部配置身份）、base_url、collection、project（远端路径身份） |
| DefinitionIdentity | id（字符串或整数）、name? |
| ArtifactDefinition | project/definition:DefinitionIdentity；远端未知 JSON 不复制进快照 |
| ReleaseArtifact | alias、type=Build、definitionReference:ArtifactDefinition |
| FrozenTarget | PlanTarget 全部字段，另含 api_kind（build/pipeline）、api_version（6.0/7.0）、artifact:ReleaseArtifact、manual_environments（全部环境名称）、release_stage_ids/release_stage_names（配置输入）、history_ids?（冻结历史列表）、environment_ids?（历史具体环境）、deployment_attempts?（环境 id→写前 attempt） |
| PreparedSnapshot | targets:FrozenTarget[]、commit?（无本地 Git 的主路径提交） |
| TaskSnapshot | TaskFields 的全部白名单字段，另含 id、source?:SourceSnapshot、prepared?:PreparedSnapshot；未知配置字段不执行、不复制 |
| TaskFields | enabled、sort_order、tg_command、tg_desc、name、project_id?、local_repo_path、repo_id?、repo_name?、git_flow:FlowInput、agent_queue_id?、agent_queue_name?、targets:TargetInput[] |
| FlowInput / MergeInput | build_branch、update_branches、merges（每项 source/target）、push_branches；均保留数组顺序 |
| TargetInput | name、enabled、build_kind?、build_id?、build_name?、release_id?、release_name?、release_stage_ids、release_stage_names |
| LastRunSummary | run_id、status（七态枚举）、operation（三操作）、created_at、finished_at?；该任务按 created_at/run_id 最新的一次运行，包含活动运行 |
| TaskValidation / TaskView | valid；TaskView 为任务已知字段及未知保留字段，另有 warnings、validation、active_run_id?、last_run?:LastRunSummary；无运行或运行库不可用时为 null |
| TaskListResponse / TaskResponse | revision + items:TaskView[] / item:TaskView |
| StartResponse | run_id |
| StepView | run_id、step_no、kind、target_index?、status、started_at?、finished_at?、checkpoint（动态 JSON） |
| EffectIntent | kind、api_kind?、branch?、commit?、previous_remote_commit?、definition_id?、queue_id?、repo_id?、ref_name?、source_version?、build_id?、pipeline_run_id?、release_definition_id?、release_id?、environment_id?、baseline_attempt?、api_version?、description?、manual_environments?；只保存受限写意图，非任意请求体 |
| EffectView | effect_id、run_id、step_no、kind、intent_key、intent:EffectIntent、state、remote_id?、owned、intent_at、confirmed_at?、error_category? |
| RunResponse | store_error?、run_id、task_id、operation、status、phase、reason_code?、created_at/started_at?/updated_at/finished_at?、config_revision、task_snapshot:TaskSnapshot、request_id/request_hash（幂等）、cancel_requested_at?、stop_reason?、deadline_at、last_seq、log_bytes、state_version（CAS）、recovery_state、summary、steps:StepView[]、effects:EffectView[] |
| RunListResponse / RunEventsResponse | items:RunResponse[] + cursor?；items:RunEventData[] + next_seq + has_more |
| StatePayload | status、reason_code?、updated_at?/started_at?/finished_at?、summary?、recovery_state?、stop_reason? |
| LogPayload | text（纯文本、已脱敏） |
| ReceiptPayload / StepFinishedPayload | remote_id? + owned；status（步骤结束状态） |
| CheckpointPayload | step_no、kind（checkpoint/intent/receipt/step_finished）、data（JournalCheckpoint/EffectIntent/ReceiptPayload/StepFinishedPayload） |
| JournalCheckpoint | kind、root?/common_dir?/lock_keys?、original_head?/original_branch?/original_refs?/new_refs?、expected_commit?、repo_needs_attention?、target_index?、definition_id?/queue_id?/repo_id?/branch?/commit?/api_version?/deadline_at?、build_id?/pipeline_run_id?/release_definition_id?/release_id?/stage_ids?/deployment_attempts?/owned?/result?；Git refs、远端观察和恢复证据 |
| RunEventData | run_id、run_seq（持久序号）、type（state/log/checkpoint）、payload（StatePayload/LogPayload/CheckpointPayload） |
| RunEvent / RunSubscribedData / RunSubscribedEvent | RunEvent 为 seq/topic=run/ts/type=run.event/data:RunEventData；订阅回执 data 为 run_id/last_seq，type=run.subscribed，其余 envelope 相同 |

运行七态：queued、running、cancelling、cancelled、succeeded、failed、unknown。
只有 cancelled/succeeded/failed 为不可变终态。步骤态：pending、running、succeeded、failed、skipped、unknown。
效果态：intent、confirmed、rejected、unknown。恢复态：none、pending、reconciled、manual_required。
operation：sync_build_release、deploy_only、rollback；stop_reason：user、timeout、shutdown。

S3 HTTP 错误 code：validation_error（422）；not_found（404）；revision_conflict、task_active、resource_active、
task_referenced、idempotency_conflict、plan_expired、plan_changed、no_credential、unsafe_repository、unsupported_task（409）；
busy、run_store_unavailable、store_unavailable（503）；ado_request_failed（502）。ADO category 沿用
no_credential/unauthorized/forbidden/not_found/redirect/timeout/tls/network/bad_response/too_large。
内部一致性拒绝还可能为 invalid_transition、state_conflict、effect_already_recorded（409）。
运行 reason_code 包括 git_failed、repo_needs_attention、plan_changed、build_failed、release_failed、remote_failed、
remote_running、remote_unknown、local_failed、interrupted、timeout、cancelled、busy、backend_restart、worker_lost；
错误正文不包含远端响应原文或凭据，前端显示 summary 和实际状态，不据 reason 推测成功。

## S3 dev 假任务启动器约定

保持原有 `--dev`、`TOOLBOX_CREDENTIALS=memory`、`TOOLBOX_DEV_FAKE_ADO` 三重门。
新增 `TOOLBOX_DEV_TASK_ROOT`：启动器先在系统临时目录创建**空的独立目录**，把绝对路径传给后端。
缺少任一门、路径非临时/非空/符号链接时启动失败；非 dev 不能打开 file 协议。
假数据 fixture 为 `tests/fixtures/fake-ado/tasks.json`，ADO handler 为有状态进程内 MockTransport。
此模式要求全新隔离 data-dir；直接播种虚构 library/project、内存假 PAT 与四个任务并将导入状态设为 declined。
未设置 TASK_ROOT 时仍保留原有工单导入演示，不播种任务、不允许生产 Git file 协议。

启动器应设置（路径均绝对、由启动器解析，无 shell 展开依赖）：

| 设置 | 值 |
| --- | --- |
| CLI | `--dev --data-dir <本次新建数据目录>` |
| TOOLBOX_CREDENTIALS | memory |
| TOOLBOX_LEGACY_CONFIG_DIR | 仓库 `tests/fixtures/legacy` 的绝对路径，或启动器另建的空旧配置目录 |
| TOOLBOX_DEV_FAKE_ADO | 仓库 `tests/fixtures/fake-ado` 的绝对路径（含 fixture.json 与 tasks.json） |
| TOOLBOX_DEV_TASK_ROOT | 启动器在系统临时目录创建的空目录 |

后端在 TASK_ROOT 下创建 remote.git（bare）与 clone，使用隔离 Git 环境和仅 file 协议，
播种一个提交，并将其 commit 注入假 ADO。四任务：同步成功、只发布失败、回滚需核实、已停用。
建议演示操作依名称选择，回滚 offset=1；三个正常启用任务也可调用其它操作，定义 11/12/13
分别提供成功/失败/部署送达后丢响应并仍运行的场景。只有所选环境部署；未选环境保持原状。

清理责任：启动器关闭本次后端 stdin 并等待退出后，删除本次 TASK_ROOT 和 data-dir；
后端负责每个 Git 子进程 TERM/KILL/wait、管道与锁回收，不删除启动器目录。
后端重启演示应保留 data-dir 并**不再次设置 TASK_ROOT**，避免重播种；旧运行只读核实，
内存远端服务重置意味着可能无法核实旧资源，按 unknown/manual_required 展示。
前端 `dev-web.mjs` 接线属于 S3-C，本包没有改它。

离线验证覆盖 S3-B `tests/test_s3b_*.py` 与 `tests/independent/s3b/`。
真实自建 ADO 对 Release manualEnvironments、Pipeline 显式 Build link、部署 attempt 的返回兼容性，
以及真实 SSH/Keychain/回环端口/Tauri 需主控或用户另行验收；内存假服务通过不代表真实服务器已验证。

### S3 运行读取扩展（2026-10-23 已批准）

`GET /api/runs` 新增 `order=asc|desc`，默认 asc，保留原有 created_at/run_id 旧到新顺序；
desc 使用两字段同时降序，新到旧翻页。task_id/status 过滤与 limit（默认50、最大100）规则不变。
游标与方向绑定：asc 继续输出原两字段 JSON 数组 `[created_at, run_id]`；
desc 输出 `["desc", created_at, run_id]`，下一页使用严格小于该二元组的记录。
asc 游标用于 desc、desc 游标用于 asc、非法 order/游标均返回 422 `validation_error`。
同一 created_at 以 run_id 决定顺序，避免同时间记录翻页重复或遗漏。

任务列表与单任务详情均返回 `last_run: LastRunSummary | null`，以创建时间而非完成时间判断最近一次，
同时间按 run_id 降序；包含 queued/running/cancelling/unknown。配置任务无运行时为 null。
一次参数化 SQL 批量取得所有任务的最新摘要与活动 id，不逐任务查询或加载全部 run 详情。
运行库不可用、已关闭或只读时，last_run 为 null，沿用运行库不可用 warnings 降级，任务配置仍可读取。
所有读取沿用既有 S0 Bearer/Host/CORS 边界；没有新增身份或 ACL 语义。


## S4-A Telegram 基础

Bot Token 仅存新 Keychain service `toolbox-next` / account `telegram_bot_token`，元数据
kind=`telegram_bot`，与 S1 凭据页共用索引。PUT 仅写入，格式为数字 5–16 位、冒号、
30–64 位字母数字或下划线/连字符；不测试候选 Token。显式 import-legacy 只读取旧
`my-own-script` / `telegram_bot_token`，不改旧条目，不访问 `ai_bot_token:*`。
启用时不能改删 Token；旧 Token 缺失为 **404 legacy_missing**。

配置 schema v1→v2 和 S1 直接导入共用规范化函数：`imported.telegram` 被移到类型化顶层
`telegram` 并移除旧键；control/owner/notify/ACL 内未知字段保留；成员补 UUID4 id。
生成的成员 UUID 每次独立迁移不同，除此之外两条路径的规范化结果一致。
迁移一律 enabled=false，不读取凭据、不联网；先写 0600 的迁移前原文快照，再原子替换。
失败不落半文件，再启动不重复迁移。旧 ACL 无效/重复/超限条目保留并警告，不授予权限。
删除任务默认保留 409 task_referenced；`detach_acl=true` 在同一次配置更新中解除所有引用，
不改组权限位、不删成员；空组附“该组已无可运行任务”警告。

`telegram.sqlite3` user_version=1，含 tg_bots/tg_updates/tg_actions/tg_outbox；
runs.sqlite3 单事务迁移到 user_version=2，origin_json 与 run 创建同事务。
旧 run 默认 `{kind:ui}`；内部 Telegram 来源包含 bot/chat/user 和动作身份，但 HTTP RunResponse
只显示 `origin.kind`。HTTP StartRequest 拒绝 origin。未知高版本/损坏/符号链接不重置；
Telegram 库故障返回只读错误态，其余设置/任务功能继续使用原有服务。
**回退旧后端会拒绝 config v2 / runs v2，不自动降级或删除数据；人工恢复须用迁移快照。**

TelegramService 是生命周期唯一所有者。enable 必填 ack_old_bot_stopped，先 getMe、
getWebhookInfo；已有 webhook 不自动删除，只有显式 delete_webhook 才调用 deleteWebhook，
且 drop_pending_updates=false。首次 getUpdates(offset=-1,timeout=0) 丢弃积压，之后
轮询 timeout=25/limit=100；每条 update 在同一事务登记并推进 offset，再交给两个处理 worker
（队列 64、同 chat 串行）。登记后崩溃不重放指令，用户需重发；同批单条失败不阻塞其余条目。
超过 5 分钟的已授权指令只回复一次过期。首次基线 409 后保留已确认的 enabled 状态，
HTTP 返回 502 telegram_request_failed/category=conflict；GET 状态可见 conflict，可单次 retry。

轮询状态：disabled → starting → polling ⇄ backoff；409 立即 conflict 并停止，不删 webhook、
不自动重试；401/404 为 token_invalid；已有 webhook 为 webhook_set；库错误为 store_unavailable。
retry 仅 conflict/backoff，做一次 timeout=0 探测；429 遵守 retry_after，网络退避
1/2/5/10/30/60 秒（抖动，上限 60）。disable/shutdown 取消长轮询、发送与在途处理器，最多
等待 5 秒后隔离未完成处理器，完成自身客户端/数据库清理；已提交的 S3 run 不被 Telegram 停用取消。

Bot API 唯一客户端固定 `https://api.telegram.org`，不跟随重定向；仅这个客户端 trust_env=True，
遵循环境/macOS 代理。独立并发为轮询 1、发送 2、媒体 1；响应限额分别为 1 MiB/64 KiB。
错误固定 category：network/timeout/http_4xx/http_5xx/conflict/unauthorized/rate_limited/bad_response，
description 脱敏、去 URL、最多 200 字；不会保留 httpx 的 URL 异常上下文。

ACL 顺序：私聊 owner → chat_id 成员 → 私聊 username 成员（首次绑定 user_id，之后只认
user_id）→ 旧白名单（status）→ none。空 owner 不自动绑定，只认设置页签发的 6 位码 /bind；
码仅在内存、10 分钟、同时一个、错 5 次作废。none 零回复；非 owner status 只列组内任务
或自己触发的运行。/help、/start、/menu 使用服务端一次性菜单令牌（TTL 5 分钟，
每 bot 活动≤256、每 chat≤16）；伪造/跨主体令牌无效果，过期动作提示重新操作。
/status 与 /bind 可用，执行类与 /wi 流程见下方 S4-B；服务/VPN/MCP/AI 回复“该功能尚未迁移到新应用”。

发件箱只在 control.enabled 时接收运行通知，入箱与停用协调；UI 通知给 owner（可关闭），
Telegram 通知给触发 chat 并绑定原 bot。run/status 去重；同一状态不重复；重启扫描 enabled_at
之后持久状态事件补齐提交后入箱前的崩溃缺口。默认摘要不含 stderr/日志/URL/远端 id；
include_details 加分支、目标数/名称、完成步骤、已知构建/Release 标识；网页链接仅由冻结来源
与当前同来源配置重建并经 S2 within 校验，不复制远端 URL、不编造未知 Release 名。
正文统一脱敏，命中已登记凭据则用固定隐藏文本替换。纯文本、每块最多 4000 字，无 parse_mode。
成功清空正文；连接建立失败/429 最多尝试 5 次、累计等待不超过 10 分钟；读超时/断链/5xx
为 unknown 不重发，400/403 为 failed。重启 sending→unknown，pending 按 next_attempt_at 续发；
pending 最多 500，优先回复，超限丢最旧通知；没有可丢通知时拒绝新入箱 busy。

### S4-A DTO 与接口

字段的确定类型以 `../contracts/openapi.json`、`events.schema.json` 为准，全部由 Pydantic 生成。

| DTO | 用途 |
| --- | --- |
| TelegramView / Control / BotView / CredentialView / OwnerView / Notify / PollerView / ACLView | revision、开关、凭据有无/来源、bot 身份、owner、通知、轮询和保留旧条目的 ACL 警告 |
| RevisionRequest / TokenRequest / EnableRequest / TelegramSettingsRequest / NotifyPatch | 带 revision 的配置/Token/接管/通知输入；Token 为 SecretStr |
| GroupCreate / GroupPatch / MemberCreate / MemberPatch / WhitelistRequest | ACL CRUD 输入，服务端生成新 id，成员 user_id 不由 HTTP 指定 |
| BindCodeResponse / ActivityResponse / ActivityItem | 一次性绑定码、无正文的处理记录（默认 50、最多 200） |
| TelegramStatusData / TelegramStatusEvent | WS telegram.status，复用 system envelope，不新增订阅主题 |
| OriginView | RunResponse.origin.kind，只读来源 |
| TelegramErrorResponse / TelegramErrorDetail | 固定错误码/category，不回显输入/Token/webhook URL |
| InjectRequest / FakeSentResponse / FakeSentItem | 仅 dev 假 Bot 路由 |

路由均经过既有 Host/CORS/Bearer/BodyLimit：GET /api/telegram；PUT/DELETE /token、
POST /token/import-legacy；POST /control/enable、/disable、/retry；POST /owner/bind-code、
DELETE /owner；PATCH /settings；POST/PATCH/DELETE /acl/groups[/{id}] 与 /acl/members[/{id}]；
PUT /acl/legacy-whitelist；POST /test-message；GET /activity。以上省略前缀 /api/telegram。
DELETE 使用 query revision；POST/PATCH/PUT 使用 DTO 中的 revision，test-message/bind-code 也带 revision。
任务删除新增 query detach_acl。ACL 组删除级联其成员，不更改其他组。
新增错误码：409 telegram_active/ack_required/webhook_set/owner_not_bound；404 legacy_missing；
502 telegram_request_failed（category 如上）；503 telegram_store_unavailable。沿用
validation_error/revision_conflict/no_credential/credential_backend_error/store_unavailable/store_busy/busy/not_found。

### Dev 假 Telegram

只能在 --dev + TOOLBOX_CREDENTIALS=memory + TOOLBOX_DEV_FAKE_TELEGRAM=1 下开启，
否则在监听前启动失败。使用进程内 httpx.MockTransport，无真实 Telegram 连接；此模式不自动
读取/播种真实配置或 Token。示例（先自行创建独立的临时 data-dir 与空 legacy-dir）：

```sh
TOOLBOX_CREDENTIALS=memory TOOLBOX_DEV_FAKE_TELEGRAM=1 \
TOOLBOX_LEGACY_CONFIG_DIR=/tmp/toolbox-fake-legacy \
.venv/bin/python -m toolbox_backend --dev --data-dir /tmp/toolbox-fake-telegram
```

用 Token PUT 录入明显假值 `123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef`，再带确认 enable。
设置页生成 bind-code 后，POST /api/dev/telegram/inject，输入 `{update:{update_id:1,message:{
chat:{id:6001,type:"private"},from:{id:6001},date:<当前Unix秒>,text:"/bind <绑定码>"}}}`；
随后注入 /help 或 /status。GET /api/dev/telegram/sent 返回 `{items:[{method,payload}]}`。
仅此模式注册这两个路由，正常模式两者均 404；它们同样需要 S0 Bearer/Host 校验。
发送记录最多 500 条。开发启动器负责关闭 stdin、等待退出并删除其临时目录；不要使用真实配置目录。

S4-A 新用例位于 tests/test_s4a_*.py 与 tests/independent/s4a/，只用 tmp_path、MemoryCredentials、
MockTransport 和既有 keyring/socket 守卫。真实 Bot、系统代理、Keychain 与端口 HTTP/WS
需主控或用户另行验收；沙箱内的无端口通过不等于这些环境已验证。

## S4-B Telegram 执行与工单

本包只增加 Bot 指令与内部服务调用；沿用 S4-A HTTP/WS DTO、路由、错误码和 SQLite schema，
`contracts --check` 必须与冻结的 b64dd65 契约一致。HTTP start 仍不接受 origin；Bot 运行来源
与 run 同事务持久化，HTTP 只公开 origin.kind。Bot 不执行任意命令、callback 参数或远端 URL。

### 指令与确认

- `/<tg_command>`、`/run <tg_command>`，或 `/help` → 任务：选择任务后选择“构建发布”或
  “仅发布”，调用既有 RunService.preflight。计划展示任务、仓库、分支、各目标 definition/stage、
  仅发布的精确 Build/commit 与警告；只有“确认执行”调用 RunService.start，“取消”作废对应确认。
- `/rollback`：选择任务 → offset 1..5 → 对该 offset 预检 → 展示各目标冻结的历史 Release
  ID、名称、创建时间、当前环境结果与精确制品 → 确认执行。展示读取只使用冻结 Release ID。
- 确认后回复“已开始（运行 #短id）”。request_id 为 `uuid5(TG_NAMESPACE, action_token)`，
  ack_old_app_idle=true，origin=telegram；执行、预约、幂等、超时与恢复全部复用 S3。
  同一确认重复点击不会创建第二个 run；结果已登记时返回原 run，否则提示已处理。
- plan/token 过期回复“计划已过期，请重新预检”及“重新预检”按钮，必须重新点击并确认，
  不自动预检或启动。任务禁用、删除、配置变化或权限收回均阻止旧确认启动。
- `/stop` 列出当前可停的活动/unknown 运行，点选调用幂等 cancel。固定提示
  “停止不会回滚已部署内容；远端可能继续”；unknown 另提示“结果需要核实”。
- `/status` 延续 S4-A 可见范围。系统操作保留“尚未迁移”提示，不显示服务、VPN、MCP、AI 入口。

动作令牌由服务端生成：16 个随机字节的 base64url（22 字符），绑定 bot/chat/user，TTL 最长
5 分钟；确认令牌同时受 plan 到期时间限制。单事务消费一次，消费后重新解析 ACL；最终
start/cancel 在 ConfigStore 单写锁内再次授权，防止权限撤回与接受运行之间的竞态。
每 Bot 活动令牌≤256，每 chat≤16，超限淘汰最旧未消费项；任务、项目、运行与关联项选择器
每页最多 8 项并提供翻页，避免当前页生成超过上限的按钮。随机、跨 bot/chat/user 或旧式
`runmode:build:<id>` 回调不触发执行。令牌和参数不来自客户端拼接，SQL 使用绑定参数。

| 操作 | owner（仅私聊） | ACL 成员 | legacy / none |
| --- | --- | --- | --- |
| 构建发布、仅发布 | 全部有效任务 | can_run 且 task_ids 包含任务 | 不允许 |
| 回滚 | 全部有效任务 | can_rollback 且 task_ids 包含任务 | 不允许 |
| 停止 | 全部可停运行 | can_stop 且持久 origin.kind=telegram、origin.chat_id=当前 chat | 不允许 |
| 状态 | 全部 | can_status；组内任务或自己触发的运行 | legacy 只读状态；none 零回复 |
| 工单 | 允许 | 不允许 | 不允许 |

菜单“任务”只对 owner 或拥有 can_run/can_rollback 的组显示；只有回滚权限的组进入任务后
只提供回滚。非 owner 的停止归属使用数据库来源，重启后仍按同一规则授权。

### /wi 只读浏览与图片

`/wi` 选择已存项目 → 新建/待开发/开发中/测试/已关闭 → 列表（8 条/页）→ 详情。
`/wi <编号>` 使用本 chat 已选项目，或当前活动/唯一项目。详情提供“全文”“关联项”；
关联项显示父子工单与 S2 关联链接标签，可分页打开父子详情。不提供 MCP 分析或复制提示词按钮。
项目/版块/页仅存内存；列表按项目、版块、配置 revision 缓存 60 秒，到期后重读，关闭时清空。
每次读取前后重新确认 owner；读取中解绑 owner 不再发送详情或错误提示。

全文只解析 S2 已清洗 HTML，转换纯文本，每块≤3900 字，不使用 parse_mode。图片只通过 S2
媒体登记表获取，沿用同源、凭据与来源变更检查，不接受 Telegram 输入的下载 URL。再按文件
签名筛选 png/jpeg/gif/webp：单张≤5 MiB、每工单最多检查前 10 个不同媒体、接受总量≤20 MiB；
越界、失效、类型或大小不符的图片跳过并注明“N 张图片未发送”。图片字节不落盘，发送后释放；
同一 worker 同时只取一张媒体，保留的合规图片总量受 20 MiB 限制，单次取图另受 S2 限额约束。
2..10 张使用 sendMediaGroup，一张使用 sendPhoto；媒体并发独立为 1。上传超时或失败不自动
重复上传，提示“图片发送失败或结果需要核实，请勿重复发送”，避免远端已收图却重复发送。

### 固定错误文案

不发送 SettingsError.detail、ADO 异常原文、git stderr 或请求 URL。未知执行错误统一
“操作失败，请稍后重试”；未知工单类别统一“工单读取失败，请稍后重试”。

| S3/内部 code | Telegram 中文 |
| --- | --- |
| task_active | 任务已有活动运行 |
| resource_active | 发布资源正被其他运行占用 |
| busy | 忙，请稍后重试 |
| no_credential | 尚未配置所需凭据 |
| unsupported_task | 该任务配置暂不支持执行 |
| run_store_unavailable | 运行数据库不可用 |
| telegram_store_unavailable | Telegram 数据库不可用 |
| store_unavailable | 配置数据库不可用 |
| plan_expired | 计划已过期，请重新预检 |
| plan_changed | 任务或来源已变化，请重新预检 |
| idempotency_conflict | 请求标识冲突，请查看运行状态 |
| not_found | 任务或运行已不存在 |
| revision_conflict | 配置已变化，请重新操作 |
| validation_error | 任务不可执行或权限已变化 |
| unsafe_repository | 仓库未通过安全检查 |
| ado_request_failed | 远端请求失败，请稍后重试 |

| /wi category（或 code） | Telegram 中文 |
| --- | --- |
| no_credential | 尚未配置 ADO 凭据 |
| unauthorized / forbidden / not_found | ADO 认证失败 / 无权读取此工单 / 工单或项目不存在 |
| timeout / network / tls | ADO 请求超时 / ADO 网络请求失败 / ADO 安全连接失败 |
| redirect / blocked_origin | ADO 请求发生重定向，已拒绝 / 已拒绝外部媒体 |
| bad_response / too_large | ADO 返回格式异常 / ADO 响应超过限额 |
| media_expired / unsupported_media | 媒体已过期，请重新打开工单 / 不支持的图片类型 |
| busy / store_unavailable | 忙，请稍后重试 / 配置数据库不可用 |

### 队列、回复与关闭

所有已登记 update 进入有界队列（并发 2、等待 64、同 chat 串行）。慢预检、工单读取和上传
均由 worker 等待，不阻塞 getUpdates 与 S3 事件入队；满时对已授权用户回复“忙，请稍后重试”，
记录该 update failed/busy，继续推进 offset。未知/未授权用户仍零回复。

回调面板优先 editMessageText；失败只将已经生成的回复退回 sendMessage，不重新预检或执行。
分块时只编辑首块，其余块新发，按钮附在最后一块。正文和按钮均在发件箱写入前扫描：按钮
命中已登记密钥、URL 编码密钥或 Bot URL/认证头脱敏规则时，整条替换为固定隐藏文本并去掉按钮，
避免敏感文字进入 DB/WAL、回复或 dev sent。通知规则与 sending→unknown 语义沿用 S4-A。

轮询/会话遇到本地非 TelegramError 时记录固定类别及异常类型，不记录异常原文，进入可由
GET/WS 观察的 backoff 或 store_unavailable。disable/shutdown 取消轮询、worker 与在途处理器，
最多等待 5 秒；相册上传随处理取消，统一关闭客户端/DB/FD，并清空 chat 锁、工单状态及缓存。
已提交的 S3 run 由 RunService 继续管理，不因 Telegram 停用被取消。

S2 `outbound()` 保持原有语义：调用方取消后仍等待读取线程，直到同步 HTTP 客户端关闭才
归还共享 6 许可。卡在此只读读取上的 Telegram 处理器在 5 秒后标记 detached，关闭流程停止
等待它们。每处理器的上下文标记阻止迟到结果发送消息、写 Telegram 数据库、操作已关闭客户端，
也不会因重新启用而恢复；结果和异常都被收取丢弃，关闭时最多记一条固定类别
`detached_after_close`，不记录异常原文。完成后移除 detached 跟踪及上下文，不留下未处理异常。
其 S2 许可在线程实际结束后归还，不提前释放。后端进程退出可能因此延迟到 S2 既有 JSON/媒体
15/30 秒读取预算；只读读取无副作用，此延迟按主控修订合同接受。lifespan 先关闭 RunService，
再关闭 TelegramService，因此 S3 停止不会排在这些读取之后。重试接管探测到的 updates 也进入
有界工作队列，不在控制锁内等待慢读取，停用仍可及时取得控制锁。

S4-B 用例：tests/test_s4b_execution.py、test_s4b_regressions.py、test_s4b_security_lifecycle.py 与
tests/independent/s4b/；只用 tmp_path、内存凭据、MockTransport、假 ADO 和临时 bare Git。
端口测试及 test_confirmed_telegram_run_uses_only_temporary_bare_git 在 codex 沙箱记 not_run，
由主控沙箱外验收；后者已由主控确认整文件 5 passed，单用例连续 3 次 passed，不修改或跳过该用例。

## S5-A：AI 开发后端基础

本包提供终端会话；`kind=chat`、resume 输入返回 409 `unsupported_cli`，由 S5-B 接入。
不启动 MCP server、不读取 AI CLI 会话目录或 AI Bot Keychain，不实现 AI Telegram 轮询。

### 配置与迁移

config schema v2→v3 从 `imported.ai` 规范化顶层 `ai`，S1 直接导入使用同一函数。
`profiles` 含 id/name/command/upgrade_command/builtin/cli；补齐 codex、gemini（cli=agy）、
claude_code。内置配置可编辑而不可删除。`selected_profile_id`、model_presets、defaults、analysis、
bots 为类型化字段；未知字段继续保存。旧 profile 缺字段、重复 id 或命令无效时保留原值并警告，
运行入口拒绝该项；不会因为一条无效 profile 而阻止打开设置。

`targets/default_target_id/default_policy/project_overrides/require_policy_check_before_code_change/`
`allow_direct_code_change` 留在 imported.ai。迁移的所有 Bot 槽位强制 enabled=false，用户名仅显示。
默认 Claude auto/effort=null、Codex workspace-write/medium、agy sandbox；分析默认 Claude plan、
Codex read-only、agy sandbox。迁移前原文快照为 `migrations/config-v2-<时间戳>.json`（0600），
快照持久化后才原子替换配置；失败保原件、清除半文件，再启动不重复迁移。v3 不自动降级。

### DTO、路由与事件

HTTP DTO 位于 `api/ai_schemas.py`，由 Pydantic 生成 OpenAPI；错误不回显输入。

| DTO | 用途 |
| --- | --- |
| AIView / ProfileView / ResolvedCLI / AILimits | revision、profile 解析状态（仅可执行文件名）、默认档、库状态、限额与警告 |
| ProfileCreate / ProfilePatch / AISettingsPatch | profile CRUD、选择、模型预设与默认/分析档配置；写配置必须带 revision |
| SessionCreate / ResumeRequest | UUID request_id、kind、profile_id、repo_id、模型/档位、初始提示词、高权限确认 |
| SessionView / SessionList / RepoView / AIOrigin | 无 cwd 路径的会话投影、状态、结束原因、退出码、水位、资源警告 |
| AIEventsResponse / AIEventData | 规范化事件，数据中的会话序号字段为 **session_seq** |
| CheckResponse / JobResponse / AIJobData | 检测输出与退出码、升级 job、取消与进度 |
| AIEvent / AISubscribedEvent / AISessionEvent / AIJobEvent | WS ai.event / ai.subscribed / ai.session / ai.job |

所有 HTTP 路由沿用 S0 Host/CORS/Bearer/BodyLimit。无新的用户或权限主体。

| 路由 | 行为 |
| --- | --- |
| GET /api/ai | 配置与 CLI 解析状态；库故障时配置仍可读，store_state=unavailable |
| POST /api/ai/profiles；PATCH/DELETE /api/ai/profiles/{pid} | 配置增删改；DELETE 的 revision 在 query 中 |
| PATCH /api/ai/settings | 带 revision 的配置修改 |
| POST /api/ai/profiles/{pid}/check | 解析 argv[0] 后执行 --version，15 秒、脱敏输出≤4 KiB |
| POST /api/ai/profiles/{pid}/upgrade | upgrade_command 经 shlex、无 shell、监督器执行；返回 job_id |
| POST /api/ai/jobs/{jid}/cancel | 幂等取消升级；同时最多一个活动升级，最长600秒、脱敏输出≤256 KiB |
| POST/GET /api/ai/sessions | 新建终端 / 列表（state、limit≤100）；request_id 重复返回原会话 |
| GET/DELETE /api/ai/sessions/{sid} | 详情 / 仅终态可删除；删除同时清除内存终端缓冲 |
| GET /api/ai/sessions/{sid}/events | after_seq 游标，默认200条、最多1000条 |
| POST /api/ai/sessions/{sid}/interrupt | 终端写 Ctrl-C；已结束时返回当前状态 |
| POST /api/ai/sessions/{sid}/close | 幂等关闭终端及其进程组 |
| WS /ws/events | ai 主题订阅/取消订阅；每连接最多8个会话 |
| WS /api/ai/terminals/{sid}/ws | 原始 PTY 字节回放与实时输出、输入和 resize |

AI 检测/升级先解析可执行文件，再判断共享的每 CLI 进程上限；不存在的可执行返回
cli_not_found，已解析但无空槽返回 ai_session_limit。检测/升级也登记 ai_processes，
role=check/upgrade；结束时写 ended_at。升级在 worker 首次执行前取消也会归还预约槽。

事件 envelope 只有 `seq/topic/type/ts/data`；seq 是进程全局序号。AIEventData 的
`session_seq` 是持久的会话序号，与 S3 的 run_seq 对应。订阅帧为
`{type:"subscribe",topic:"ai",session_id,after_seq}`，先登记订阅再读取数据库水位，回放至水位后
发送 ai.subscribed，再补齐并发事件；客户端按 session_seq 去重和增量重拉。
订阅队列有界，溢出沿用 S3 的 4408 断开语义，重连通过 after_seq 拉取，不阻塞 CLI 输出。

终端 WS 校验 Origin 与首帧 `{type:"auth",token}`，随后发送
`{type:"attach",after_offset:0}`。二进制输出为8字节大端起始 offset + 输出字节。
保留窗口内回放与实时交接连续、去重；早于环形缓冲窗口的 offset 从当前保留起点返回。
输入 `{type:"input",data:"<base64>"}`，resize `{type:"resize",rows,cols}`。
终态 attach 只回放，后端重启后终端原始输出不可恢复。

### 状态、安全与限额

会话状态预留 `starting → idle ⇄ busy ⇄ awaiting_approval → closing → ended`，启动失败为 failed。
S5-A 终端使用 starting/idle/closing/ended/failed；转换由单一会话任务负责。
结束原因包括 user_closed、process_exited、interrupted_on_exit、backend_restart、start_failed。
启动恢复把遗留活动会话置 ended/backend_restart；组首启动时间和可执行路径均匹配记录才 killpg，
防 PID 复用误杀。清理未确认时登记 kill_failed，SessionView.warnings 对桌面可见。

| 限额 | 数值 |
| --- | --- |
| 活动 PTY / 预留 headless | 各6 |
| 每 CLI 进程（会话、检测、升级共享） | 4 |
| 会话排队 / 单条提示词 | 10 / 32 KiB |
| 单终端内存输出 / 单次读取 | 2 MiB / 64 KiB |
| 单终端 WS / 单帧输入 / 输入速率 | 2 / 解码16 KiB / 256 KiB每秒 |
| rows / cols | 5..300 / 20..500 |
| 规范化事件 | 单条64 KiB、每会话5000条或8 MiB、14天保留；裁剪产生notice |

错误码：409 ai_session_limit、ai_queue_full、cli_not_found、repo_missing、session_ended、
builtin_profile、high_risk_ack_required、unsupported_cli、busy；503 ai_store_unavailable。
沿用 validation_error(422)、revision_conflict(409)、not_found(404)、store_unavailable/store_busy。
模型名用合同正则；档位用各 CLI 枚举；模型名及外部会话 id 不能以 `-` 开头。
命令只做 shlex.split 后以 argv 执行，无 shell。工作目录仅由登记的 repo_id 解析，
不存在或被替换成符号链接时拒绝，不回落到后端目录。

子进程环境保留 PATH/MANPATH/INFOPATH/FPATH；删除 TOOLBOX_*、CI。名称按 `_` 切段，
任一段为 TOKEN/TOKENS/SECRET/SECRETS/PASSWORD/PASSWD/PAT/COOKIE/COOKIES 时删除；
整名含 API_KEY/APIKEY/ACCESS_KEY/PRIVATE_KEY/TOKEN/SECRET/PASSWORD 也删除。
不注入任何凭据。生产 PATH 补全沿用旧端的五组目录；测试可注入 path_extras=[]。
TERM=xterm-256color，PTY 另设 COLORTERM=truecolor。

### 进程布局与资源关闭

后端不 fork；通过 start_new_session=True 启动单线程 Python 监督器。启动 JSON 从 stdin 传入，
不在 argv 暴露参数。监督器 fork 后，pipe 子进程 setpgid(0,0)，PTY 子进程 setsid+TIOCSCTTY，
CLI pgid=CLI pid，与监督器分组。控制 EOF/stop/SIGTERM 触发 TERM CLI组→3秒→KILL→waitpid；
直接子进程先退出也清理组内后代。主动 setsid 脱离该组的后代不在回收范围。

| 资源 | 关闭点 | 对应用例 |
| --- | --- | --- |
| 监督器/CLI组 | SupervisedProcess.close；监督器 finally killpg/waitpid | supervisor runtime pipe/ignore-term；独立 supervisor 生命周期 |
| 控制/状态 FD、启动 stdin/exec握手 FD | start异常/finally、close_control/close、监督器关闭与进程退出 | chdir失败、控制writer SIGKILL、exec守卫拒绝 |
| PTY slave/master、asyncio reader/writer注册 | start后close_slave；SessionLifecycle finally调用PTYTerminal.close | controlling terminal/env、ring replay、resize/input、终态回放 |
| 会话wait/command/初始提示词writer任务与排队 | _session finally cancel/gather、清空queue、移除_active | 幂等close、写入阻塞时close、并行shutdown、kill_failed |
| WS连接、输出/输入任务、订阅 | handler finally cancel/gather、减连接数、close；hub.unsubscribe | terminal WS auth/reconnect/cap、ai回放水位 |
| SQLite连接与锁FD | AIStore.close；初始化异常_close | corrupt/unknown-version/symlink、重启PID复用 |
| 升级job/检测进程与预约 | _command finally close/finish_process；job done callback归还槽；shutdown取消 | check记录/脱敏、升级共享上限、启动前取消 |
| pending审批 | 终态事务更新expired（本包只预建表，不接审批协议） | kill_failed与pending审批收尾 |

退出时先拒绝新会话，并行处理所有会话与检查/升级，整体5秒预算；RunService先关闭，随后
AISessionService，最后TelegramService。PTY原始输出不落数据库或日志，只保留内存回放。
ai.sqlite3 使用0700目录、0600文件、拒绝符号链接、WAL、FULL、busy_timeout=5000，IO在线程。
损坏/未知版本只使AI进入503只读错误态，不重置原件、不启动AI进程。

### Dev 假 AI

只允许 `--dev` + `TOOLBOX_CREDENTIALS=memory` + `TOOLBOX_DEV_FAKE_AI=1`，否则在bind前失败。
profiles 运行命令映射到仓库 `tests/fixtures/fake_cli/fake.py`，不解析或调用真实AI客户端。
先创建独立临时data-dir、空legacy-dir及本地临时仓库；通过本地仓库API登记repo_id后创建终端：

```sh
TOOLBOX_CREDENTIALS=memory TOOLBOX_DEV_FAKE_AI=1 \
TOOLBOX_LEGACY_CONFIG_DIR=/tmp/toolbox-fake-ai-legacy \
.venv/bin/python -m toolbox_backend --dev --data-dir /tmp/toolbox-fake-ai-data
```

开发启动器负责关闭stdin、等待退出并清理临时目录。测试沿用keyring/socket守卫并额外包装
Popen、exec*、posix_spawn*：解析到替身目录以外的claude/codex/agy会失败并记违规。
沙箱禁止端口bind或/bin/ps时，依赖它们的用例记not_run，由主控沙箱外验收；mock身份的
进程组测试不等于真实ps身份核验通过。

## S5-B：headless 会话（Claude / Codex / agy）

`kind=chat` 会话由 `services/ai_chat.py::ChatSession` 驱动，协议适配器在 `adapters/ai_cli/{claude,codex,agy}.py`
（纯 argv/协议/事件归一化）。每会话一个任务独占状态转换；HTTP 只投递命令（`inbox`）或同步入队，
读取任务只写事件、把控制事实（result/审批请求/退出）交给会话任务，读取不被下游阻塞。
监督器新增 stdio 模式（payload `stdio`：把 stdin/stdout/stderr 三个管道 dup2 到 CLI），其余语义不变。

### 协议与状态

- Claude：常驻进程 `--print --verbose --input-format stream-json --output-format stream-json
  --permission-mode <p> --permission-prompt-tool stdio [--model] [--effort]`，新会话 `--session-id <后端 uuid>`
  （即 external_id），续聊 `--resume <id>`；提示词只经 stdin；中断为 control_request(interrupt)，10 秒无
  result 则记 interrupted 并吞掉迟到的 result；未知事件/字段忽略；空闲 4 小时自动结束（ended_reason=`limit`）。
- Codex：每回合一进程 `exec --json --skip-git-repo-check -C <cwd> [-m] [-c model_reasoning_effort=E] -s <沙箱> -`
  （无 `--full-auto`；danger 档用 `--dangerously-bypass-approvals-and-sandbox` 代替 `-s`），续聊
  `exec resume <thread_id> --json --skip-git-repo-check [-m] [-c] -`（不传 `-s/-C`，仅首轮 danger 才再传 bypass）；
  提示词经 stdin；thread_id 取自 `thread.started`；每回合 30 分钟超时。
- agy：每回合 `--print --input-format stream-json --output-format stream-json --print-timeout=<n>s`
  + `--sandbox`（sandbox）/`--sandbox --mode plan`（plan）/`--dangerously-skip-permissions`（auto）、`--model`、
  `--effort`、`--conversation <id>`；conversation_id 取首个事件；总是传 `--print-timeout`（默认 600 秒，
  看门狗另加 60 秒）；stderr 含 `[agy] print timeout` 或缺少最终 agent_response DONE 一律 `turn_failed(timeout)`。
  stdin 输入失败（无事件且非零退出）自动退回 `--print=<prompt>`，并给会话加 warning
  `prompt_visible_to_other_processes`。
- 会话状态 `starting → idle ⇄ busy ⇄ awaiting_approval → closing → ended`（启动失败 failed）；回合以
  `turn_started` 开始，只有一个终态事件：`turn_completed` 或 `turn_failed`（payload `status` 为
  completed/failed/interrupted，`category` 为 timeout/exit/cli_error/process_exited/start_failed/interrupted）。
  排队 ≤10、提示词 ≤32 KiB；interrupt 同时清空排队；会话内 `request_id` 重复返回同一结果。
- 事件 payload：init `{cli,external_id}`、assistant/thinking `{text}`、tool_use `{tool,tool_use_id,summary}`、
  tool_result `{tool_use_id,is_error,text}`、turn_started `{turn,text}`（text 为本回合用户提示词，最多 4000 字）、approval `{approval_id,tool,summary,state,scope?}`、
  error `{category(stderr|bad_json|line_too_long|cli_error|process_exited),text?}`；stderr/坏 JSON/超长行
  共用每秒 ≤20 条限流，超出合并为 `notice{reason:"suppressed",count}`；单行 >4 MiB 丢弃；stderr 环形 64 KiB 脱敏。
- usage 汇总到 `usage_json`：`{turns,cost_usd,input_tokens,output_tokens}`，并累加适配器提供的其他
  `*_tokens`（Codex 包括 `cached_input_tokens`、`reasoning_output_tokens`；仅非负整数）。

### 审批（Claude）

`control_request can_use_tool` → `ai_approvals(pending)`（摘要 ≤500 字脱敏，入参只存 SHA-256，原始入参仅在内存
等待决定）+ 事件 `approval` + 会话 `awaiting_approval`。`POST /api/ai/sessions/{id}/approvals/{aid}`
`{decision: allow_once|allow_session|deny}`：原子 `pending→allowed|denied`，再回 control_response
（deny `{behavior:"deny",message}`；allow `{behavior:"allow",updatedInput:<原始入参>}`）。9 分钟（`approval_ttl_s`）
到期自动 deny（expired）；interrupt/close/进程退出时 pending → expired 并回 deny。第二个决定 409
`approval_settled`/`approval_expired`；超过截止时间的决定即使计时器未触发也不生效。
“本会话始终允许”只存内存规则（工具名；Bash 为命令首词），含 `; & | \` < > $( ${` 或换行的命令不匹配，仍逐条审批。
待决审批 >8 自动拒绝。

### 续聊与候选

`POST /api/ai/sessions/{id}/resume {request_id, ack_high_risk?}`（已结束且有 external_id；`resume_of`；Codex
沿用首轮沙箱，首轮为 danger 需 ack）。`POST /api/ai/sessions` 的 `resume:{session_id}` 同义，
`resume:{external_id}` 仅 Claude。`GET /api/ai/resume-candidates?repo_id=&cli=claude&query=` 只读
`$HOME/.claude/projects/<编码后的仓库 realpath>/` 下 ≤50 个 jsonl、每个头 ≤80 行，拒绝符号链接/越界/非常规文件，
返回 `{session_id,title(≤48),updated_at}`。

### 工单 AI 分析

`GET /api/work-items/{id}/ai-prompt?project_id=&cli=` → `{prompt,warnings}`；`POST /api/work-items/{id}/ai-analysis
{request_id,project_id,repo_id,profile_id,ack_high_risk?}` → SessionView（purpose=work_item_analysis，档位取
`ai.analysis.<cli>`，提示词作为首条消息，request_id 幂等，不写回“当前仓库”）。提示词只含整数工单号与 library/project
名称（单行清洗），不含工单正文；Claude 前缀固定 `mcp__ado-work-items__`，Codex/agy 取新增配置
`ai.mcp_tool_prefix.{codex,agy}`（默认 `mcp__adoWorkItems__` / `mcp__ado-work-items__`，`[A-Za-z0-9_.:-]{1,64}`；
属 config v3 的增量字段）。id 形如 `proj:<uuid>` 的项目视为新端独有，提示词加警示并给会话 warning
`legacy_mcp_may_not_resolve_project`。

### 配置枚举修订

Codex effort：`none|minimal|low|medium|high|xhigh|max`，默认仍为 `medium`；配置、HTTP 和 TG 向导
共用 `CODEX_EFFORTS`，已有配置无需迁移。具体模型不支持的档位由 CLI 服务端报错；JSON 编码的
API 错误取内层消息，经现有事件脱敏与 500 字截断后展示。

Claude permission：`acceptEdits|auto|bypassPermissions|manual|dontAsk|plan`，输入或已存的 `default` 规范化为
`manual`（pydantic 前置校验，迁移与读取都生效）；agy mode：`sandbox|plan|auto`，`analysis.agy.mode` 新默认 `plan`
（已存值不变），agy 增加可选 `effort low|medium|high|xhigh|max`。高权限档（bypassPermissions、danger-full-access、
agy auto）需 `ack_high_risk:true`。

### 新增 DTO / 路由 / 错误码

DTO：SendMessage、SendResult、ResumeSession、ApprovalDecision、ApprovalResult、ResumeCandidate(s)、
AnalysisRequest、PromptResponse；AISettingsPatch/AIView 增 `mcp_tool_prefix`。错误码（409）：`session_ended`、
`ai_queue_full`、`approval_settled`、`approval_expired`、`session_active`（续聊仍在运行的会话）、
`resume_unavailable`（无 external_id）；沿用 `cli_not_found/repo_missing/high_risk_ack_required/unsupported_cli`
（现仅 cli=other 的 chat 触发）。

### 未核对真实 CLI 的事项

Codex 0.163.0 的首轮/续聊、stdin、thread_id、command/agent 事件、usage 和 effort 枚举已由主控
于 2026-10-24 核对；本包回归只使用相同结构的替身。仍未核对：Codex 指定模型、workspace-write/danger
档、file/MCP/reasoning 事件、TERM 后续聊与首轮失败后续聊；
Claude `behavior:"allow"` 的 control_response 形状；agy
`--input-format stream-json` 的 stdin 行格式（已有 argv 退路）及 init/step_update/result 载荷是否嵌套在事件名下
（两种都解析）；Codex/agy 的 MCP 工具名前缀写法。替身只证明适配逻辑，不证明真实 CLI 行为。

### 测试

`tests/test_s5b_*.py`、`tests/independent/s5b/`；替身 `tests/fixtures/fake_cli/{claude,codex,agy}`（sh 蹦床，
读 `FAKE_AI_PYTHON`）与 `ai_fake.py`（行为由提示词关键字控制，`FAKE_AI_LOG` 记录 argv/stdin）。

## S5-C：Telegram AI 机器人与 `/wi` AI 分析

### 槽位与 telegram.sqlite3 v2

`TelegramService` 按槽位实例化：`main` 与 `ai:claude_code|codex|gemini`（`app.state.telegram_service`、
`app.state.telegram_ai_services[ai_id]`）。每槽位独立 Token、enable/disable/retry、getMe/webhook 检查、
首次基线（丢积压）、先登记后处理、409 立即 `conflict`（不抢占、不 deleteWebhook）、退避、5 分钟过期、
关闭清理；开关互不影响。共享同一 `TelegramStore`（按持有者计数，最后一个槽位释放才关库）、发件箱发送、
统一脱敏与纯文本发送。同一 bot_id 只能被一个已启用槽位使用：启用事务内检查，冲突 409 `bot_in_use`。
导入/迁移从不自动启用（config v3 `ai.bots.*.enabled` 迁移时即为 false）。

`telegram.sqlite3` user_version 1→2：单事务 `ALTER TABLE tg_bots ADD COLUMN slot`，已有 Bot 记为 `main`；
新库直接建 v2；更高版本进入只读错误态。不自动降级。

AI 槽位速率（每槽位独立）：每 chat ≤1 条/秒、每 Bot ≤20 条/分钟（`rate_chat_s`/`rate_bot_n`）。
主槽位沿用 S4 行为，未加该限速（偏差，见交付报告）。

### Token 与接口

Keychain `toolbox-next` account `ai_bot_token:<ai_id>`，元数据 kind=`telegram_ai_bot`（ref=ai_id）。
`GET /api/telegram/ai-bots`、`GET /api/telegram/ai-bots/{ai_id}`，`PUT|DELETE .../token`，
`POST .../token/import-legacy`（只读旧 `my-own-script`/`ai_bot_token:<id>`，缺失 404 `legacy_missing`），
`POST .../control/{enable,disable,retry}`；enable 需 `ack_old_bot_cleared:true`（可选 `delete_webhook`）。
启用中改删 Token 409 `telegram_active`；`ai_id` 仅 claude_code|codex|gemini（否则 422）。
WS `telegram.status` 增加 `slot`（默认 "main"，向后兼容）。新增 `GET /api/ai/agy-models`（`agy models`，
15 秒，缓存 10 分钟，失败返回空表 + category）。新增 DTO：AIBotEnableRequest、AIBotView、AIBotsView、
AIBotControlView、AgyModels。新增错误码：409 `bot_in_use`。

### ACL、指令与向导

AI 槽位只认私聊 owner；群内 owner、非 owner、伪造/跨 chat/重放令牌一律零回复零副作用；不响应 `/bind`、
任务、`/wi`。`/start|/help|/menu|/cc` 出该 CLI 的活动会话（聚焦/⏹/🗑）与「➕ 新建」。向导（全部为 S4 动作令牌，
payload 在服务端累积并在确认时重验）：仓库（仅 local_repos）→ Claude：全新/续聊（resume-candidates 最近 10 个）→
权限档 auto/acceptEdits/plan/manual/dontAsk；Codex：模型预设→effort→沙箱 read-only/workspace-write；
agy：模型（agy models）→模式 sandbox/plan。bypassPermissions、danger-full-access、agy auto 不提供，
手工构造含这些值的令牌也被拒。会话 origin=`{kind:"telegram",bot_id,chat_id,user_id}`，request_id=uuid5(令牌)。
非 `/` 文本投给本 chat 聚焦会话（无则出菜单）；回复某条会话输出投给该会话；AI 槽位上超过 5 分钟的消息
（含普通文本）回复“已过期”不执行。聚焦的桌面会话同样被投影。

### 投影（AiTelegramProjector，D11）

`AIStore.on_event` 同步调用 `offer()`（O(1)、有界队列 8192、满则丢弃并计数），消费任务只写发件箱。
assistant 正文 4000 字分块；工具调用 3 秒窗口合并为“🔧 工具: 摘要 等 N 个”；thinking 不发；tool_result 只发失败
（≤500 字）；回合结束“✓ 完成 / ❌ 出错（类别）/ ⏹ 已中断”+ 📝/🗑 按钮；意外结束发一条结束通知（user_closed 不发）。
dedup_key=`ai:<session_id>:<seq>`。发件箱 pending ≥500 时丢弃顺序：ai_tool → notify → ai_text(最旧)；
AI 类新条目在无可丢时自己被丢弃，不抛错。正文入箱前统一脱敏 + 已登记密钥扫描。槽位重新启用时丢弃
其遗留的 AI pending。reply-to 路由表仅内存、有界 512。

Claude 审批：TG 来源（或在该 Bot 聚焦过）的会话出现 pending 审批 → 向该 chat 发“✅ 允许一次/❌ 拒绝”
（kind=`ai_approval`，TTL=剩余有效期，无“始终允许”）。点击时重查 ACL，并在 config 单写者锁内评估
`authorize` 后原子 settle（`AISessionService.decide(..., authorize=)`）；先到者生效，另一端得“已由另一端处理”。

### `/wi`

详情新增「🔍 AI 分析」「📋 复制提示词」（仅 owner）。分析：仓库 → AI（只列可运行 profile，对应 AI 机器人未启用
标“（仅桌面可见）”）→ 确认 → `AISessionService.analyze`（analysis 档、origin=主槽位 chat、request_id=uuid5(令牌)）。
AI 槽位已启用则聚焦并路由输出，回复“已创建会话（#短id），回复将发到 @机器人”，否则“已在桌面 AI 会话页创建”。
高权限分析档（配置为 auto 等）因无 ack 被拒。复制提示词用 `reply`（纯文本、无 parse_mode），按钮可切换另两种 CLI 版本。
不写回任何配置。

### 切换步骤（摘要，逐个 AI 机器人）

①新端导入 Token（先做）②旧端清除该 AI 绑定（不要关旧端“启用 Telegram 触发任务”）③新端勾选
“旧端已清除绑定”启用 ④conflict 则回到②。回退：停用槽位，在旧 UI 重新粘贴 Token。

### Dev 假 Telegram

`FakeTelegram` 按 token 数字前缀区分 bot；`/api/dev/telegram/inject` 增加可选 `bot_id`，`sent` 带 `bot_id`。
三重门不变（--dev + memory 凭据 + TOOLBOX_DEV_FAKE_TELEGRAM=1）。

### 测试

`tests/test_s5c_*.py`（夹具 `tests/s5c_helpers.py`：按 token 区分的内存 Bot API + 替身 CLI）与
`tests/independent/s5c/`。替身 `ai_fake.py` 新增关键字 TOOLS3/TOOLFAIL/MANYLINES 与 `agy models`。

## S6-A：MCP 配置、ADO stdio 与自检

配置升级为 schema v4：新增 `mcp.ado/lark/figma/runtime` 和
`ai.analysis.mcp_source`（默认 `legacy`）。v3 迁移沿用持久快照、原子替换与 revision；
旧 Lark/Figma 字段逐项校验，无效项回退该字段默认值，日志只记录字段名，
`imported.*` 原文保留。迁移不确认 Lark 所有权、不自动启动第三方服务。
包版本读取 `resources/mcp/package.json`：Lark 0.5.1、Figma 0.13.2；
Node 下限 20.20.0、托管固定 v24.13.0。运行组件安装和 Lark/Figma 托管属于 S6-B。

### 接口与接入

所有接口仍经 Host/CORS/Bearer/BodyLimit；配置与凭据写请求携带 `revision`，冲突返回 409。

- `GET /api/mcp`：ADO 配置、自检运行快照、runtime、包版本与 revision。
- `PATCH /api/mcp/settings`：更新类型化 MCP 配置。
- `PUT|DELETE /api/mcp/credentials/{lark_app_secret|figma_token}`：凭据只写，不读回。
  PUT 使用 `{revision,value,app_id?,expiry_days?}`；DELETE 用 query revision/app_id。
  新 Keychain service 为 `toolbox-next`，account 为 `lark_app_secret:<app_id>` 或 `figma_token`。
  Figma 设置时间与有效期仅以元数据保存在 config 中；状态可经 `GET /api/credentials` 查询。
- `POST /api/mcp/credentials/import-legacy`：`{revision,kinds,app_id?}` 显式只读导入旧 Keychain；
  Lark 只导入旧 `lark_login_state.json` 的登录时间和 scope，不复制令牌或存储文件。
  每 kind 独立提交，前一项成功、后一项失败时前一项保留，可查询状态并重试；旧条目不变。
- `POST /api/mcp/ado/policy/import-legacy`：`{revision,path}` 从请求指定文件一次性导入策略基线，
  不硬编码旧仓库路径、不覆盖已导入基线。工具评估叠加 `imported.ai` 的全局与项目规则。
- `POST /api/mcp/ado/self-test`：`{timeout_s:15}`，上限 60 秒。通用 runner 经监督器 pipe 执行
  initialize → initialized → tools/list；返回协议、工具名、耗时、错误码及脱敏 stderr 尾部。
  stdout/stderr 独立读取，stderr 原始环形缓冲为 64 KiB；成功、失败、超时、取消统一收尾。
- `GET /api/mcp/client-config?server=ado|lark|figma&cli=claude|codex|agy`：返回无凭据片段。
  注册名 `toolbox_ado`、`toolbox_figma`、`lark`；不写任何 CLI 配置。

ADO CLI 命令与自检相同：`<sys.executable> -m toolbox_backend.mcp.ado_server --data-dir <dir>`。
数据目录须归当前用户所有、非符号链接、权限不宽于 0700；无效时 exit 2。
server 支持三版 MCP 协议、七个读取/评估工具及默认隐藏的创建工具；每次调用必须显式给出
library/project 名称或 ID，PAT 每次从新 Keychain 读取，不回落 UI active 配置。
附件经 S2 同源/响应大小限制，缓存采用私有权限、O_NOFOLLOW、LRU 和 14 天过期规则。
后端依赖不含 Pillow，附件结果明确标记跳过压缩。stdin EOF、TERM/INT、父进程变化均终止 server。

切换分析来源：先在各 CLI 注册片段并完成自检，再 `PATCH /api/ai/settings` 提交
`analysis.mcp_source="toolbox"` 与 `ack_cli_registered:true`；未确认返回 422。
toolbox 来源三家 CLI 均用 `mcp__toolbox_ado__`，去掉新端独有项目警示；切回 legacy 保持旧行为。

### 数据目录与测试替身

```text
<data-dir>/
  config.json
  migrations/config-v3-*.json
  mcp/
    ai_change_policy.yaml
    ado-attachments/<library摘要>/<work-item>/<attachment摘要>_<安全文件名>
    run/<server>/                 # 0700 专用空 cwd；拒绝已有 .env 等文件
```

自检环境在 S5 过滤基础上补全 PATH，删除父环境 NODE_OPTIONS、APP_ID/APP_SECRET、LARK_*、
USER_ACCESS_TOKEN、FIGMA_*；ADO PAT 不经 argv/环境注入。
`tests/test_s6_*.py` 与 `tests/independent/s6a/` 使用临时目录、内存凭据、S2 MockTransport、
Python 假 stdio server（无响应、错误响应、退出、stderr 洪泛、忽略 TERM、孙进程、取消）。
沿用 keyring/socket 守卫；不调用真实 Node/npm/AI CLI 或外部服务。沙箱禁止 `/bin/ps` 时，
runner 测试仅替换身份探针，保留真实监督器与进程组回收；真实身份探针和 live HTTP/WS 须沙箱外复跑。

## S6-B：Node/npm 运行组件、Lark 托管、Figma Wrapper、WS 与 TG

### Node/npm 运行组件（`toolbox_backend/mcp/runtime.py`）

- 检测顺序：`config.mcp.runtime.node.path`（用户确认路径）→ `<data-dir>/mcp/runtime/`（托管安装目录）
  → 系统/Homebrew/fnm/旧应用只读 bootstrap（`~/.config/my-own-script/node`）；版本门槛 `>= 20.20.0`。
- 安装任务（`POST /api/mcp/runtime/install`、`POST /api/mcp/jobs/{job_id}/cancel`）：
  1. 从 `nodejs.org/dist/v24.13.0/` 下载对应架构 tar.gz 与 `SHASUMS256.txt`，校验 SHA-256，使用
     `tarfile.extractall(..., filter="data")` 安全解包到 `<data-dir>/mcp/runtime/`（拒绝路径穿越与危险链接）。
  2. 将仓库内锁定的 `resources/mcp/{package.json,package-lock.json}` 暂存到 `<data-dir>/mcp/packages/`，
     经 `SupervisedProcess` 执行 `npm ci --ignore-scripts --prefix <data-dir>/mcp/packages`，随后仅对原生依赖执行
     `npm rebuild keytar --prefix <data-dir>/mcp/packages`。
  3. 总超时 600 秒，支持取消并回收进程组；输出经 `redact_mcp` 脱敏并截断至 `<= 256 KiB`；进度通过 WS `mcp.job` 推送。

### Lark 托管状态机与补丁（`services/mcp.py`、`mcp/lark_logs.py`、`resources/mcp/lark_mcp_patches.js`）

- 状态枚举：`stopped | starting | running | running_degraded | unhealthy | stopping | logging_in | failed`。
- 所有权门禁：`POST /api/mcp/lark/ownership`（需 `{ack_old_app_stopped: true}`）、`DELETE /api/mcp/lark/ownership`（需已停止）。
  未确认所有权时 `start/stop/login/logout` 均返回 `409 lark_owner_unconfirmed`；未配 Secret 返回 `409 lark_not_configured`；
  缺少运行组件返回 `409 mcp_runtime_missing`；端口被占用返回 `409 mcp_port_in_use`；启停/登录/登出互斥返回 `409 mcp_busy`。
  所有写动作支持 `request_id` 幂等。
- 监督启动：经 `SupervisedProcess` 启动 `<node> <packages>/node_modules/@larksuiteoapi/lark-mcp/dist/cli.js mcp ... --debug`，
  `cwd` 固定为 `<data-dir>/mcp/run/lark/`（0700 空目录）；`APP_SECRET` 仅通过环境变量传入（绝不进入 `argv`），
  剔除父进程 `APP_ID/LARK_*/USER_ACCESS_TOKEN`，`NODE_OPTIONS` 固定为 `--require <resources>/lark_mcp_patches.js`。
- 补丁与降级：`lark_mcp_patches.js` 通过 `Module._resolveFilename` 解析后的真实路径匹配 `mcp-tool/mcp-tool.js`、
  `auth/store.js`、`auth/utils/oidc.js`（修复相对路径 `require("./oidc")` 不命中的问题），并向 stderr 打印
  `[toolbox-lark-patch] <name>=applied|skipped|failed`。任一补丁非 `applied` 或出现
  `Builtin User Access Token Store will be disabled` 时进入 `running_degraded` 并附带告警。
- 就绪与健康探测：启动后每 250 ms 向 `127.0.0.1:<port>` 发送 `GET /mcp`（任意 HTTP 响应状态如 405 均视为就绪），
  最长 15 秒；运行期每 30 秒探测一次，连续 3 次失败转 `unhealthy`。
- 日志与令牌状态推断：逐行经 `redact_mcp`（含 `code=`/`code:`、`Bearer`、`u-`/`ur-` 及已登记密钥）写入
  `<data-dir>/mcp/logs/lark-mcp.log`（5 MiB × 2 轮换，权限 `0600`）。令牌状态仅根据 `mcp.lark.login.logged_in_at`
  与日志中的 `Successfully refreshed token` / `Token refresh failed` 推断 `ok | refresh_failing | unknown`，
  不解密 `storage.json`、不读 `lark-mcp-nodejs` Keychain。
- 登录与登出：`POST /api/mcp/lark/login`（300 秒外层超时，`POST /api/mcp/lark/login/cancel` 可取消；若服务运行中先停机并在成功后恢复）、
  `POST /api/mcp/lark/logout`（60 秒超时，清理 `mcp.lark.login` 元数据并提示旧 CLI bearer 已失效）。

### Figma Wrapper 与自检（`mcp/figma_wrapper.py`、`resources/mcp/figma_mcp_concurrency.js`）

- CLI 入口：`python -m toolbox_backend.mcp.figma_wrapper --data-dir <data-dir>`。
- 从新 Keychain `toolbox-next` 读取 `figma_token`（缺失向 stderr 打印提示并 `exit 2`），
  以 `--image-dir <调用者原始 cwd>` 启动 `figma-developer-mcp/dist/bin.js --stdio --no-telemetry`，
  子进程 `cwd` 固定为 `<data-dir>/mcp/run/figma/`；环境注入 `FIGMA_API_KEY`、`FRAMELINK_TELEMETRY=off`、
  `DO_NOT_TRACK=1`、并发/退避参数及 `NODE_OPTIONS=--require <resources>/figma_mcp_concurrency.js`。
- 复用 `proc_supervisor` 共享函数监听三信号（stdin EOF、SIGTERM/SIGINT、父进程 ppid 变化）并回收子进程组。
- `POST /api/mcp/figma/self-test` 复用 S6-A 通用 stdio runner 对 wrapper 执行握手与 `tools/list`。

### WS `mcp` 主题、Telegram `/mcp` 与并行关闭预算

- WS `/ws/events` 新增 `mcp` 主题（`subscribe` / `unsubscribe`）：支持 `after_seq` 历史回放、`mcp.subscribed {last_seq}`
  水位回执与实时 `mcp.status` / `mcp.job` 推送；慢客户端溢出按 4408 关闭。
- Telegram 主机器人新增私聊 owner 专属 `/mcp` 指令与主菜单 `MCP` 按钮：展示 ADO / Figma / Lark 状态摘要，
  仅提供 Lark MCP 启动/停止与状态刷新按钮（不含 AI CLI 注入，不提供 ADO/Figma 启动按钮）。
- 后端 `lifespan` 关闭阶段使用 `asyncio.gather(ai_service.close(), mcp_service.close())` 并行回收子进程组，
  共享 3 秒宽限期，总关闭耗时控制在 5 秒预算内。

## S7-A：服务管理

配置 schema v5 只新增 `services`：`binaries.{code_server,cloudflared}`（已确认绝对路径或 null）、
`code_server.start_timeout_s`（默认 30 秒）、`cloudflared.{protocol,max_tunnels}`（默认 http2、5）。
v4 启动迁移先保存 `migrations/config-v4-*.json` 原字节快照，再原子替换；重复初始化不重复迁移。
不新增凭据，不导入旧进程状态。dsh、网关及命名隧道推迟。

HTTP 仍经过 Host/CORS/Bearer/BodyLimit，错误为 S1 `detail` 结构：

- `GET /api/services`：缓存快照（code_server、cloudflared.global/tunnels、network、binaries、settings、revision）。
- `PATCH /api/services/settings`：`{revision, services}`；端口、绑定及认证不属于可写配置。
- `POST /api/services/import-legacy`：`{revision, path}`，只从指定 JSON 文件导入 `protocol` 枚举，不修改原件。
- `POST /api/services/{code-server|cloudflared}/{start|stop}`：`{request_id?}`，立即返回过渡状态，UUID 在本后端会话内幂等。
- `POST /api/services/cloudflared/tunnels`：`{target_url, ack_public:true, request_id?}`；仅允许显式端口的 localhost、127.0.0.1、[::1] HTTP/HTTPS 目标。
- `DELETE /api/services/cloudflared/tunnels/{id}`：仅回收指定自定义隧道。
- `POST /api/services/cloudflared/protocol`：`{revision, protocol}`；不自动重启，返回 `restart_required`。
- `GET /api/services/{name}/logs?tail=65536`：脱敏日志尾，最多 64 KiB；自定义隧道名为 `cloudflared-<id>`。

WS `/ws/events` 的 `services` 主题支持 subscribe/unsubscribe、after_seq、
`services.status {services_seq,snapshot}` 与 `services.subscribed {last_seq}`；历史保留本次后端运行的最近 1024 条，
队列溢出沿用 4408。状态查询不启动任何子进程，不等待启停锁。网络信息由固定 argv 的 ifconfig 每 5 秒刷新，
只显示 utun 上的 10.254.* VPN 地址及 en 接口 RFC1918 LAN 地址，无默认路由回退。

code-server 无额外参数启动；只提取其配置中的 auth/bind-addr，不解析密码值。不能证明 password 认证时拒绝启动。
全局 quick tunnel 固定指向 code-server 端口，自定义目标还须明确确认公网暴露；域名只接受该进程输出的完整严格匹配行。
服务使用 `SupervisedProcess`，后端失联由控制管道 EOF 触发监督器 TERM→3 秒→KILL；不会按端口或进程名杀进程。
端口已占用标记 external，停止不影响外部实例。健康探测每 30 秒执行，code-server 连续三次端口失败显示 unhealthy，
cloudflared 同时探测其回环目标端口，连续三次失败同样显示 unhealthy（不自动重启）。服务、MCP 与 AI 会话在 lifespan 中并行回收。

数据目录仅新增 `services/run/`（工作目录）和 `services/logs/{code-server,cloudflared,cloudflared-<id>}.log`；
日志 5 MiB × 2、0600，目录 0700，拒绝符号链接。运行状态与自定义目标不持久化。
TG 主 Bot owner 菜单新增“服务”页及 `/services`，状态仅含状态、端口、域名、局域网地址与协议；
自定义隧道先输入地址再点确认，VPN 显示“VPN 管理见 S8”。

测试只使用临时配置、内存凭据与 Python 编写的 code-server/cloudflared/ifconfig 替身，PATH 仅含替身。
`tests/test_s7_services.py`、`test_s7_ws_tg.py` 和 `tests/independent/s7a/` 覆盖无进程边界；
`test_s7_processes.py` 覆盖端口、进程组、忽略 TERM、孙进程与后端 SIGKILL；沙箱拒绝进程组或监听时显式标记 not_run，须在沙箱外复跑。

## S8-A：VPN 后端

配置 schema v6 在 `vpn` 段保存客户端 bundle id、隧道前缀、登录字段、自动化模式与超时；v5→v6 初始化会先留存原始快照，再原子替换。VPN 密码和 TOTP 种子只写入 `toolbox-next` 凭据后端，状态接口只返回是否已配置。旧 Keychain 导入为显式只读操作。

TOTP 导入请求接收不超过 1 MiB 的文本或 `otpauth://` URI；服务端仅在内存解析并要求调用方选择多条匹配项。计算使用标准库 RFC 6238 SHA1/6 位/30 秒。VPN 运行使用单飞任务、幂等 request_id、取消与总时限，最多保留 20 条内存记录。客户端控制使用固定 argv 与 bundle id；登录和窗口自动化当前留有 S8-B 接缝，占位实现明确返回 `vpn_not_implemented`。

HTTP 路由为 `/api/vpn*`，WebSocket 主题为 `vpn`，TG `/vpn status|on` 仅 owner 可用。`vpn/logs/vpn.log` 限 5 MiB 并保留一个轮转文件，目录 0700、日志 0600，拒绝符号链接。状态读取每次直读网络接口；运行收尾与应用关闭会释放 VPN 任务。
