# Build macOS .app (wrapper)

This builds a lightweight `.app` bundle that launches the repo's venv Python.

- Pros: fast, works with Python 3.14 today
- Cons: not a standalone app; requires `~/my-own-script/.venv`

## Build

```bash
cd ~/my-own-script
bash dev_run.sh   # ensure venv exists
bash pack_mac_app.sh
```

Output:

- `dist/代码工具箱.app`

## Build .dmg (installer)

```bash
cd ~/my-own-script
bash pack_mac_app.sh
bash pack_mac_dmg.sh
```

Output:

- `dist/代码工具箱-<version>-mac.dmg`

## Publish to GitHub Releases (auto upload)

Prerequisite: install and login `gh` CLI.

```bash
cd ~/my-own-script
bash release_github.sh
```

This will:
- build `.app` + `.dmg`
- create or update release tag `v<version>`
- upload the `.dmg` as release asset

## Move to Applications (optional)

```bash
cp -R dist/代码工具箱.app /Applications/
```

If you move the repo to another path, rebuild with:

```bash
REPO_DIR=/path/to/my-own-script bash pack_mac_app.sh
```
