# UI (PySide6)

Run:

```bash
my-own-script-ui
```

- Left sidebar: Settings / Tasks
- Tasks page: a demo TaskCard + log panel
- Task base class: `ui_app/task_base.py`

Notes:
- Logs are written to `~/.local/share/my-own-script/ui.log`.
- Demo task runs in a QThread and streams logs back to the UI.
