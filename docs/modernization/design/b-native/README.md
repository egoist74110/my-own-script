# 方向 B · macOS 原生设计稿（参考源码）

画布：https://claude.ai/artifact/Uno9R3vJky5oSRgvxb5D1K（用户 2026-10-23 选定 B；C「深色控制台」作为 B 的深色模式参考）。本目录是画布中方向 B 各画板的源码快照，供离线对照。

| 文件 | 屏 | Tweaks 状态 |
| --- | --- | --- |
| `B-Native.dc.html` | 工单（浅色） | 正常 / 未配置项目 / 读取中 / 出错 |
| `B-Dark.dc.html` | 工单（深色） | 同上 |
| `B-Tasks.dc.html` | 任务（S3-C 依据） | 运行中 / 确认运行 / 需要核实 / 没有任务 |
| `B-Settings.dc.html` | 设置 · ADO 连接 | 正常 / HTTP 明文警告 / 存储只读 |
| `B-AI.dc.html` | AI 会话（S5 前为 mock） | 等待审批 / 运行中 / 没有会话 |
| `B-Components.dc.html` | 组件清单（令牌、字号、组件、版式） | — |

这些是设计画布格式（`<x-dc>` 模板 + `renderVals()` 示例数据），只作视觉与结构参考，不能直接运行或拷进前端。规则见 `../../FRONTEND_STACK.md` §9，施工合同见 `../../WORK_PACKAGES.md` R1。示例数据均为虚构。画板上的交通灯只是示意，应用里由 Tauri Overlay 标题栏提供真窗口按钮。
