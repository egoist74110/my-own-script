# 前端技术选型

状态：主控提案，用户已接受 Vue 3 + Vite + Tauri 方向（2026-10-22）。具体库版本在 S0 骨架施工时锁定为当时最新稳定版并写入 lock 文件，本文不预填版本号。

## 1. 目标

用户要求“优雅、帅气、高端”，旧 UI 不保留。由此推出两条硬约束：

1. **样式必须完全自有**：不能是一眼能认出来的后台模板风（Element Plus / Ant Design 默认皮肤）。
2. **桌面原生质感**：macOS 毛玻璃侧栏、覆盖式标题栏、键盘优先、动效克制且流畅；首屏与切页不卡顿。

## 2. 选型

| 关注点 | 选择 | 理由 / 备选 |
| --- | --- | --- |
| 框架 | Vue 3（`<script setup>` + Composition API）+ TypeScript strict | 用户指定 |
| 构建 | Vite | Tauri 官方推荐组合；不采用 Nuxt（SSR、约定路由在本地 SPA 无收益） |
| 组件底座 | **Reka UI**（无样式、可访问性完整的原语）+ **shadcn-vue**（源码拷入仓库、自由修改） | 外观 100% 自控，适合做高端定制；备选 Naive UI（主题能力强但风格固定）、PrimeVue unstyled（体量大） |
| 样式 | Tailwind CSS v4 + CSS 变量设计令牌 | 令牌一处定义，亮/暗主题与强调色切换只改变量 |
| 图标 | Lucide（lucide-vue-next） | 线性风格统一，按需引入 |
| 字体 | 界面 Geist / Inter，等宽 Geist Mono / JetBrains Mono，中文回退 PingFang SC | 随应用打包，离线可用 |
| 动效 | Motion for Vue（motion-v） | 布局动画、列表进出、共享元素；遵守系统“减少动态效果” |
| 路由 | Vue Router | — |
| 服务端状态 | TanStack Query（@tanstack/vue-query） | 缓存、重试、失效；WebSocket 事件直接更新查询缓存 |
| 本地 UI 状态 | Pinia | 只放界面状态（侧栏、筛选、选中项），业务状态以后端为准 |
| API 客户端 | openapi-typescript + openapi-fetch（由后端 OpenAPI 生成） | 前后端类型单一来源 |
| 表单校验 | vee-validate + zod | — |
| 表格 / 长列表 | TanStack Table + TanStack Virtual | 工单、日志、任务历史的虚拟滚动 |
| 终端 | xterm.js（@xterm/xterm + fit / webgl 插件） | 取代旧 pyte 虚拟屏；后端持有 PTY，经 WS 传字节流 |
| 代码 / 日志 / diff 查看 | CodeMirror 6；Markdown 用 markdown-it + Shiki 高亮 | 比 Monaco 轻；AI 输出与工单描述渲染 |
| HTML 清洗 | DOMPurify（后端已先做白名单清洗） | ADO 工单 HTML、AI 输出均不可信 |
| 通知 | vue-sonner | — |
| 命令面板 | shadcn-vue Command（Reka Combobox） | ⌘K 全局搜索任务、工单、会话与操作 |
| 工具库 | VueUse | — |
| 包管理 | pnpm | 本机已有 |
| 测试 | Vitest + Vue Test Utils；Playwright 跑 Vite 页面 + MSW 模拟后端 | 不连真实后端/外部服务 |
| 规范 | ESLint（flat config，eslint-plugin-vue）+ Prettier；vue-tsc 类型检查 | Vue 生态支持最完整 |

不引入：完整组件库皮肤、CSS-in-JS、全局事件总线、第二套状态管理。暂不做 i18n（界面中文；文案集中存放，后续可接 vue-i18n）。

## 3. 桌面壳相关（Tauri 2）

- 标题栏 `titleBarStyle: Overlay`，保留红绿灯，侧栏顶部留出拖拽区。
- 侧栏使用 macOS vibrancy 窗口效果；不支持或用户关闭透明度时退回实色令牌。
- 菜单栏托盘：显示后端状态、运行中任务数、快速“显示窗口 / 退出”。
- 系统通知走 Tauri 通知插件；页面不直接调用系统 API，经 Tauri command。
- 仅开放所需 Tauri 权限（capabilities 最小化）；页面不允许任意 shell / fs。

## 4. 前端目录约定（S0 落地）

```text
next/desktop/src/
  app/            路由、布局壳、全局 provider
  design/         令牌（tokens.css）、主题、基础动效
  components/ui/  shadcn-vue 拷入组件（可改）
  components/     业务无关的复合组件
  features/<能力>/ 页面、组件、查询 hooks（tasks、work-items、ai、mcp、vpn、services、settings）
  api/            生成的类型与客户端、WS 订阅
```

每个 feature 只依赖 `api/` 与通用组件，不跨 feature 引用内部文件。

## 5. 视觉方向（下一步，由用户选择）

技术选型不决定“长什么样”。骨架之外先单独做方向稿，用户拍板后才固化令牌：

- 产出 2～3 套方向，每套包含：主界面（侧栏 + 任务总览）、工单详情、AI 会话三屏高保真稿，亮/暗两种主题。
- 每套定义：中性色阶 + 1 个强调色、字体与字号阶梯、圆角/阴影/描边、信息密度、动效节奏。
- 参考气质（仅作沟通用，不照搬）：Linear 的克制与密度、Raycast 的键盘优先、Arc 的材质感。
- 通过标准：用户选定一套；对比度满足 WCAG AA；在 1280×800 与 1728×1117 下不拥挤。

## 6. 性能底线

- 首屏可交互目标在 S0 实测后设定，不预估；路由级代码分割，终端、编辑器、Markdown 渲染按需加载。
- 长列表必须虚拟滚动；日志与 AI 流式输出按帧合并渲染。
- 隐藏页面不轮询；状态由后端事件推送（解决 D10）。


## 7. 视觉方向决定（2026-10-22）

用户选定“工业 HUD”风格，直接沿用开源项目 [rhine-lock](https://github.com/tmc5csxr9m-cpu/rhine-lock)（AGPL-3.0，与本仓库同协议）的视觉语言。设计稿：claude.ai 画布“代码工具箱 新版视觉概念”页面 D（总览 / 工单 / AI 会话 × 常态 / 告警）。

- 沿用：配色令牌（纸面 `#e7e5e1`、墨 `#111214`、橙 `#ff7b00`、青柠 `#b9e432`，以 `--denied` 0..1 用 color-mix 混入黑橙告警态）、Montserrat + JetBrains Mono（OFL）、黑色烟雾分区牌、磨砂档案面板、细线角标与微型编号、WARNING 告警框、两步确认按钮、界面音效体系。
- 状态映射：常态亮色；任务失败、附件来源被拦截、命令被策略拒绝、VPN 掉线等进入告警态。
- 不使用：RHINE LAB / 明日方舟名称与原作 ∞ 标志图形（商标）；原作不随仓库分发的配乐。品牌为 TOOLBOX，∞ 造型自绘。
- 复用其代码或音效时：保留原版权声明，在关于页与 README 注明来源；可读性修正——原作 `--mute #8b8882` 在纸面上对比度不足 4.5:1，本项目文字用 `#5f5c57`，微型字号不小于 10px。
- 选型影响：组件底座定为 Reka UI + shadcn-vue（Nuxt UI 不再考虑）；新增 Three.js（经 TresJS）做 ∞ 卡片雕塑主视觉，Web Audio 播放音效（默认关闭，可在设置开启）。Svelte 源码按 Vue 组件改写，不引入 Svelte。
