from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from app_ado.store import config_dir


@dataclass
class TaskRunRecord:
    ts: int
    task_id: str
    task_label: str
    triggered_by: str  # 'ui' | 'tg'
    requester_chat_id: str
    requester_username: str
    result: str  # 'success'|'fail'|'stopped'
    summary: str
    details: str = ""  # optional, truncated error/details


def history_path() -> Path:
    return config_dir() / "task_history.jsonl"


def append_record(rec: TaskRunRecord) -> None:
    p = history_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec.__dict__, ensure_ascii=False)
    with p.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_recent(task_id: str | None = None, limit: int = 50) -> list[dict]:
    p = history_path()
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            if task_id and str(j.get("task_id")) != str(task_id):
                continue
            out.append(j)
    out.sort(key=lambda x: int(x.get("ts") or 0), reverse=True)
    return out[:limit]


def fmt_ts(ts: int) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except Exception:
        return str(ts)
