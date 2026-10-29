# 开发 / 测试

## 这个能力做什么
新版（`next/`）的本地开发运行、各层测试命令、契约生成/检查，以及「新增一个能力」的落点约定。

## 关键文件
| 做什么 | 文件 |
| --- | --- |
| 后端工程/依赖/pytest 配置（`testpaths=tests`、`asyncio_mode=auto`） | `next/backend/pyproject.toml`、`uv.lock` |
| 后端测试 | `next/backend/tests/` |
| 前端脚本 | `next/desktop/package.json` |
| 前端守卫脚本 | `next/desktop/scripts/`（`contracts-check.mjs`、`guard-dist.mjs`、`forbidden-scan.mjs`、`dev-web.mjs`） |
| Rust 壳与测试 | `next/desktop/src-tauri/`（`src/`、`tests/`） |
| 构建脚本测试 | `next/scripts/tests/`（`test_scripts.py`、`test_sync_version.py`、`test_make_update_manifest.py`） |
| 契约产物 | `next/contracts/{openapi,events.schema}.json`、`next/desktop/src/api/schema.d.ts`（生成，不手改） |
| 契约生成器 | `next/backend/src/toolbox_backend/contracts.py` |

## 怎么跑
```bash
# 后端
cd next/backend && uv run pytest -q

# 前端（以 package.json 为准）
cd next/desktop
pnpm typecheck        # vue-tsc --noEmit
pnpm lint             # eslint + prettier --check
pnpm test             # vitest run
pnpm build            # vue-tsc + vite build
pnpm tauri dev        # 桌面开发（dev:web 仅起网页端：pnpm dev:web）

# Rust 壳
cd next/desktop/src-tauri && cargo test

# 构建脚本
cd next && python3 -m unittest scripts.tests.test_scripts    # 另可加 test_sync_version、test_make_update_manifest
python3 next/scripts/sync_version.py --check                 # 版本一致性（仓库根）
```

## 契约（改后端 API 后必做）
```bash
cd next/backend && uv run python -m toolbox_backend.contracts            # 重新生成 openapi.json / events.schema.json
cd next/backend && uv run python -m toolbox_backend.contracts --check    # 有漂移则 exit 1
cd next/desktop && pnpm contracts:gen                                    # 由 openapi.json 生成 src/api/schema.d.ts
cd next/desktop && pnpm contracts:check                                  # schema.d.ts 与 openapi.json 不一致则失败
```
后端另有 `tests/test_contracts.py` 守护。

## 沙箱 / 环境下的已知失败
- 沙箱（限制端口监听、子进程、keychain、`~/Library` 写入）下，涉及起本地 HTTP/WS、拉子进程（后端 supervisor、MCP、PTY、`verify_app.sh`）的测试可能因端口/进程限制失败；这类失败先在沙箱外复跑再判断，别直接当回归。
- 间歇失败：`next/backend/tests/test_s6b_lark.py::test_lark_health_probe_marks_unhealthy_after_3_failures`（Lark 健康探测，依赖时序）。单独复跑通过即视为抖动。
- 迭代时只跑针对性测试（`uv run pytest -q tests/test_xxx.py`），全量留到提交前。

## 新增能力的落点约定（照 `AGENTS.md` 红线）
1. **代码**：业务进 `next/backend/src/toolbox_backend/`（`api/` 路由、`services/` 业务、`adapters/` 外部 IO、`domain/` 模型、`mcp/`、`vpn/`）；界面进 `next/desktop/src/`。
2. **密钥**：只进 macOS Keychain（`adapters/credentials.py`），不写 YAML/日志/响应。
3. **契约**：改 API 后跑上面的契约生成 + 检查，不手改生成文件。
4. **索引**：`docs/CAPABILITIES.md` 加一行并在 `docs/capabilities/` 补一页。
5. **红线**：涉及 ADO/发布先读 `docs/SECURITY.md` 与 `docs/AI_CHANGE_POLICY.md`。
