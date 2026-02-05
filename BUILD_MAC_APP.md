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

## Move to Applications (optional)

```bash
cp -R dist/代码工具箱.app /Applications/
```

If you move the repo to another path, rebuild with:

```bash
REPO_DIR=/path/to/my-own-script bash pack_mac_app.sh
```
