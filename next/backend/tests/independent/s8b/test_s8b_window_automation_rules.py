"""Independent pure-function contracts for S8-B window automation."""

import pytest

from toolbox_backend.adapters.window_automation import (
    Candidate,
    ClickBudget,
    Rect,
    choose_candidate,
    filter_windows,
)


def test_rect_contains_only_points_in_its_half_open_bounds():
    rect = Rect(x=10, y=20, width=100, height=50)

    assert rect.contains(10, 20)
    assert rect.contains(109.99, 69.99)
    assert not rect.contains(9.99, 20)
    assert not rect.contains(110, 40)
    assert not rect.contains(20, 70)


@pytest.mark.parametrize("mode", ["connect", "connect_update"])
@pytest.mark.parametrize(
    "text",
    ["Cancel", "Skip", "Disconnect", "Connected to VPN", "Change Network", "Cancel Connect"],
)
def test_dangerous_or_non_action_text_is_never_selected_even_if_it_contains_connect(mode, text):
    candidate = Candidate(text=text, x=20, y=20)

    assert choose_candidate([candidate], [Rect(0, 0, 100, 100)], mode, ClickBudget()) is None


def test_connect_mode_only_selects_connect_or_reconnect_and_text_is_bounded():
    rect = Rect(0, 0, 100, 100)
    for text in ("Update", "Install", "Restart", "Connected", "Please Connect now"):
        assert choose_candidate([Candidate(text, 10, 10)], [rect], "connect", ClickBudget()) is None

    assert choose_candidate([Candidate("Reconnect", 10, 10)], [rect], "connect", ClickBudget())
    assert choose_candidate([Candidate("Connect", 10, 10)], [rect], "connect", ClickBudget())
    assert choose_candidate([Candidate("Connect" + " " * 22, 10, 10)], [rect], "connect", ClickBudget()) is None


def test_connect_update_allows_connect_and_update_actions_only_within_24_chars():
    rect = Rect(0, 0, 100, 100)
    budget = ClickBudget()
    for text in ("Connect", "Reconnect", "Update", "Install", "Restart"):
        assert choose_candidate([Candidate(text, 10, 10)], [rect], "connect_update", budget)
    assert choose_candidate([Candidate("Install" + " " * 18, 10, 10)], [rect], "connect_update", budget) is None


def test_click_budget_caps_total_at_eight_and_each_button_at_two():
    budget = ClickBudget()
    assert budget.allow("Connect")
    budget.record("Connect")
    assert budget.allow("Connect")
    budget.record("Connect")
    assert not budget.allow("Connect")
    for text in ("Update", "Install", "Restart", "Reconnect", "Refresh", "Continue"):
        assert budget.allow(text)
        budget.record(text)
    assert not budget.allow("Update")
    assert not budget.allow("Restart")
    assert not budget.allow("Another")


def test_window_filter_requires_matching_owner_layer_zero_and_onscreen():
    windows = [
        {"kCGWindowOwnerPID": 41, "kCGWindowLayer": 0, "kCGWindowIsOnscreen": True, "id": "match"},
        {"kCGWindowOwnerPID": 42, "kCGWindowLayer": 0, "kCGWindowIsOnscreen": True, "id": "other-pid"},
        {"kCGWindowOwnerPID": 41, "kCGWindowLayer": 1, "kCGWindowIsOnscreen": True, "id": "overlay"},
        {"kCGWindowOwnerPID": 41, "kCGWindowLayer": 0, "kCGWindowIsOnscreen": False, "id": "offscreen"},
        {"kCGWindowOwnerPID": 41, "kCGWindowLayer": 0, "id": "onscreen-missing"},
    ]

    assert filter_windows(windows, owner_pid=41) == [windows[0]]


@pytest.mark.parametrize(
    "rect",
    [
        Rect(0, 0, 0, 10),
        Rect(0, 0, 10, 0),
        Rect(0, 0, -1, 10),
        Rect(0, 0, 10, -1),
        Rect(float("nan"), 0, 10, 10),
        Rect(0, float("inf"), 10, 10),
        Rect(0, 0, float("inf"), 10),
        Rect(0, 0, 10, float("nan")),
    ],
)
def test_invalid_or_nonfinite_rectangles_never_contain_points(rect):
    assert not rect.contains(1, 1)


@pytest.mark.parametrize(
    ("x", "y"),
    [
        (float("nan"), 10),
        (10, float("nan")),
        (float("inf"), 10),
        (10, float("-inf")),
    ],
)
def test_rect_contains_rejects_nonfinite_candidate_coordinates(x, y):
    assert not Rect(0, 0, 100, 100).contains(x, y)


def test_rect_edge_coordinates_are_consistently_inclusive_then_exclusive():
    rect = Rect(5, 7, 3, 4)

    assert rect.contains(5, 7)
    assert rect.contains(7.999, 10.999)
    assert not rect.contains(8, 8)
    assert not rect.contains(6, 11)
