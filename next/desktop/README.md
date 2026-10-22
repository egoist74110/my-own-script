# TOOLBOX 桌面前端（S0-B：HUD 壳）

Vue 3 + TypeScript strict + Vite + Tailwind v4 + Reka UI / shadcn-vue + Pinia + vue-query。
单页总览：左栏能力索引、时钟、后端连接状态、告警演示开关、WARNING 框、∞ 占位。

## 命令（在 `next/desktop`）

| 命令                             | 作用                                                                                                                                               |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pnpm install --frozen-lockfile` | 安装依赖（pnpm-lock.yaml 入库）                                                                                                                    |
| `pnpm dev:web`                   | 拉起 `../backend`（`uv run python -m toolbox_backend --dev`），解析 READY 行，把端口/token 以环境变量注入 vite（1420，strictPort），退出时回收后端 |
| `pnpm dev`                       | 只启动 vite（Tauri `beforeDevCommand` 用；连接信息由 Tauri 命令 `backend_connection` 提供）                                                        |
| `pnpm typecheck`                 | vue-tsc                                                                                                                                            |
| `pnpm lint`                      | ESLint（flat）+ Prettier 检查                                                                                                                      |
| `pnpm test`                      | Vitest（jsdom，假 WebSocket / 假 fetch / 假定时器，不连任何真实服务）                                                                              |
| `pnpm build`                     | 类型检查 + vite build                                                                                                                              |
| `pnpm contracts:gen`             | `../contracts/openapi.json` -> `src/api/schema.d.ts`                                                                                               |
| `pnpm contracts:check`           | 重新生成并与入库文件比对                                                                                                                           |

## 连接与安全

- 连接信息（端口 + token）只在内存：Tauri 内调用 `backend_connection`；`pnpm dev:web` 下读 `VITE_TOOLBOX_PORT / VITE_TOOLBOX_TOKEN`。不写 localStorage、不进 URL、不进日志。
- HTTP 用 `Authorization: Bearer`；WebSocket 连接后首帧发 `{"type":"auth","token":...}`。
- 断线按 0.5s -> 最大 10s 指数退避重连，每次重连重新取连接信息并重新 auth；超过 15s 无任何事件视为连接已死。
- 告警态只由 `system.alert` / `system.hello` 事件驱动，开关只发 `POST /api/system/alert`。

## 目录

`src/app`（壳、路由、runtime）· `src/design`（令牌与 HUD 样式）· `src/components`（含 `ui/` shadcn-vue 拷入组件）· `src/features/overview` · `src/api`（连接、客户端、事件）· `src/stores`。
测试在 `tests/unit`；`tests/independent` 为独立验证用例目录。

## 来源

视觉语言与字体许可见 `../THIRD_PARTY.md`。∞ 主视觉为自绘占位。
