"""Whole window runs use fake OCR, window lists, clicks and a deterministic clock."""

import asyncio
from types import SimpleNamespace

import pytest

from toolbox_backend.adapters.window_automation import Candidate, WindowAutomation
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.vpn import VpnConfig


class Native:
    def __init__(self, texts):
        self.texts, self.clicked = iter(texts), []
        self.foreground = True
        self.owner = 41
        self.change_owner = False

    def permissions(self):
        return {"screen_recording": True, "accessibility": True}

    def windows(self):
        return [
            dict(
                kCGWindowOwnerPID=self.owner,
                kCGWindowLayer=0,
                kCGWindowIsOnscreen=True,
                kCGWindowBounds=dict(X=0, Y=0, Width=100, Height=100),
            )
        ]

    def safe_to_click(self, pid, rects):
        return self.foreground

    def candidates(self, rects):
        if self.change_owner:
            self.owner = 42
        return [Candidate(next(self.texts, "Update"), 20, 20)]

    def click(self, x, y):
        self.clicked.append((x, y))


class Store:
    async def read(self):
        return SimpleNamespace(vpn=VpnConfig())


class Client:
    def __init__(self, clock):
        self.clock, self.surfaces = clock, []

    def resolve(self, bundle):
        return object()

    async def processes(self, app):
        return [(41, "start", "/fake/app")]

    async def open(self, bundle):
        self.surfaces.append(self.clock[0])


def window(native):
    now = [0]
    client = Client(now)

    async def sleep(delay):
        now[0] += delay
        await asyncio.sleep(0)

    return WindowAutomation(
        Store(), client, native=native, clock=lambda: now[0], sleep=sleep
    ), client


async def test_run_never_exceeds_eight_clicks():
    native = Native(
        [
            "Update",
            "Install",
            "Restart",
            "Relaunch",
            "Download",
            "Update Now",
            "Upgrade",
            "Update & Restart",
            "Connect",
        ]
    )
    automation, _ = window(native)
    assert await automation.connect("connect_update") == "update"
    assert len(native.clicked) == 8


async def test_same_button_limit_and_surface_throttle_hold_for_entire_run():
    native = Native(["Update"] * 100)
    automation, client = window(native)
    assert await automation.connect("connect_update") == "update"
    assert len(native.clicked) == 2
    assert len(client.surfaces) > 1
    assert all(
        right - left >= 30
        for left, right in zip(client.surfaces, client.surfaces[1:], strict=False)
    )


@pytest.mark.parametrize("changed_owner", [False, True])
async def test_foreground_or_ownership_change_prevents_click(changed_owner):
    native = Native(["Connect"])
    native.foreground = changed_owner
    native.change_owner = changed_owner
    automation, _ = window(native)
    with pytest.raises(SettingsError) as exc:
        await automation.connect("connect")
    assert exc.value.code == "window_not_foreground"
    assert native.clicked == []


async def test_wrong_owner_window_is_explicitly_unavailable():
    native = Native(["Connect"])
    native.owner = 42
    automation, _ = window(native)
    with pytest.raises(SettingsError) as exc:
        await automation.connect("connect")
    assert exc.value.code == "window_unavailable"
    assert native.clicked == []
