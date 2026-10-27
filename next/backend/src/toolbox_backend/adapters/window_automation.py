"""Native screen automation behind one injectable boundary; no frame/text persistence."""

import asyncio
import math
import sys
import time
from dataclasses import dataclass, field

from toolbox_backend.domain.errors import SettingsError


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    def contains(self, x, y):
        return (
            all(math.isfinite(v) for v in (self.x, self.y, self.width, self.height, x, y))
            and self.width > 0
            and self.height > 0
            and (self.x <= x < self.x + self.width and self.y <= y < self.y + self.height)
        )


@dataclass(frozen=True)
class Candidate:
    text: str
    x: float
    y: float


@dataclass
class ClickBudget:
    total: int = 0
    buttons: dict = field(default_factory=dict)

    def allow(self, text):
        return self.total < 8 and self.buttons.get(text.strip().lower(), 0) < 2

    def record(self, text):
        if not self.allow(text):
            return False
        self.total += 1
        key = text.strip().lower()
        self.buttons[key] = self.buttons.get(key, 0) + 1
        return True


NEGATIVE = (
    "later",
    "not now",
    "skip",
    "remind",
    "cancel",
    "dismiss",
    "close",
    "no thanks",
    "snooze",
    "ignore",
    "next time",
    "disconnect",
    "connected to",
    "change network",
)
UPDATE = ("install", "restart", "relaunch", "download", "update now", "update &", "upgrade")


def choose_candidate(candidates, rects, mode, budget):
    if mode not in ("connect", "connect_update"):
        return None
    for item in candidates:
        text = item.text.strip().lower()
        if (
            not text
            or len(item.text) > 24
            or any(word in text for word in NEGATIVE)
            or not any(rect.contains(item.x, item.y) for rect in rects)
            or not budget.allow(text)
        ):
            continue
        if text in ("connect", "reconnect") or (
            mode == "connect_update" and (text == "update" or any(word in text for word in UPDATE))
        ):
            return item
    return None


def filter_windows(windows, owner_pid):
    return [
        window
        for window in windows
        if (
            window.get("kCGWindowOwnerPID") == owner_pid
            and window.get("kCGWindowLayer") == 0
            and window.get("kCGWindowIsOnscreen") is True
        )
    ]


def window_rects(windows, owner_pid):
    result = []
    for window in filter_windows(windows, owner_pid):
        bounds = window.get("kCGWindowBounds", {})
        try:
            rect = Rect(*(float(bounds[key]) for key in ("X", "Y", "Width", "Height")))
        except KeyError, TypeError, ValueError:
            continue
        if rect.contains(rect.x, rect.y):
            result.append(rect)
    return result


def ocr_point(rect, box):
    """Vision normalized bottom-left coordinates -> Quartz global top-left points."""
    x, y, width, height = box
    return rect.x + (x + width / 2) * rect.width, rect.y + (1 - y - height / 2) * rect.height


class MacNative:
    def permissions(self):
        if sys.platform != "darwin":
            return {"screen_recording": False, "accessibility": False}
        try:
            from ApplicationServices import AXIsProcessTrusted
            from Quartz import CGPreflightScreenCaptureAccess

            return {
                "screen_recording": bool(CGPreflightScreenCaptureAccess()),
                "accessibility": bool(AXIsProcessTrusted()),
            }
        except ImportError:
            return {"screen_recording": False, "accessibility": False}

    def windows(self):
        import Quartz as Q

        return (
            Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionOnScreenOnly, Q.kCGNullWindowID) or []
        )

    def safe_to_click(self, pid, rects):
        import Quartz as Q
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        point = Q.CGEventGetLocation(Q.CGEventCreate(None))
        return bool(
            app
            and app.processIdentifier() == pid
            and any(rect.contains(point.x, point.y) for rect in rects)
        )

    def candidates(self, rects):
        import Quartz as Q
        import Vision
        from objc import autorelease_pool

        candidates = []
        with autorelease_pool():
            for rect in rects:
                frame = Q.CGWindowListCreateImage(
                    Q.CGRectMake(rect.x, rect.y, rect.width, rect.height),
                    Q.kCGWindowListOptionOnScreenOnly,
                    Q.kCGNullWindowID,
                    Q.kCGWindowImageDefault,
                )
                if frame is None:
                    continue
                request = Vision.VNRecognizeTextRequest.alloc().init()
                request.setRecognitionLanguages_(["en-US"])
                request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
                handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(frame, {})
                ok, error = handler.performRequests_error_([request], None)
                if not ok or error:
                    continue
                for observation in request.results() or []:
                    top = observation.topCandidates_(1)
                    if not top:
                        continue
                    box = observation.boundingBox()
                    x, y = ocr_point(
                        rect, (box.origin.x, box.origin.y, box.size.width, box.size.height)
                    )
                    candidates.append(Candidate(str(top[0].string()), x, y))
        return candidates

    def click(self, x, y):
        import Quartz as Q

        for kind in (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp):
            event = Q.CGEventCreateMouseEvent(None, kind, (x, y), Q.kCGMouseButtonLeft)
            Q.CGEventPost(Q.kCGHIDEventTap, event)


class WindowAutomation:
    def __init__(self, store, client, *, native=None, sleep=asyncio.sleep, clock=time.monotonic):
        self.store, self.client, self.native = store, client, native or MacNative()
        self.sleep, self.clock = sleep, clock
        self.last_surface = float("-inf")

    async def permissions(self):
        # Probe in this backend process; never request permission/prompt the user.
        values = self.native.permissions()
        return {
            key: "granted" if values.get(key) is True else "denied"
            for key in ("screen_recording", "accessibility")
        }

    async def connect(self, mode):
        if mode == "off":
            return "off"
        if not all(value == "granted" for value in (await self.permissions()).values()):
            raise SettingsError("window_permission_missing", "窗口自动化所需权限未就绪", 409)
        if sys.platform != "darwin" and isinstance(self.native, MacNative):
            raise SettingsError("window_permission_missing", "窗口自动化仅支持 macOS", 409)
        config = (await self.store.read()).vpn
        app = self.client.resolve(config.client.bundle_id)
        rows = await self.client.processes(app) if app else []
        if not rows:
            raise SettingsError("window_unavailable", "未找到客户端主进程", 409)
        pid = rows[0][0]
        budget, updated = ClickBudget(), False
        deadline = self.clock() + (180 if mode == "connect_update" else 30)
        while self.clock() < deadline and budget.total < 8:
            if self.clock() - self.last_surface >= 30:
                await self.client.open(config.client.bundle_id)
                self.last_surface = self.clock()
            rects = window_rects(self.native.windows(), pid)
            if not rects:
                raise SettingsError("window_unavailable", "客户端窗口不在屏幕上", 409)
            if not self.native.safe_to_click(pid, rects):
                raise SettingsError(
                    "window_not_foreground", "客户端未在前台或鼠标不在客户端窗口内", 409
                )
            item = choose_candidate(self.native.candidates(rects), rects, mode, budget)
            if item:
                # Re-read ownership/frontmost/mouse immediately before posting input.
                current = window_rects(self.native.windows(), pid)
                if not any(
                    rect.contains(item.x, item.y) for rect in current
                ) or not self.native.safe_to_click(pid, current):
                    raise SettingsError("window_not_foreground", "窗口状态已改变", 409)
                budget.record(item.text)
                self.native.click(item.x, item.y)
                if item.text.strip().lower() in ("connect", "reconnect"):
                    return "update" if updated else "connect"
                updated = True
            elif not updated:
                return "none"
            await self.sleep(4)
        return "update" if updated else "none"
