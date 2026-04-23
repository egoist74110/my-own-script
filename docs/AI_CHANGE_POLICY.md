# AI 改动准入规则

## 目标

在本地 AI 使用 MCP 读取工单并尝试改代码前，先执行一轮策略评估：

- 是否允许自动改
- 是否必须人工复核
- 是否只能分析不能改

## 策略文件

当前策略文件：

- `config/ai_change_policy.yaml`

## 当前策略入口

当前 MCP server 已提供工具：

- `ado_evaluate_change_policy`

建议使用顺序：

1. 先调用 `ado_evaluate_change_policy`
2. 若结果为 `allow`，再继续改代码
3. 若结果为 `review`，先人工确认范围
4. 若结果为 `deny`，只允许分析，不允许自动改代码

## 当前默认规则

### 自动放行类型

- `Bug`
- `缺陷`
- `用户情景`

### 需人工复核

- `任务`
- `Task`
- 未提供目标文件
- 命中 review 关键词
- 命中 review 路径
- 修改文件数超过阈值

### 禁止自动修改

- 命中高风险关键词
- 命中禁止路径

## 默认禁止路径

- `app_ado/secrets.py`
- `app_ado/tg_control.py`
- `app_ado/ado_release_http.py`
- `app_ado/ado_build_http.py`
- `release_github.sh`
- `pack_mac_app.sh`
- `pack_mac_dmg.sh`

## 示例

### 只按工单评估

```text
先评估 ADO 工单 4563 是否允许 AI 自动修改代码
```

### 带目标文件评估

```text
先评估 ADO 工单 4563 是否允许 AI 修改以下文件：
- src/views/query.vue
- src/components/SearchForm.vue
```

## 说明

- 这套规则是本地规则，不依赖 ADO 服务端。
- MCP 负责提供工单事实数据，策略负责判断是否允许进入自动改代码流程。
- 最终合并责任仍然在人，不归属于 AI。
