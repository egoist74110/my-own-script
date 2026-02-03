# runner

A pure-Python **remote release execution runner** (currently stubbed providers) with a strict whitelist from `tasks.yaml`.

## Requirements

- Python **3.11+**

## Install

Using `pip` (editable):

```bash
cd runner
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

### publish

```bash
runner publish web prod main
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
runner build web main
```

### status

```bash
runner status gh:...
```

### logs

```bash
runner logs gh:... --lines 100
```

### setup

Interactive setup:

```bash
runner setup
```

- Tokens are stored using `keyring` under service name `runner`.
- Env var override priority:
  1. `GITHUB_TOKEN` / `AZURE_DEVOPS_TOKEN`
  2. keyring entries: `runner/github_token`, `runner/azure_token`
  3. otherwise error + suggest `runner setup`

### config show

```bash
runner config show
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
- Storage uses SQLite in `~/.local/share/runner/runner.sqlite` (macOS/Linux).
