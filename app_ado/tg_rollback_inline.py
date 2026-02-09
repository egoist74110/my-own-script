from __future__ import annotations


def task_buttons(items: list[tuple[str, str]], *, prefix: str = "rb_task:") -> dict:
    """items: [(task_id, label)]"""
    keyboard = []
    for tid, label in items:
        keyboard.append([{ "text": label, "callback_data": prefix + str(tid) }])
    return {"inline_keyboard": keyboard}


def offset_buttons(max_offset: int, *, prefix: str = "rb_off:") -> dict:
    keyboard = []
    row = []
    for k in range(1, max_offset + 1):
        row.append({"text": str(k), "callback_data": prefix + str(k)})
        if len(row) >= 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([{ "text": "取消", "callback_data": "rb_cancel" }])
    return {"inline_keyboard": keyboard}


def confirm_buttons() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "确认回退", "callback_data": "rb_yes"},
                {"text": "取消", "callback_data": "rb_cancel"},
            ]
        ]
    }
