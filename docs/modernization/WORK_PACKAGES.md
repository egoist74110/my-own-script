# 工作包（阶段 0/1 与新产品切片）

- plan_id: modernization-20261021
- revision: 11（2026-10-26 S6 十一项待决按推荐确认；此前 10：S5 十项待决按推荐确认）
- 2026-10-26：S0–S5、R1 与阶段 0/1 的合同已原样移入 [archive/](archive/README.md)；本文件只保留当前切片。
- base: c349243286d27ae82943a4381951f9f3b041b7d1 + 账本所列用户修改
- executor_autonomy: standard
- max_same_failure_attempts: 2
- delivery: 阶段 0/1 为本地文件与验证报告；S0 起用户授权在 `rewrite/next` 本地提交，不 push/merge/publish/deploy
- workflow: [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md)
- 状态、真实署名和检查结果只写 [PROGRESS.md](PROGRESS.md)，不能在本文件预填通过。
- 2026-10-22：方向改为前后端分离重写。WP-03、WP-11..16 的处置已由用户确认（见 [MIGRATION_PLAN.md §4](MIGRATION_PLAN.md)）。新产品切片的合同派工前追加到本文件，切片完成后移入 archive。

# 新产品切片

切片顺序与“搬完”标准见 [MIGRATION_PLAN.md](MIGRATION_PLAN.md)。新代码只在 `next/` 下；`next/` 以外的旧代码只读，不 import。

合同中引用的已归档小节（如「S0 已定接口」「S1-A 主控裁决」「协议核对结论」、S4/S5 所有权切换步骤）按 [archive/README.md](archive/README.md) 的「常被引用的小节」表定位，只读对应文件的那一节。

当前无进行中的切片（S6 已于 2026-10-26 集成验收并归档到 [archive/work-packages/S6.md](archive/work-packages/S6.md)）。下一切片 S7 服务管理的合同待主控起草。
