# ADO PAT Discovery Flow (Projects/Repos/Branches/Build/Release)

> Purpose: record the proven workflow + error handling for later reference.

## Goal
From UI, use a stored PAT (Keychain) to query Azure DevOps Server REST APIs and populate dropdowns.

## Constraints observed in this environment
- Base URL: `https://azuredevops.cg1alias.com`
- ADO Server supports up to `api-version=7.0`
- Some endpoints / auth paths may advertise NTLM; QNetworkAccessManager-based requests were unstable.
- Using `httpx` in a background Python thread was stable and returned correct JSON.

## PAT storage
- PAT is never stored in config files.
- Stored in macOS Keychain via `keyring`.
- Service: `toolbox-next`（旧版 `my-own-script`，仅只读迁移）
- Key format: `azuredevops_pat:<library_id>`

## Flow
> 新版（`next/`）：旧 PySide6 的 ProjectDialog / QNAM 流程已删除，本文保留认证协议与 API 约定。实现见 `next/backend/src/toolbox_backend/adapters/ado_http.py`、`ado_read.py`（仅向已保存 library 的 origin 发送 PAT、10s/1MiB 限额、`AdoFailure` 分类：unauthorized/forbidden/not_found/redirect/tls/timeout/network/bad_response/no_credential）与发布配置发现路由 `api/release_discovery_routes.py`（repo/branches/targets/queues）。错误只回分类与脱敏信息，不回显 PAT/响应头。

### Entities
- **Library**: `{id, name, base_url}`
- **Project**: `{id, library_id, collection, project}`

### Project discovery: list projects
- 选择 Library、填 `Collection`，由后端发起 `projects` 查询（`AdoHTTP.projects`，必须用所选 library）

### Request
- Read PAT from Keychain using the selected library_id.
- Build URL:

  `GET {base_url}/{collection}/_apis/projects?api-version=7.0`

- Auth header:

  `Authorization: Basic base64(:PAT)`

- Client:
  - `httpx.Client(follow_redirects=False)`
  - Timeout: total ~10s, connect 5s.

### Success handling
- 解析 JSON：期望 `{ count, value:[ {name, id, ...}, ... ] }`；格式不符按 `bad_response` 处理。
- 前端用返回的项目名填充下拉。

### Error handling
- 非 200 / 解析失败 / 无 PAT 均映射为 `ConnectionResult.category`（见上），向界面返回分类 + 简短脱敏信息。
- 不回显 PAT、响应头或原始 body；PAT 缺失返回 `no_credential`，提示去设置里配置。

## Debugging lessons learned
- 旧 QNAM (QNetworkAccessManager) 在企业环境有认证/代理异常；改用 `httpx` 稳定（现由后端承担）。

## 其他发现端点（现由 `adapters/ado_read.py` 与发布发现路由使用）
- Repos:
  `GET {base_url}/{collection}/{project}/_apis/git/repositories?api-version=7.0`
- Branches:
  `GET {base_url}/{collection}/{project}/_apis/git/repositories/{repoId}/refs?filter=heads/&api-version=7.0`
- Pipelines:
  `GET {base_url}/{collection}/{project}/_apis/pipelines?api-version=7.0`
- Build definitions fallback:
  `GET {base_url}/{collection}/{project}/_apis/build/definitions?api-version=7.0`
- Classic release definitions:
  `GET {base_url}/{collection}/{project}/_apis/release/definitions?api-version=7.0`
- Release stages (environments):
  `GET {base_url}/{collection}/{project}/_apis/release/definitions/{defId}?api-version=7.0`
