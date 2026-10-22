# 方向 E · 工具优先设计稿（参考源码）

画布：https://claude.ai/artifact/BYu7ZL4MEz2bBATMp1BXx2 第一页「E · 液态玻璃 × 游戏 UI」。

| 文件 | 屏 | 说明 |
| --- | --- | --- |
| `tasks.dc.html` | 任务控制台 | 属性 `alert=true` 时为告警态（顶部黑色横幅 + 出错行/检查器转橙） |
| `work-item.dc.html` | 工单 | 列表 ｜ 详情 ｜ AI 分析面板 |
| `ai-session.dc.html` | AI 会话 | 会话列表 ｜ 对话 + 内联审批条 ｜ 检查器 |

这些是设计画布格式（`<x-dc>` 模板 + `renderVals()` 示例数据），只作视觉与结构参考，不能直接运行或拷进前端。规则见 `../../FRONTEND_STACK.md` §8、§8.1。示例数据均为虚构。
