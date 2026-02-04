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
- Service: `my-own-script`
- Key format: `azuredevops_pat:<library_id>`

## UI flow (current implementation)
### Entities
- **Library**: `{id, name, base_url}`
- **Project**: `{id, library_id, collection, project}`

### Project discovery: list projects
- User opens **ProjectDialog**
- User selects **Library** in dialog (important: request must use the selected library)
- User fills `Collection` (manual) and clicks **获取Projects**

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
- Parse JSON body:
  - Expect shape: `{ count, value:[ {name, id, ...}, ... ] }`
- Populate `Project` dropdown.
- Switch UI from manual Project input → Project combobox.

### Error handling
On non-200:
- Show a **modal confirm dialog** with scrollable text.
- Include:
  - library name/id
  - PAT length (only length; never echo PAT)
  - URL
  - status
  - response headers
  - body (truncated)

On JSON parse failure:
- Show modal dialog with:
  - exception message
  - body (truncated)

On missing PAT:
- Show modal dialog instructing user to set PAT in Library dialog.

## Debugging lessons learned
- QNAM (QNetworkAccessManager) produced auth/proxy anomalies in this enterprise environment.
- Running HTTP via `httpx` in a background Python thread + marshaling results back to UI avoided Qt threading crashes and native malloc/free issues.

## Next endpoints (planned)
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
