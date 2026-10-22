# 第三方来源与许可

## 视觉语言（方向 E）

方向 E「液态玻璃 × 游戏 UI · 工具优先」的令牌数值与结构取自项目内设计稿
`docs/modernization/design/e-tool-first/`，在 `next/desktop` 中重写为独立 CSS / Vue 组件，未拷贝其 HTML 或脚本。

理念来源（S0 的工业 HUD 方向已被替代）仅保留三点：黑色块标签、微型编号、黑橙告警。该理念来自开源项目
rhine-lock（AGPL-3.0-or-later，参考提交 `a4df68c`），本仓库同为 AGPL-3.0 兼容协议。未复制其源码、图形、纹理或音频。
若后续直接复制或改写其源码文件，须在该文件头部加署名并在此登记。

| 本仓库文件                                        | 来源与方式                                        |
| ------------------------------------------------- | ------------------------------------------------- |
| `next/desktop/src/design/tokens.css`、`ui.css`    | 数值参考方向 E 设计稿的 `<style>`，改写为独立 CSS |
| `next/desktop/src/components/*`、`src/features/*` | 依设计稿的结构自行重写为 Vue 组件                 |

S0.5 移除（不再随应用提供）：`design/hud.css`、`components/WarningBox.vue`、`InfinityPlaceholder.vue`、`ClockBlock.vue`、`ConnectionBadge.vue`、`lib/clock.ts`、`features/overview`，以及 Montserrat 字体。

## 字体（SIL OFL 1.1）

经 `@fontsource/oxanium`（标题、数字、编号）、`@fontsource/inter`（正文）、`@fontsource/jetbrains-mono`（标签、微型文字）随应用离线打包，
不连接任何在线字体服务。三者均为 SIL Open Font License 1.1。已移除 `@fontsource/montserrat`。

## npm 依赖

以 `next/desktop/pnpm-lock.yaml` 为准（Vue、Reka UI、Tailwind CSS、openapi-fetch、lucide 图标等，均为 MIT / Apache-2.0 / ISC 等宽松许可）。
`src/components/ui/switch` 按 shadcn-vue（MIT）的 Switch 组件拷入并改样式。
