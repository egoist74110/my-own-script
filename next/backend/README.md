# toolbox-backend (S0-A)

TOOLBOX next 的本地后端进程：FastAPI + uvicorn，Python >= 3.14，uv 管理依赖（`uv.lock` 入库）。
接口合同见 `docs/modernization/WORK_PACKAGES.md` 的「S0 已定接口」。

## 分层

`src/toolbox_backend/`：`api/`（路由、WS、安全中间件）、`services/`（事件总线、系统服务）、
`domain/`（Pydantic 数据/事件模型）、`adapters/`（外部适配器；S0 仅 stdin EOF 监视）。
`server.py` 为进程入口，`contracts.py` 为契约生成器。

## 运行

```sh
cd next/backend
UV_PYTHON_DOWNLOADS=never uv sync --frozen
UV_PYTHON_DOWNLOADS=never uv run python -m toolbox_backend [--dev]
```

- 只绑 `127.0.0.1`，端口自行 `bind(("127.0.0.1", 0))`，无监听地址选项。
- 服务开始接受连接后 stdout 只打印一行 `TOOLBOX_READY {"v":1,"port":..,"token":"..","pid":..}`；
  之后 stdout 无输出，日志走 stderr 且脱敏 token。
- 退出：stdin EOF、SIGTERM、SIGINT 均协调退出，退出码 0；启动失败非 0 且不打印 READY。
- 测试钩子：环境变量 `TOOLBOX_HEARTBEAT_INTERVAL_S`（默认 5）缩短心跳间隔。
  进程内可通过 `Settings(heartbeat_interval_s=..., ws_auth_timeout_s=..., ws_queue_size=...)` 注入。
- 手动试用（token 在 READY 行里）：
  `curl -H "Authorization: Bearer <token>" http://127.0.0.1:<port>/health`

## 测试

```sh
UV_PYTHON_DOWNLOADS=never uv sync --frozen && UV_PYTHON_DOWNLOADS=never uv run pytest -q
UV_PYTHON_DOWNLOADS=never uv run ruff check .
```

`tests/` 为主测试（子进程测试均有超时并在 finally 回收进程）；`tests/independent/` 为独立测试者的用例。
部分测试会真实等待约 5 秒（WS 未认证 4401）。

## 契约生成

```sh
UV_PYTHON_DOWNLOADS=never uv run python -m toolbox_backend.contracts          # 写 ../contracts/
UV_PYTHON_DOWNLOADS=never uv run python -m toolbox_backend.contracts --check  # 漂移时 exit 1
```

输出 `next/contracts/openapi.json` 与 `events.schema.json`（排序键、末尾换行，确定性）。
`tests/test_contracts.py` 比对仓库内文件与当前生成结果，改了模型/路由后必须重新生成并提交。

## 实现要点

- READY 时序：uvicorn 以已绑定 socket 服务；轮询 `server.started`（监听已创建且 lifespan 已启动）后才写 READY。
- 信号：覆盖 uvicorn 的 `capture_signals`，自行用 `loop.add_signal_handler` 置 `should_exit`，避免 uvicorn
  退出后重发信号导致非 0 退出码。stdin 监视线程直接读 fd（读 `sys.stdin` 缓冲会在解释器退出时 abort）。
- 事件：`EventHub` 进程内 `seq` 单调；hello 与订阅注册同步完成（无 await），故后续事件 seq 必大于 hello 的 seq。
  每连接队列 256，满则标记溢出，处理器以 4408 关闭；对完全不读的对端，uvicorn 的发送背压会使关闭帧
  无法送达，处理器等待 2 秒后连接被拆除（不影响其他连接）。
- WS 无 Origin 头（非浏览器客户端）视为允许；有 Origin 则必须在允许列表。
