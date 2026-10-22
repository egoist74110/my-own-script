# toolbox-backend (S0 / S1 / S2-A)

TOOLBOX next 的本地后端进程：FastAPI + uvicorn，Python >= 3.14，uv 管理依赖（`uv.lock` 入库）。
接口合同见仓库 `docs/modernization/WORK_PACKAGES.md` 的 S0、S1、S2 及「S1-A 主控裁决」。

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

- 新 store 为 `<data-dir>/config.json`，schema v1；目录 0700，文件、锁及导入快照 0600。
  新 Keychain service 为 `toolbox-next`，account 为 `ado_pat:<library_id>`。
  旧 service `my-own-script` 只有只读适配器，S1 只读取 ADO PAT。
- 普通读取不创建文件、不迁移。文件不存在时返回内存中的空配置（revision 0）。
  写入在线程中执行：进程内锁（最多等待 5 秒）→ flock（最多等待 5 秒）→ 重读 → 比较 revision → 副本变更与完整校验
  → 同目录临时文件 flush/fsync → `os.replace` → fsync 目录 → 释放锁 → `settings.changed {revision}`。
  每次成功提交 revision +1；旧 revision 返回 409 `revision_conflict`。replace 是提交点，替换后的异常会核验已提交内容。
- 启动时显式调用 `ConfigStore.initialize()`。v1 是首个生产版本，生产迁移注册表为空。
  测试或后续版本可注入 `{from_version: step_fn}`；每个纯函数接收独立字典，返回 schema_version +1 的字典。
  迁移持有同一进程锁和 flock，重读后校验完整迁移结果，先把原文字节写为
  `config.json.bak-v<旧版本>-<时间戳>...` 并 fsync，再原子替换；迁移提交 revision +1。
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
- **生产 preflight/start 返回 409 `unsupported_task`**，直到 S3-B 接入完整执行适配器。
  HTTP 不接受 executor、cwd、URL、argv、owner 或测试远端开关。应用创建时可通过
  `create_app(task_executor=..., task_git=...)` 做可信依赖注入；没有环境变量或页面后门。
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
