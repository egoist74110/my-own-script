from __future__ import annotations


def run_mode_buttons(task_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "构建 + 发布（完整流程）", "callback_data": f"runmode:build:{task_id}"},
            ],
            [
                {"text": "仅发布（使用最新构建）", "callback_data": f"runmode:deploy:{task_id}"},
            ],
            [
                {"text": "取消", "callback_data": "runmode:cancel"},
            ],
        ]
    }
