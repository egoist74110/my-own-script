# TOOLBOX 桌面前端（R1：方向 B「macOS 原生」）

Vue 3 + TypeScript strict + Vite + Tailwind v4 + Reka UI / shadcn-vue + Pinia + vue-query。
骨架：232px 通高侧栏（分组导航 + 底部设置/连接状态行）｜页面区（每页自己的列表栏 / 详情 / 顶栏，52px）｜可开关的右侧检查器（280px）。没有底部状态栏。任务 `/tasks` 已接真实 S3 接口（CRUD、执行预检、双击幂等启动、取消与 unknown 对账、WS 日志订阅与补齐、检查器），按 B-Tasks 原生风格呈现；AI 会话 `/ai` 仍是 mock；工单 `/work-items` 与设置 `/settings` 已接真实接口（`/` 重定向 `/tasks`）。

## 命令（在 `next/desktop`）

| 命令                             | 作用                                                                                                                                                                                                                                                      |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pnpm install --frozen-lockfile` | 安装依赖（pnpm-lock.yaml 入库）                                                                                                                                                                                                                           |
| `pnpm dev:web`                   | 拉起 `../backend`（`uv run python -m toolbox_backend --dev`，带 `TOOLBOX_DEV_FAKE_ADO` 指向 `../backend/tests/fixtures/fake-ado`，工单页读本地假 ADO，不连真实服务），解析 READY 行，把端口/token 以环境变量注入 vite（1420，strictPort），退出时回收后端 |
| `pnpm dev`                       | 只启动 vite（Tauri `beforeDevCommand` 用；连接信息由 Tauri 命令 `backend_connection` 提供）                                                                                                                                                               |
| `pnpm typecheck`                 | vue-tsc                                                                                                                                                                                                                                                   |
| `pnpm lint`                      | ESLint（flat）+ Prettier 检查                                                                                                                                                                                                                             |
| `pnpm test`                      | Vitest（jsdom，假 WebSocket / 假 fetch / 假定时器，不连任何真实服务）                                                                                                                                                                                     |
| `pnpm build`                     | 类型检查 + vite build                                                                                                                                                                                                                                     |
| `pnpm guard:dist`                | 产物禁词守卫（Rhine/Arknights/莱茵/fonts.googleapis 与残留 `--denied`）；**必须在 `pnpm build` 之后**单独运行，dist 不存在即失败                                                                                                                          |
| `pnpm contracts:gen`             | `../contracts/openapi.json` -> `src/api/schema.d.ts`                                                                                                                                                                                                      |
| `pnpm contracts:check`           | 重新生成并与入库文件比对                                                                                                                                                                                                                                  |

## 连接与安全

- 连接信息（端口 + token）只在内存：Tauri 内调用 `backend_connection`；`pnpm dev:web` 下读 `VITE_TOOLBOX_PORT / VITE_TOOLBOX_TOKEN`。不写 localStorage、不进 URL、不进日志。
- HTTP 用 `Authorization: Bearer`；WebSocket 连接后首帧发 `{"type":"auth","token":...}`。
- 断线按 0.5s -> 最大 10s 指数退避重连，每次重连重新取连接信息并重新 auth；超过 15s 无任何事件视为连接已死。
- 告警态只由 `system.alert` / `system.hello` 事件驱动，开关只发 `POST /api/system/alert`。

## 目录

- `src/app`：壳（`App.vue`）、路由、runtime、`inspector.ts`（检查器容器注入）。
- `src/design`：`tokens.css`（浅色令牌 + `prefers-color-scheme: dark` 深色令牌）、`ui.css`（焦点环、列表行、动效关键帧、reduced-motion）、`app.css`（入口与 body）。
- `src/components`：基础组件；`ui/` 为 shadcn-vue 拷入件（仅 Switch，已改系统风格）。
- `src/features/ai`：AI 会话页，`mock/` 放虚构数据。`src/features/tasks`：任务占位页（无 mock）。`src/features/{work-items,settings}`：真实接口页面。feature 之间不互相引用内部文件。
- `src/shared/cn.ts`：类名合并。注意不能放 `src/lib/`（仓库根 `.gitignore` 的 `lib/` 规则会让它不入库）。
- `src/api`、`src/stores`：连接、客户端、事件、Pinia（`backend` 连接/告警；`ui` 检查器开合，开合状态存 localStorage `toolbox.ui.inspector`，只存布尔值）。
- 测试在 `tests/unit`；`tests/independent` 为独立验证用例目录（含测试子 agent 写的 `r1-*.test.ts`）。`pnpm test` 不依赖 `dist/`；产物检查用 `pnpm guard:dist`（build 之后）。测试夹具 `tests/unit/boot.ts`：`boot()` 起连接，`bootUnconnected()` 不调用 `runtime.start()`，`openConnection()` 打开侧栏连接状态弹出层（告警演示开关在里面）。

## 设计令牌与深色模式

令牌在 `src/design/tokens.css`，数值参考 `docs/modernization/design/b-native/`（只作参考，未拷贝）：

- 浅色：窗口 `#FFFFFF`、侧栏 `#EEEDF1`、检查器 `#F7F7F9`、设置内容底 `#F5F5F7`、分隔线 `#E5E5EA`、正文 `#1D1D1F`、次要 `#6E6E73`、强调 `#0A63D6`（白字）。
- 深色（跟随系统，本版不做手动切换）：窗口 `#121315`、侧栏 `#0E0F11`、列表 `#141517`、检查器 `#17181B`、正文 `#ECEDEF`、强调 `#C6F432`（其上文字 `#14161A`，绿色不作文字色）。
- `--mute-tint`：侧栏、控件底、选中未聚焦行上用的次要文字（`#6E6E73` 在这些面上不足 4.5:1，故加深到 `#636368`）；运行状态「已停用」文字同理加深为 `#65656A`。
- 运行状态八态（排队/运行中/停止中/成功/失败/已取消/需核实/已停用）与提示横幅（信息/警告/错误）各有底、文字、圆点（描边）令牌，深浅两套，均过 4.5:1。
- 字体：系统字体栈（SF Pro + PingFang SC），等宽 SF Mono 只用于编号、提交、路径、命令、日志；不再打包任何字体。
- 字号 22/15/14/13/12/11；圆角 6/7/10/12；间距 4/8/12/16/20/28；控件高 28；顶栏高 52。

## 组件清单（`src/components`）

Pane（纯色面，`surface`）· SegmentedControl（Reka Tabs，横向分段/页签，`orientation="vertical"` 为设置分区列表；可带计数；传默认插槽时每页签配 tabpanel，传 `panelId` 时 aria-controls 指向页面容器）· Button（primary/default/destructive/plain，高 28）· ToolbarButton（无底色，按下态，必须 `label`）· TextField · SearchField（⌘K/Ctrl+K 聚焦，Esc 失焦）· Tag（中性小标签）· StatusDot（ok/run/warn/idle）· StatusPill（八态，文案见 `pill.ts`）· Banner（info/warn/error，贴在所属区域内）· ApprovalBar（Y/A/N，输入框聚焦时不响应，发出 `decide`）· Inspector（Teleport 进壳的检查器）· InspectorToggle（顶栏开关，`aria-pressed`）· Sidebar（分组导航）· ConnectionStatus（侧栏底部状态行 + 弹出层：后端状态、pid、心跳延迟、告警演示开关）· AlertToggle · ListRow（两行；选中聚焦=强调底，选中未聚焦=灰底，由 `.b-list:focus-within` 区分）· EmptyState · Skeleton · Sheet（Reka Dialog 确认单，焦点陷阱，Esc 关闭；设置页删除与导入确认、任务执行计划与取消均已使用 Sheet）。

## 告警

状态只来自 store 的 `alert`（`system.alert` / `system.hello`）。告警时：页面区顶部出现 warn Banner（`reason`，缺省给默认文案），侧栏连接状态行变橙；无遮罩，不拦截操作。

## 任务页（S3-C）

`/tasks` 已按 `docs/modernization/design/b-native/B-Tasks.dc.html` 实现完整业务流与真实后端对接：

- 任务列表：搜索、启用过滤、两行 ListRow、状态 StatusPill 八态取真实 active run / 最近 run；
- 任务 CRUD：新建 / 编辑 / 删除 / 排序（409 冲突刷新提示，未知字段保留）；
- 执行计划预检（preflight）：弹出 Sheet 确认，展示分支、target、steps、不可撤回副作用警告，必选确认旧应用空闲勾选（`ack_old_app_idle`）；
- 三种操作：`sync_build_release` / `deploy_only` / `rollback`（带 offset 1-5 选择）；
- 幂等启动：一次确认会话派发单一随机 `request_id`，防止双击重复启动；
- 运行详情与历史：运行记录列表、步骤列表（StepList）、取消运行（Cancel）、unknown 态核查（Reconcile）与只读核对；
- 日志同步器（`useRunLogs`）：WS 订阅（`run.event`）先订阅后 HTTP 补齐，连续 `run_seq` 去重与乱序缓冲，切换运行退订，组件卸载清理订阅且不中断后端任务；日志纯文本渲染（无 `v-html`、不解析 ANSI），token 不外泄；
- 存储：localStorage 仅持久化选中的 `task_id`，草稿与日志不进持久化；
- 侧栏任务角标：真实活动运行数（`${count} 运行中`，无活动运行则不显示）。

## mock 位置

mock 只在 `src/features/ai/mock/`。AI 页只调用 `useAiSessions()`（会话、对话、审批 Y/A/N 按会话 id 隔离；审批目前只改 mock 状态）。换真实接口时保持组合式的返回形状，内部换成 `useQuery` + `runtime.api()`（见 `components/ConnectionStatus.vue` 的 `/health` 查询）。

## 来源

视觉用系统字体与自绘组件，无第三方视觉来源，见 `../THIRD_PARTY.md`。设计参考见 `docs/modernization/design/b-native/`（只作参考，未拷贝）。

## 工单页（S2-B）

- 取数：vue-query，键 `['work-items','ado']` 与 `['work-items','p',projectId,...]`；`staleTime` 30s、不因窗口聚焦重取、列表栏「刷新」强制重取；切换项目清掉旧项目查询；`settings.changed` 使全部 `work-items` 查询失效。看板列固定五列（默认「开发中」），只请求当前列；筛选与分页（10/50/100）在前端。
- `localStorage`（键 `toolbox.work-items.selection`）只存 `{project_id, column}`，读写 try/catch。
- 外部 HTML：后端 nh3 清洗后，前端 `components/safe-html.ts`（DOMPurify 显式白名单）再清洗，`components/SafeHtml.vue` 渲染。`<img>` 无 src，只有 `data-media-id`；`components/media.ts` 的页面级缓存带 Bearer 取字节生成 `blob:` URL，同一详情内相同 id 复用，详情卸载/切换工单或项目时 `URL.revokeObjectURL`（含中止进行中的请求）。token 不进任何 URL/DOM/存储。
- 链接：点击一律拦截（`components/open-external.ts`），Tauri 内用 opener 插件，`pnpm dev:web` 下 `window.open(url,'_blank','noopener')`；只放行 http(s)（opener 的 capability scope 同样只含 `http://*`、`https://*`），WebView 自身永不导航。mailto 在两种环境下都不打开。
- 检查器列出状态、优先级、指派、看板列、严重度、区域、迭代、标签；其下 AI 分析面板整体禁用（「即将推出」，S5 提供）。详情顶栏有项目、指派人、在浏览器打开与检查器开关。
- 未在真实环境验证：Tauri 内 opener 与 blob 图片渲染、真实 ADO。
