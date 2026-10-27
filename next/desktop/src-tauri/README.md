# TOOLBOX 桌面壳（Tauri 2）

Rust 薄壳：窗口、菜单栏托盘、关窗常驻、单实例，并拉起 / 监督 / 回收 Python 后端。不含业务逻辑。接口以 `docs/modernization/archive/work-packages/S0.md`「S0 已定接口」为准。

## 结构

```text
src-tauri/
  Cargo.toml / build.rs        build.rs 用 AppManifest 只登记 2 个页面命令
  tauri.conf.json              identifier dev.toolbox.next, productName TOOLBOX, Overlay 标题栏, CSP
  capabilities/main.json       最小权限：两个后端命令 + 事件监听 + 窗口拖拽
  icons/                       自绘占位图标（方框 + 橙色横条，非原作标志）
  src/main.rs                  入口，仅调用 lib::run()
  src/lib.rs
  src/backend.rs               监督器（无 GUI，可单测）
  src/app.rs                   Tauri 装配：命令、托盘、关窗隐藏、Dock 重开、退出协调
  tests/supervisor.rs          监督器集成测试（替身后端）
  tests/fixtures/fake_backend.py   替身后端（不监听端口，只模拟握手/崩溃/忽略 SIGTERM 等）
```

### 监督器（`backend.rs`）

- 命令：开发默认 `<repo>/next/backend/.venv/bin/python -m toolbox_backend --dev`，cwd `next/backend`；环境变量 `TOOLBOX_BACKEND_CMD` 整体覆盖（shell 风格引号拆分，如 `TOOLBOX_BACKEND_CMD="/usr/bin/env python3 /path/fake.py"`）。
- 子进程 `process_group(0)`，持有 stdin 管道；stdout 第一行必须是 `TOOLBOX_READY {"v":1,"port":..,"token":"..","pid":..}`（20 秒超时，行长上限 4096，非法/超时/提前退出都算握手失败并进入重启）。READY 之后 stdout 如有内容只记一条不含内容的日志并继续排空。
- stderr 逐行转发为 `[toolbox] backend: ...`。握手完成前的 stderr 行暂存（上限 1000 行），READY 后按已知 token 脱敏再输出，所以与 READY 行赛跑的日志也不会泄露 token。
- 重启：意外退出后按 1,2,4…≤30 秒退避；READY 后稳定运行 ≥60 秒则退避序列重置。`restarts` 是自监督器启动以来的累计次数（不随稳定期清零）。
- 状态 `backend://status` 载荷：`{"state","pid","restarts"}`，`state` ∈ `starting | ready | restarting | stopping | stopped`，不含 token。命令 `backend_status` 返回同样结构的快照（页面可能错过早期事件）。
- 命令 `backend_connection` → `{port, token}`；后端未就绪（启动或重启中）时最多等 20 秒，超时报错；关闭中立即报错。
- 协调关闭（只执行一次）：`shutdown()` 用 compare-and-swap 抢占，唯一的 run-loop 任务（子进程的唯一属主）执行：关 stdin → 进程组 SIGTERM → 最多 5 秒 → 进程组 SIGKILL → wait；之后确认 `kill(-pgid,0)` 为 ESRCH。重启与关闭的竞争：关闭只置位 level-triggered 标志，run-loop 在 spawn 之前和每个可阻塞的 await 处检查；关闭开始后状态只允许发布 `stopping/stopped`。
- 意外退出（leader 已死）时同样对进程组做清理，避免孙进程残留。

### 壳行为（`app.rs`）

- 关窗 = 隐藏；Dock 图标点击（`RunEvent::Reopen`）与托盘「显示窗口」恢复。
- 托盘：状态（禁用项，随 `backend://status` 更新）、显示窗口、退出。
- 单实例：`tauri-plugin-single-instance`，第二次启动聚焦已有窗口后第二个进程退出。
- 退出入口（托盘退出、⌘Q/系统注销触发的 `ExitRequested`、SIGTERM/SIGINT）全部汇入 `begin_quit`：`prevent_exit` → 一次协调关闭 → `app.exit(0)`；`RunEvent::Exit` 里再做一次幂等兜底。

## 测试

```bash
export CARGO_TARGET_DIR=/Users/wesker/my-own-script-next/.local/cargo-target   # 共享构建目录
cd next/desktop/src-tauri
cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test
```

测试需要 `/usr/bin/env python3`（替身后端）；不联网、不监听端口、不触碰 Keychain 或用户配置。`cargo test` 约 6 秒（其中一个用例真实等待 5 秒 SIGKILL 宽限期）。

构建可执行文件（不签名、不安装；`pnpm tauri` 需要 `next/desktop/package.json` 提供 `@tauri-apps/cli` 与 `"tauri": "tauri"` 脚本）：

```bash
cd next/desktop && pnpm tauri build --debug --no-bundle
# 产物：$CARGO_TARGET_DIR/debug/toolbox-desktop
```

## 手动验证清单（真实 GUI，未在自动化覆盖）

用替身后端即可，不需要真实后端：
`TOOLBOX_BACKEND_CMD="/usr/bin/env python3 $PWD/tests/fixtures/fake_backend.py" FAKE_STATE_DIR=$(mktemp -d) FAKE_MODE=ok <产物路径>`

- [ ] 托盘：菜单栏出现图标；第一项灰色「后端：运行中 (pid …)」；杀掉替身（`kill <pid>`）后文字变「重启中 (第 1 次)」再恢复「运行中」。
- [ ] 关窗常驻：点红灯关闭，窗口消失但托盘与后端仍在（`ps` 可见替身）；点 Dock 图标窗口恢复；托盘「显示窗口」同样可恢复。
- [ ] ⌘Q 回收：`FAKE_MODE=ignore_term` 下按 ⌘Q，约 5 秒后进程消失，`ps -g <pgid>` 为空（替身与其孙进程都被回收）；托盘「退出」同样。
- [ ] 单实例：再次启动产物，第二个进程立即退出，已有窗口被聚焦（含隐藏状态下被唤出）。
- [ ] SIGTERM：`kill -TERM <壳 pid>` 与托盘退出行为一致（已用 `FAKE_MODE=ignore_term` 手测过一次：壳退出、进程组清空）。
- [ ] 覆盖式标题栏：红绿灯保留，标题隐藏；前端实现拖拽区后验证拖动与双击最大化。

## 给主控合并的前端侧内容

见施工报告：`next/desktop/package.json` 需要 `@tauri-apps/cli`（dev）、`@tauri-apps/api`、脚本 `"tauri": "tauri"`，以及 `dev` / `build` 脚本（`tauri.conf.json` 的 `beforeDevCommand` / `beforeBuildCommand` 分别调用 `pnpm dev` / `pnpm build`，`devUrl` 为 `http://localhost:1420`，`frontendDist` 为 `../dist`）。

## 打包态后端解析

壳通过 `BackendCommand::packaged` 统一解析启动命令，顺序如下：

1. `TOOLBOX_BACKEND_CMD` 去除首尾空白后非空：沿用开发态的 shell 风格引号拆分与 cwd 行为，整体覆盖 program/args；引号不平衡仍报错。
2. 否则检查 `<壳可执行文件目录>/../Resources/backend/bin/python3.14`。存在时，以该 Python 执行 `-m toolbox_backend`（无 `--dev`），cwd 为 `Resources/backend`，追加 `PYTHONDONTWRITEBYTECODE=1`、`PYTHONNOUSERSITE=1`，避免写入签名 bundle 的 pyc 或读取用户 site-packages。打包态不要求编译时仓库路径存在。
3. Python 不存在时回退现有 `dev()` 命令；空白覆盖变量视为未设置。

构建暂存目录约定为 `next/build/app-resources/{backend,mcp}`：`backend` 放完整 Python 运行时、锁定依赖和后端 wheel（pyc 由构建阶段预编译），`mcp` 放补丁脚本与包清单。准备好资源后，从 `next/desktop` 执行：

```bash
pnpm tauri build --config src-tauri/tauri.bundle.conf.json
```

叠加配置的资源源路径相对 `src-tauri/`，分别为 `../../build/app-resources/backend`、`../../build/app-resources/mcp`，映射到 `.app/Contents/Resources/backend`、`.app/Contents/Resources/mcp`。默认 `tauri.conf.json` 不引用暂存资源，开发态与 `cargo test` 无需预先构建它们。此命令仅说明叠加配置用法；构建与签名流程由 S9-B 提供。

`tauri.conf.json` 的版本起点为 `1.0.0`；Cargo/package.json/pyproject 的版本同步与一致性校验留给 S9-B。`minimumSystemVersion` 暂不设置，待 S9-B 实测。
