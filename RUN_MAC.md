# Run on macOS (bootstrap)

This branch imports `ok-script` for its QFluentWidgets UI components.

> Note: upstream ok-script targets Windows automation and Python 3.12.
> For macOS bootstrap we only run the UI layer and our own app entry.

## 1) Create/activate venv

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

## 2) Install minimal deps

```bash
pip install PySide6 PySide6-Fluent-Widgets pydantic keyring
```

(Optional) YAML support for config files:

```bash
pip install pyyaml
```

## 3) Run

### One-liner (recommended)

```bash
cd ~/my-own-script && bash dev_run.sh
```

### Manual

```bash
python app_main.py
```
