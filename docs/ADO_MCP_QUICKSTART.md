# ADO Work Items MCP 接入与使用

## 当前状态

本项目已提供本地 MCP server：

- `app_ado/mcp_ado_work_items_server.py`

已注册到当前机器的 Codex 全局配置：

- server 名称：`adoWorkItems`

## Codex 注册结果

已写入：

- `~/.codex/config.toml`

对应配置：

```toml
[mcp_servers.adoWorkItems]
command = "/Users/wesker/my-own-script/.venv/bin/python"
args = ["/Users/wesker/my-own-script/app_ado/mcp_ado_work_items_server.py"]
```

查看方式：

```bash
codex mcp list
codex mcp get adoWorkItems
```

## 人类怎么用

### 1. 先在工具里配置 ADO

先在本项目现有 UI 里配置这些内容：

- library
- project
- PAT

要求：

- PAT 已写入 macOS Keychain
- `active_library_id` 已选中
- `active_project_id` 已选中

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
- 当前还没有前端“工作项页”，现在是先打通 AI 主链路。

## 下一步

建议下一步做真实联调：

1. 在工具里确认 ADO 配置可用
2. 用一个真实 bug id 测 `ado_get_work_item`
3. 再测 `ado_get_work_item_comments`
4. 然后正式跑一次“修复 Bug 12345”
