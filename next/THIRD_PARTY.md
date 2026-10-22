# 第三方来源与许可

## 视觉语言（AGPL-3.0）

TOOLBOX 的“工业 HUD”视觉语言（配色令牌结构、`--denied` 常态/告警混色方式、磨砂档案面板、
细线与微型编号、WARNING 告警框、两步确认按钮的风格）取自开源项目
rhine-lock（https://github.com/tmc5csxr9m-cpu/rhine-lock，AGPL-3.0-or-later，参考提交 `a4df68c`），
本仓库同为 AGPL-3.0 兼容协议。

| 本仓库文件 | 来源与方式 |
| --- | --- |
| `next/desktop/src/design/tokens.css` | 数值照搬设计稿 `Hud-Main` 的 `.hud` 令牌；设计稿的视觉语言源自上述项目。文字灰改为 `#5f5c57`（对比度修正），微型字号 >= 10px。未复制其源码文件。 |
| `next/desktop/src/design/hud.css` | 按设计稿 `.chip/.micro/.glass/.plate/.smoke` 与关键帧重写为独立 CSS。未复制其源码文件。 |
| `next/desktop/src/components/WarningBox.vue` | 依设计稿 WARNING 框重写为 Vue 组件。 |

未复制、未引入：原作品牌名称与标志、∞ 标志的 SVG / 生成脚本 / 纹理（`gen_logo.py`、`card.png`、`hex.png`）、背景音乐。
∞ 主视觉为自绘占位（双纽线线框 + 双环，标注 PLACEHOLDER）。
本表仅登记“视觉语言/令牌”层面的来源；若后续直接复制或改写其源码文件，须在该文件头部加上
`Portions derived from rhine-lock (https://github.com/tmc5csxr9m-cpu/rhine-lock), Copyright (C) its authors, AGPL-3.0-or-later` 并在本表登记文件与来源提交。

## 字体（SIL OFL 1.1）

经 `@fontsource/montserrat`、`@fontsource/jetbrains-mono` 随应用离线打包，不连接任何在线字体服务。

## npm 依赖

以 `next/desktop/pnpm-lock.yaml` 为准（Vue、Reka UI、Tailwind CSS、openapi-fetch 等，均为 MIT / Apache-2.0 等宽松许可）。
`src/components/ui/switch` 按 shadcn-vue（MIT）的 Switch 组件拷入并改样式。
