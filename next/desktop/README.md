# TOOLBOX 桌面前端（S0.5：方向 E 液态玻璃 × 游戏 UI · 工具优先）

Vue 3 + TypeScript strict + Vite + Tailwind v4 + Reka UI / shadcn-vue + Pinia + vue-query。
骨架：208px 侧栏（编号导航 + Pinned）｜主区（工具栏 + 内容）｜可收起的右侧检查器｜底部状态栏。三屏 mock：任务 `/tasks`、工单 `/work-items`、AI 会话 `/ai`（`/` 重定向 `/tasks`）。

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
| `pnpm guard:dist`                | 产物禁词守卫（Rhine/Arknights/莱茵/fonts.googleapis 与残留 `--denied`）；**必须在 `pnpm build` 之后**单独运行，dist 不存在即失败                   |
| `pnpm contracts:gen`             | `../contracts/openapi.json` -> `src/api/schema.d.ts`                                                                                               |
| `pnpm contracts:check`           | 重新生成并与入库文件比对                                                                                                                           |

## 连接与安全

- 连接信息（端口 + token）只在内存：Tauri 内调用 `backend_connection`；`pnpm dev:web` 下读 `VITE_TOOLBOX_PORT / VITE_TOOLBOX_TOKEN`。不写 localStorage、不进 URL、不进日志。
- HTTP 用 `Authorization: Bearer`；WebSocket 连接后首帧发 `{"type":"auth","token":...}`。
- 断线按 0.5s -> 最大 10s 指数退避重连，每次重连重新取连接信息并重新 auth；超过 15s 无任何事件视为连接已死。
- 告警态只由 `system.alert` / `system.hello` 事件驱动，开关只发 `POST /api/system/alert`。

## 目录

- `src/app`：壳（`App.vue`）、路由、runtime、`inspector.ts`（检查器容器注入）、`mock/`（侧栏 Pinned、状态栏 VPN/TG/MCP 的 mock）。
- `src/design`：`tokens.css`（令牌）、`ui.css`（玻璃/切角/斜切/条纹/动效关键帧）、`app.css`（入口与 body 背景）。
- `src/components`：基础组件；`ui/` 为 shadcn-vue 拷入件（仅 Switch）。
- `src/features/{tasks,work-items,ai}`：页面；各自 `mock/` 放虚构数据。feature 之间不互相引用内部文件。
- `src/shared/cn.ts`：类名合并。注意不能放 `src/lib/`（仓库根 `.gitignore` 的 `lib/` 规则会让它不入库）。
- `src/api`、`src/stores`：连接、客户端、事件、Pinia（`backend` 连接/告警；`ui` 检查器开合）。
- 测试在 `tests/unit`；`tests/independent` 为独立验证用例目录。`pnpm test` 不依赖 `dist/`（源码禁词仍在测试里检查）；产物检查用 `pnpm guard:dist`（build 之后）。测试夹具 `tests/unit/boot.ts`：`boot()` 起连接，`bootUnconnected()` 不调用 `runtime.start()`（用于“未取得连接”场景）。

## 组件清单（`src/components`）

GlassPanel（`cut` lg/sm/none）· AppTabs（Reka Tabs，斜切，方向键；每个页签配 tabpanel 并用 aria-controls / aria-labelledby 关联。传默认插槽 `<AppTabs v-model=… :items=… label=…><template #default="{ item }">…</template></AppTabs>` 时当前面板显示插槽内容；不传插槽则面板为空且隐藏，内容仍由页面按 `v-model` 自行渲染）· AppButton（primary/accent/ghost）· IconButton（32x32，必须 `label`）· TextInput · SearchBox（⌘K/Ctrl+K 聚焦，Esc 失焦，不做真实搜索）· BlockTag · StampBadge（CLEAR/FAILED/ROLLBACK）· StageBar（done/run/pending/fail，运行中流动纹）· EnergyBar（0..N 段）· StatusDot（ok/run/warn/idle）· AlertBanner · ApprovalBar（Y/A/N，输入框聚焦时不响应，发出 `decide`）· InspectorPanel（Teleport 进壳的检查器）· SidebarNav · StatusBar · AlertToggle（视觉 20px，命中区经伪元素扩到 `--target-min` 32px）。

## 告警

状态只来自 store 的 `alert`（`system.alert` / `system.hello`）。告警时：主区顶部黑色横幅（`reason`，缺省给默认文案）；任务页 mock 里 `errorOnAlert` 的行与检查器转橙；导航「任务」角标变 `!`。无遮罩，工作区保持可交互。

## mock 位置与如何换接口

mock 只在 `src/features/<feature>/mock/` 与 `src/app/mock/`。页面只调用一个取数组合式（`useTasks()` / `useWorkItems()` / `useAiSessions()`，返回响应式数据与动作）。换真实接口时：保持组合式的返回形状，把内部换成 `useQuery` + `runtime.api()`（见 `components/StatusBar.vue` 的 `/health` 查询），页面模板不用改。`useAiSessions()` 的对话、已发送消息、审批记录与待审批命令按会话 id 隔离（`messages(id)` / `approvals(id)` / `pending(id)` / `send(id, text)` / `decide(id, decision)`）；审批 Y/A/N 目前只改 mock 状态，接后端时在 `decide` 里发请求。

## 来源

视觉语言与字体许可见 `../THIRD_PARTY.md`。设计参考见 `docs/modernization/design/e-tool-first/`（只作参考，未拷贝）。
