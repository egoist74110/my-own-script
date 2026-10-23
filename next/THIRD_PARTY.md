# 第三方来源与许可

## 视觉语言（方向 B「macOS 原生」）

界面使用系统字体（`-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', 'Helvetica Neue'`；等宽 `'SF Mono', ui-monospace, Menlo`），不随应用打包任何字体，也不连接任何在线字体服务。

令牌数值与结构取自项目内设计稿 `docs/modernization/design/b-native/`（仅作参考），在 `next/desktop` 中重写为独立 CSS / Vue 组件，未拷贝其 HTML 或脚本。无第三方视觉来源。

| 本仓库文件                                        | 来源与方式                            |
| ------------------------------------------------- | ------------------------------------- |
| `next/desktop/src/design/tokens.css`、`ui.css`    | 数值参考方向 B 设计稿，改写为独立 CSS |
| `next/desktop/src/components/*`、`src/features/*` | 依设计稿的结构自行重写为 Vue 组件     |

已移除：方向 E 的全部视觉（玻璃、切角、斜切、编号导航、阶段条等）与 `@fontsource/oxanium`、`@fontsource/inter`、`@fontsource/jetbrains-mono` 三个字体依赖。

## npm 依赖

以 `next/desktop/pnpm-lock.yaml` 为准（Vue、Reka UI、Tailwind CSS、openapi-fetch、lucide 图标等，均为 MIT / Apache-2.0 / ISC 等宽松许可）。
`src/components/ui/switch` 按 shadcn-vue（MIT）的 Switch 组件拷入并改样式。
