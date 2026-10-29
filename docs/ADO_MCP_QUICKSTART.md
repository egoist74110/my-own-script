# ADO Work Items MCP 接入与使用

## 当前状态

本项目内置本地 stdio MCP server：

- `next/backend/src/toolbox_backend/mcp/ado_server.py`（模块 `toolbox_backend.mcp.ado_server`，由应用内置后端 Python 运行）

接入配置由应用「MCP」页生成（API `mcp_routes.py` 的接入配置片段，含 Claude/Codex 格式），粘贴到客户端即可。Codex 示例形态（实际 command/args/数据目录以应用生成为准，不要手抄路径）：

```toml
[mcp_servers.adoWorkItems]
command = "<应用生成的 python 路径>"
args = ["-m", "toolbox_backend.mcp.ado_server", "--data-dir", "<数据目录>"]
```

查看方式：

```bash
codex mcp list
codex mcp get adoWorkItems
```

## 人类怎么用

### 1. 先在工具里配置 ADO

先在应用的设置/发布配置里配置这些内容：

- library
- project
- PAT

要求：

- PAT 已写入 macOS Keychain
- 已选中默认 library / project

MCP server 会直接复用这些本地配置，不需要在 Codex 里重复登录 ADO。

### 2. 然后直接对 Codex 下指令

最小用法：

```text
读取 ADO Bug 12345 的详情和评论
```

修 bug 用法：

```text
修复 ADO Bug 12345。
先读取工作项详情和评论，分析根因；
然后修改当前仓库代码并运行相关测试；
最后汇总修复结果。
```

### 3. 如果没有默认项目，也可以显式指定

例如让 Codex 调用时显式传：

- `library_id`
- `project_id`

后续如果需要，也可以继续扩展默认：

- `team`
- `board`

## 当前可用工具

- `ado_get_work_item`
- `ado_get_work_item_comments`
- `ado_query_work_items`
- `ado_list_board_columns`
- `ado_list_work_items_by_column`
- `ado_get_attachment`
- `ado_create_work_item`
- `ado_evaluate_change_policy`（改代码前的准入评估，见 [AI_CHANGE_POLICY](AI_CHANGE_POLICY.md)）

## 典型使用场景

### 查 bug

```text
读取 ADO Bug 12345，告诉我标题、状态、指派人、重现信息和最近评论。
```

### 修 bug

```text
修复 ADO Bug 12345。
先读取工作项详情、评论和关联信息；
再在当前仓库里定位相关代码并修复；
最后运行相关测试并总结结果。
```

### 查某个版块列

```text
读取 team=XXX、board=XXX 下“开发中”这一列的工作项。
```

## 注意事项

- 如果 Codex 能看到 MCP，但查不到数据，优先检查 PAT 权限。
- 如果工作项详情正常、评论失败，优先检查 ADO Server 的 comments API 版本兼容性。
- 如果按列查询失败，优先检查 `team` 和 `board` 的真实名字。
- 工具清单以 `next/backend/src/toolbox_backend/mcp/tools.json` 为准。

## 联调步骤

1. 在应用里确认 ADO 配置可用（MCP 页可跑自检）
2. 用一个真实 bug id 测 `ado_get_work_item`
3. 再测 `ado_get_work_item_comments`
4. 然后正式跑一次“修复 Bug 12345”
