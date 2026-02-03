# my-own-script

A pure-Python **remote release execution runner** (currently stubbed providers) with a strict whitelist from `tasks.yaml`.

## Requirements

- Python **3.11+**

## Install

Using `pip` (editable):

```bash
cd my-own-script
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configure tasks

Copy the example file:

```bash
cp tasks.example.yaml tasks.yaml
```

Edit `tasks.yaml` to define allowed apps, providers, envs, and defaults.

## Commands

## UI (PySide6)

Install deps then run:

```bash
my-own-script-ui
```

See `ui_app/README_UI.md`.

## CLI Commands

### publish

```bash
my-own-script publish web prod main
```

Outputs **JSON lines** (one JSON object per line):

1) queued
```json
{"job_id":"gh:...","app":"web","action":"publish","env":"prod","ref":"main","status":"queued"}
```

2) final
```json
{"job_id":"gh:...","status":"success"}
```

### build

```bash
my-own-script build web main
```

### status

```bash
my-own-script status gh:...
```

### logs

```bash
my-own-script logs gh:... --lines 100
```

### setup

Interactive setup:

```bash
my-own-script setup
```

- Tokens are stored using `keyring` under service name `my-own-script`.
- Env var override priority:
  1. `GITHUB_TOKEN` / `AZURE_DEVOPS_TOKEN`
  2. keyring entries: `my-own-script/github_token`, `my-own-script/azure_token` (back-compat read: `runner/github_token`, `runner/azure_token`)
  3. otherwise error + suggest `my-own-script setup`

### config show

```bash
my-own-script config show
```

Prints JSON showing what is configured (never prints token values).

## Notifier integration

Currently `runner_app/notifiers/openclaw.py` is a stub that prints:

```
[openclaw] would notify telegram: ...
```

A future implementation can call OpenClaw via:

```python
subprocess.run(["openclaw", "notify", ...])
```

## Notes

- Providers (`github`, `azure`) are **stubs** now. They return fake run ids and URLs.
- Storage uses SQLite in `~/.local/share/my-own-script/my-own-script.sqlite` (macOS/Linux).
