# 重写版发布配置与运行命令（v8）

实现范围：`next/backend`；桌面类型由 OpenAPI 生成。配置唯一来源是 ConfigStore `config.json` 中的 `tasks.release_configs`；`tasks.items` 是内存展开视图，不重复持久化。运行 SQLite、执行器、单次投递与核对语义不变。

| 模型 | 字段 | 说明 |
| --- | --- | --- |
| ReleaseConfig | `id`, `name`, `sort_order` | 配置标识、标题、排序 |
| ReleaseConfig | `project_id`, `repo_id`, `repo_name`, `local_repo_path` | ADO 项目、仓库与本地路径 |
| ReleaseConfig | `agent_queue_id`, `agent_queue_name` | 共享构建队列 |
| ReleaseConfig | `branches`, `targets`, `commands` | 分支目录、目标目录、运行命令；配置级 `git_flow` 已移除 |
| ReleaseBranch | `id`, `build_branch`, `update_branches`, `merges`, `push_branches` | 稳定分支 id + 原 GitFlow 全部字段；保留分支及合并规则扩展字段。同配置构建分支名不能重复 |
| ReleaseTarget | `id` + 原 DeployTarget 全部字段 | 稳定目标标识；构建类型/定义、Release 定义、环境 id 与显示名 |
| RunCommand | `id`, `name`, `tg_command`, `tg_desc`, `enabled`, `sort_order` | 原命令 id、TG 信息、启用和排序不变 |
| RunCommand | `branch_id` | 必填，必须属于当前配置的分支目录 |
| RunCommand | `update_branches`, `merges`, `push_branches`, `local_repo_path`, `agent_queue_id`, `agent_queue_name` | 命令级覆盖，均可空：`null` 沿用分支/配置；有值只对这条命令生效，空列表/空路径 = 明确清空。覆盖后有效 Git 规则非空而本地路径为空时 422 |
| RunCommand | `target_ids` | 本配置内有序、非重复目标 id，新增/修改要求 1–20 个；执行顺序与列表一致 |
| CommandView | 上述字段 + `last_run`, `active_run_id` | 继续按命令 id 查询运行概览 |

执行时使用配置共享字段、命令 `branch_id` 对应的 GitFlow、命令 `target_ids` 对应的目标展开 DynamicTask。展开结果不含 `branches`、`branch_id`、目标 id；目标统一启用，目录的兼容字段 `enabled` 不作为第二层选择开关。扩展字段保留在配置与兼容任务视图；运行计划/持久运行快照仍按现有执行字段筛选，不扩展执行协议。

## v7 → v8 迁移

启动时沿用 ConfigStore 的串行锁、文件锁、迁移前持久备份和原子替换机制。备份为 `migrations/config-v7-*.json`；旧版本按注册链依次升级（v6→v7 算法保留）。普通读取不写入、不触发迁移。迁移成功 revision 只增加一次；重复启动不再迁移、不新增备份。替换前失败保留原文件与已完成备份，临时写入文件由 ConfigStore 清理。

1. 按 `(project_id, repo_id, local_repo_path, agent_queue_id)` 完全相同分组；不再把 `git_flow` 放入配置分组条件。
2. 组内按 `(sort_order, id)` 排序，配置 id、排序及共享显示元数据取第一份，保证确定性。
3. GitFlow 全部字段（含扩展字段、合并规则扩展字段）完全相同才去重。分支 id 用配置 id + 完整 GitFlow 生成确定性 UUID。
4. 目标沿用 `(build_kind, build_id, release_id, release_stage_ids)` 去重，保留首次出现的 id 与显示元数据；环境顺序参与比较。每条命令的 `target_ids` 映射为新目录 id，保持顺序并去重。
5. 命令 id 及其他字段原样保留；只映射目标引用、增加 `branch_id`，指向原配置 GitFlow 对应的分支。
6. 组内名称均为仓库名或 `仓库名（构建分支）` 自动名时，合并名用第一份仓库名；存在自定义名称时保留排序第一份配置的名称。

同名构建分支却具有不同 GitFlow 的冲突数据不会被静默覆盖：最终模型校验失败，保留原文件，需先消除冲突再重试。

本机真实数据的**预期**是 6 个配置合并成 5 个；测试仅使用等价假数据，不读取用户真实配置文件：

| 配置名 | 分支数 | 命令数 |
| --- | ---: | ---: |
| CG_Vue_Event | 1 | 2 |
| CG_Vue_Front | 2（main / develop） | 2 |
| CG | 1 | 2 |
| CG_Vue_Vip_H5 | 1 | 1 |
| CG_Vue_Vip_H5_DCR | 1 | 1 |

历史命令没有已启用目标时仍保留空选择，执行入口要求修正，不擅自启用目标。

## API 新旧对照

所有接口沿用本地 Bearer 认证和全局 `revision` 乐观锁；写入返回 MutationResponse。路径及排序、活动运行、ACL 删除保护语义不变。

| 操作 | v7 | v8 |
| --- | --- | --- |
| 配置 GET/POST/PATCH | 配置级 `git_flow` | `branches: ReleaseBranch[]`；不再接受配置级 `git_flow` |
| 命令 GET/POST/PATCH | `target_ids` | 增加 `branch_id`；POST 必填，PATCH 未提供则保留，不能为 null |
| 删除引用中目标 | 422 `validation_error`，`目标仍被运行命令引用` | 422 `target_in_use`，message 原样保留 |
| 删除引用中分支 | 无分支目录 | 422 `branch_in_use`，`分支仍被运行命令引用` |
| 同名构建分支、外部目录 id、无效引用 | 不适用/校验错误 | 422 `validation_error` |

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| GET / POST | `/api/release-configs` | 列表 / 创建配置 |
| PUT | `/api/release-configs/order` | 全部配置 id 恰好各一次 |
| GET / PATCH / DELETE | `/api/release-configs/{config_id}` | 详情 / 局部修改 / 删除 |
| GET / POST | `/api/release-configs/{config_id}/commands` | 命令列表 / 新建 |
| PUT | `/api/release-configs/{config_id}/commands/order` | 此配置全部命令 id 恰好各一次 |
| GET / PATCH / DELETE | `/api/release-configs/{config_id}/commands/{command_id}` | 命令详情 / 修改 / 删除 |

`branches` 与 `targets` 都是整份目录替换。已有条目必须带原 id，新增省略 id；不能传其他配置的 id。PATCH 未提供的条目子字段沿用现值，扩展字段按 id 保留。保存后 GET 获取新 id，再创建/修改命令。创建配置不接受内嵌命令，可先建空目录，但创建命令前必须补齐分支和目标。

删除配置/命令时，活动运行返回 `task_active`；ACL 引用返回 `task_referenced` 及 `groups`。确认解除 ACL 后加 `detach_acl=true` 和当前 revision 重试。失败不增加 revision、不解除 ACL；运行历史保留。空配置继续阻止删除引用的 ADO 项目/库及覆盖式首次导入。

旧任务接口兼容方式：

- `GET /api/tasks` 与详情：每条命令展开为一条任务，`name` 取配置名，`git_flow` 取命令所选分支。
- `POST /api/tasks`：沿用旧请求，创建独立配置、一条分支和一条命令，服务端自动生成目录 id 与引用。
- `PATCH /api/tasks/{id}`：命令元数据和目标选择仍可修改。配置共享字段（含旧 `git_flow`）仅单命令配置可改；`git_flow` 还要求目录中只有一条分支。多命令/多分支场景请用发布配置与命令接口，避免旧表单误改共享数据。目标仍采用追加/复用，不隐式删除目录。
- `PUT /api/tasks/order` 继续排序全部命令；DELETE 删除命令并保留配置，沿用活动运行与 ACL 保护。
- preflight 仍为 `{revision, operation, rollback_offset?}`，启动仍为 `{plan_id, request_id, ack_old_app_idle:true}`；运行请求不接受临时分支/目标选择。run/cancel/events/reconcile 路径与语义不变。

## 前端接入

配置编辑器维护共享来源、分支目录、目标目录；分支编辑使用扁平字段 `build_branch/update_branches/merges/push_branches`。命令编辑器新增必选分支下拉，提交 `branch_id`，目标勾选仍提交 `target_ids`。新增分支先保存目录、重新 GET 拿 id，再保存命令。删除前可依据命令引用禁用按钮，服务端仍作最终校验；按 `target_in_use` / `branch_in_use` 显示错误，不再匹配文本。

列表与标题显示配置名；运行选择已建命令，然后走既有 preflight、确认、启动流程。ACL、运行历史、并发预约继续使用命令 id，同配置其他命令不继承权限。TG 标签保持 `配置名称：运行命令名称`。revision_conflict 时重新读取后编辑，不盲目重试覆盖。

契约来源：`next/contracts/openapi.json`；`next/desktop/src/api/schema.d.ts` 仅通过 `pnpm -s contracts:gen` 生成。此次不修改其他桌面文件；前端业务接入由前端工作包完成。

## v8 交付记录（2026-10-28）

状态：字段、迁移、配置/命令 API、旧任务兼容、引用错误码、生成契约与文档为 done；自动验收真实结果见下表。真实用户配置迁移、真实 ADO/TG/Keychain、桌面人工体验未测。无执行器或运行数据库改动，无提交、stash、分支切换。

本轮文件：

- `next/backend/src/toolbox_backend/domain/settings.py`：ReleaseBranch、branch_id、v8 模型/迁移与展开。
- `next/backend/src/toolbox_backend/adapters/config_store.py`：注册迁移、schema 版本与 v7 备份路径。
- `next/backend/src/toolbox_backend/api/release_schemas.py`：分支目录输入与命令字段；既有 release_routes 无需修改。
- `next/backend/src/toolbox_backend/services/releases.py`、`services/tasks.py`：目录及引用校验、稳定错误码、旧写兼容。
- `next/backend/tests/test_release_configs.py`：合并、去重、稳定 id、幂等、原子失败、分支快照、CRUD 与引用保护回归。
- 相邻夹具同步：`tests/test_s3_faults.py`、`tests/test_s4b_execution.py` 的配置级 GitFlow 改为分支目录。现行 schema 断言更新：`tests/test_s1_store.py`、`test_s4_lead_fixes.py`、`test_s4a_foundation.py`、`test_s5a_config.py`、`test_s5a_regressions.py`、`test_s6_config.py`、`test_s7_services.py`、`test_s8_config.py`；`tests/independent/{s1/test_s1_store_contracts.py,s4a/test_telegram_migration_acl_contract.py,s6a/test_s6a_config_and_source.py,s7a/test_s7a_config_migration.py,s8a/test_s8a_config_totp_boundaries.py}`。
- `next/contracts/openapi.json`、`next/desktop/src/api/schema.d.ts`；本文、能力索引与进度账本。

验收使用仓库内 `UV_CACHE_DIR=/Users/wesker/my-own-script-next/next/.local/uv-cache`。日志保留 `next/.local/release-configs-v8/`（Git 忽略）；测试资源使用隔离临时目录并由 fixture 清理，没有启动持久服务。

| 检查 | 实际结果 |
| --- | --- |
| `uv run pytest -q tests/test_release_configs.py` | **20 passed**；最终相邻集合也包含这 20 项 |
| `uv run pytest -q tests/test_release_configs.py tests/test_s1*.py tests/test_s3*.py tests/test_s4*.py tests/independent/s1 tests/independent/s3* tests/independent/s4* --ignore=tests/independent/s1/test_s1_live_boundaries.py` | **511 passed / 1 failed，112.18s**；唯一失败 `test_s1d_process.py::test_cr006_dev_memory_process_stderr_never_contains_pat`：本地 socket bind 被沙箱拒绝 |
| 首轮含 `test_s1_live_boundaries.py` 的相邻集合 | 该文件 **8 项 setup errors**，`no READY line (exit=1)`；隔离启动诊断已确认 `server.py::bind_socket` 抛 `PermissionError: Operation not permitted`。最终集合排除该文件，不记为通过 |
| `uv run pytest -q tests/test_contracts.py tests/independent/test_fault_contracts.py tests/test_s5a_config.py tests/test_s5a_regressions.py tests/test_s6_config.py tests/test_s7_services.py tests/test_s8_config.py tests/independent/s6a/test_s6a_config_and_source.py tests/independent/s7a/test_s7a_config_migration.py tests/independent/s8a/test_s8a_config_totp_boundaries.py` | **93 passed / 1 skipped，14.93s**，包含契约回归；skip 为既有用例 |
| `uv run python -m toolbox_backend.contracts` 与 `--check` | 生成、检查 exit 0；events 内容未变 |
| `cd next/desktop && pnpm -s contracts:gen`、`pnpm -s contracts:check` | exit 0，`contracts:check ok` |
| `uv run --project next/backend ruff check next/backend`（仓库根目录） | exit 0，All checks passed |
| `git diff --check` | exit 0，无输出 |

上表 pytest/契约命令默认在 `next/backend` 运行。首轮发现的两处旧 GitFlow 夹具与两处旧版本常量断言已适配；三项因此失败的行为用例单独复验 **3 passed**，并已包含在最终 511 项通过结果中。未运行本轮全量；沙箱外应补跑端口受限项及全量，不把专项通过替代全量验收。

偏离：无业务范围偏离。旧任务写兼容选择上述保守限制；同名构建分支但 GitFlow 不同的历史冲突采用失败保留原文件，避免丢规则。安全与一致性检查：未认证请求沿用 401；本地 Bearer 无新增角色，TG 的命令 ACL 不变；目录 id 必须属于配置，分支/路径/ADO 数字标识仍校验，未增加凭据或外部调用。所有父子目录变更在 ConfigStore 单次原子更新内完成，失败无部分引用、无 revision 增长；无新增连接、工作线程或运行时资源。

验证署名：role=build，actual_model/actual_effort=unknown，verified_by=executor，independent=false；未委派测试或审计。

## 自动发现

以下四个接口共用前缀 `/api/release-configs/discover`，沿用本地 Bearer 认证。接口只读，不保存配置、不增加 revision、不缓存；每次使用当前项目所属库的 PAT，经既有出站并发限制和 HTTP 超时访问 ADO。所有身份 id 均返回字符串。

### 1. 本地仓库 → 项目与仓库

`POST /api/release-configs/discover/repo`

请求：

```json
{"local_repo_path":"~/work/demo"}
```

响应示例：

```json
{
  "local_repo_path":"/Users/example/work/demo",
  "remote_url":"https://ado.example/DefaultCollection/产品/_git/demo",
  "project_id":"proj:demo",
  "project_label":"DefaultCollection/产品",
  "repo_id":"repo-guid",
  "repo_name":"demo",
  "default_branch":"main",
  "suggested_name":"demo",
  "existing_config_id":null,
  "reason":null
}
```

路径展开 `~` 并解析为绝对路径，必须是目录和 Git 仓库。优先读取 origin，缺少 origin 时取 Git 列出的第一个远端。仅执行带超时、固定参数的本地 Git 读取，不连接远端 Git、不执行仓库脚本。支持：

- `https://[user@]host[:port]/{collection}/{project}/_git/{repo}`（也支持用户名/密码）。
- `ssh://[user@]host[:port]/{collection}/{project}/_git/{repo}`。
- `git@host:v3/{collection}/{project}/{repo}`。
- `DefaultCollection` 作为普通集合名；支持 `/tfs/` 等前置路径，取 `_git` 前的集合与项目；集合、项目、仓库名 URL 解码。

按 Library base_url 的 hostname、显式端口及项目的 collection/project 匹配；hostname、collection、project 忽略大小写，端口必须一致，不把 SSH 端口映射为 HTTPS 端口。匹配不唯一时也不猜测凭据来源。`remote_url` 去掉用户名/密码，URL 形式同时去掉查询串和片段；SCP 形式去掉 `git@`。

未匹配时仍返回 200，`reason="project_not_matched"`，保留规范路径与安全远端，其余字段为 null。匹配后查询 ADO 仓库详情，以真实 repo_id 查找已有发布配置（忽略 id 大小写），命中则返回 `existing_config_id`。

### 2. 分支

`GET /api/release-configs/discover/branches?project_id=proj%3Ademo&repo_id=repo-guid`

```json
{"branches":["main","develop","release"],"default_branch":"main"}
```

读取仓库详情与 `refs?filter=heads/`；移除 `refs/heads/`，去重，默认分支优先，其余按名称排序。未设置默认分支时 `default_branch=null`。

### 3. 构建、Release 与建议目标

`GET /api/release-configs/discover/targets?project_id=proj%3Ademo&repo_id=repo-guid`

```json
{
  "builds":[{"id":"11","name":"demo CI","kind":"pipeline"}],
  "releases":[{
    "id":"21","name":"demo 发布","build_definition_ids":["11"],
    "environments":[{"id":"1","name":"生产"}]
  }],
  "suggested_targets":[{
    "id":null,"name":"demo 发布","enabled":true,
    "build_kind":"pipeline","build_id":"11","build_name":"demo CI",
    "release_id":"21","release_name":"demo 发布",
    "release_stage_ids":["1"],"release_stage_names":["生产"]
  }]
}
```

构建列表使用 repositoryId/TfsGit/includeAllProperties 查询并再次按 repository.id 过滤，兼容忽略筛选参数的服务器。`process.type==2` 为 `pipeline`，其他为 `build`，与执行器一致。Release 查询展开 artifacts/environments，只保留 Build artifact 引用本仓库构建的定义；同域请求沿用执行器，版本先 6.0，仅明确不支持版本时回退 7.0。

每个（构建定义，引用它的 Release 定义）生成一项建议，同名建议加 `（构建定义名）`，环境默认全选；没有关联 Release 的构建仍在 builds 中，但不生成建议。建议符合 `ReleaseTargetInput`，供用户勾选后保存；不代表执行预检已通过，现有执行器仍核验单制品等限制。

### 4. Agent 队列

`GET /api/release-configs/discover/queues?project_id=proj%3Ademo`

```json
{"queues":[{"id":"5","name":"默认队列"}]}
```

请求 `distributedtask/queues?actionFilter=Use`；按 `7.1-preview.1` → `6.0-preview.1` → `5.1-preview.1` → `5.0-preview.1` 探测。仅 400/404 或明确版本不支持时继续；认证、权限和连接失败立即返回错误。

### 错误与前端接入

错误沿用 `{"detail":{"code":"...","message":"中文说明"}}`：

| code | HTTP | 含义 |
| --- | --- | --- |
| `not_git_repo` | 422 | 路径无效、非目录、非 Git 仓库或 Git 读取失败/超时 |
| `no_remote` | 422 | 没有远端或远端 URL 不可读取 |
| `remote_not_ado` | 422 | 不支持的远端 URL |
| `project_not_matched` | 200 的 reason | 未找到唯一登记项目，非错误响应 |
| `pat_missing` | 409 | 项目所属库未配置 PAT |
| `ado_not_found` | 404 | ADO 资源或接口不存在 |
| `ado_unreachable` | 502 | 超时、网络、认证/权限或远端响应无效 |

已有来源不存在、凭据后端失败、出站繁忙及输入校验仍使用全局错误体系。PAT、认证头及原始 ADO 错误正文不返回前端。

向导顺序：**路径 → repo → 分支 → 目标 → 队列**。路径可先从已登记 local_repos 中选择，再调用 repo；`existing_config_id` 非空时可引导编辑已有配置。reason 非空时引导登记库/项目或核对端口。repo 成功后，branches/targets/queues 可分别加载与重试，单项失败不要清空其他项；来源改变时清除旧候选并忽略过期响应。用户只勾选分支、目标、环境和队列，最终仍经原有发布配置 API 保存；发现接口不接受 revision，也不会替用户保存。
