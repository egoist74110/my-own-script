from __future__ import annotations


def stop_task_buttons(items: list[tuple[str, str]]) -> dict:
    """items: [(task_id, label)]"""
    kb: list[list[dict]] = []
    for tid, label in items:
        kb.append([{ "text": f"停止：{label}", "callback_data": f"stp:{tid}" }])
    kb.append([{ "text": "取消（不停止）", "callback_data": "stp_cancel" }])
    return {"inline_keyboard": kb}
