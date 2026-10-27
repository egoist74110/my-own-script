"""Exercise the Playwright adapter using a fake Playwright API, without launching Chrome."""

from types import SimpleNamespace

import pytest

from toolbox_backend.adapters.window_automation import MacNative, Rect
from toolbox_backend.vpn.login_worker import (
    CHROME_ARGS,
    LoginFailure,
    PlaywrightDriver,
    login_flow,
)


class Locator:
    def __init__(self, page, selector):
        self.page, self.selector, self.first = page, selector, self

    async def fill(self, value, **kwargs):
        if self.page.missing:
            from playwright.async_api import TimeoutError

            raise TimeoutError("fake controls unavailable")
        self.page.values[self.selector] = value

    async def inner_text(self, **kwargs):
        return "US Data Residency"

    async def click(self, **kwargs):
        if self.selector == "button[type='submit']":
            self.page.state = {"workspace": "credentials", "credentials": "mfa", "mfa": "callback"}[
                self.page.state
            ]
            if self.page.state == "callback":
                for callback in self.page.cdp.handlers.values():
                    callback({"url": "S8Probe://cb#id_token=S8_FAKE_CALLBACK"})

    async def is_visible(self):
        return self.page.state == "mfa" and "one-time-code" in self.selector

    async def count(self):
        return 0


class Page:
    def __init__(self, cdp):
        self.cdp, self.state, self.values, self.missing = cdp, "workspace", {}, False

    async def goto(self, url, **kwargs):
        self.url = url

    def locator(self, selector):
        return Locator(self, selector)

    def get_by_role(self, *args, **kwargs):
        return Locator(self, "role")


class Cdp:
    def __init__(self):
        self.handlers = {}

    async def send(self, method):
        assert method == "Page.enable"

    def on(self, name, callback):
        self.handlers[name] = callback


@pytest.mark.parametrize(
    "has_seed,headless,expected", [(False, True, False), (True, True, True), (True, False, False)]
)
async def test_real_adapter_options_cdp_flow_and_memory_only_output(
    tmp_path, monkeypatch, has_seed, headless, expected
):
    import playwright.async_api as api

    import toolbox_backend.adapters.vpn_browser as browser

    cdp = Cdp()
    page, events, launched, closed = Page(cdp), [], [], []

    class Context:
        pages = [page]

        async def new_cdp_session(self, target):
            assert target is page
            return cdp

        def on(self, *args):
            pass

        async def close(self):
            closed.append("context")

    class Playwright:
        chromium = None

        async def start(self):
            return self

        async def launch_persistent_context(self, profile, **kwargs):
            launched.append((profile, kwargs))
            return Context()

        async def stop(self):
            closed.append("playwright")

    playwright = Playwright()
    playwright.chromium = playwright
    monkeypatch.setattr(api, "async_playwright", lambda: playwright)

    async def discover(pid, profile):
        return {"pid": 999998, "lstart": "Mon Oct 26 12:00:00 2026"}

    monkeypatch.setattr(browser, "discover_chrome", discover)
    options = dict(data_dir=str(tmp_path), scheme="s8probe", has_seed=has_seed, headless=headless)
    driver = PlaywrightDriver(options, lambda event, **kw: events.append((event, kw)))
    try:
        await driver.start()

        async def mfa():
            return "123456"

        result = await login_flow(
            driver,
            {"password": "S8_FAKE_PASSWORD"},
            mfa,
            lambda event, **kw: events.append((event, kw)),
        )
        assert result == "S8Probe://cb#id_token=S8_FAKE_CALLBACK"
        assert len([x for x in events if x[0] == "captured"]) == 1
        assert "S8_FAKE_PASSWORD" not in str(events)
        assert "123456" not in str(events)
        assert "S8_FAKE_CALLBACK" not in str(events)
        assert set(cdp.handlers) == {
            "Page.frameRequestedNavigation",
            "Page.frameScheduledNavigation",
        }
        assert launched[0][1]["channel"] == "chrome"
        assert launched[0][1]["headless"] is expected
        assert set(CHROME_ARGS) <= set(launched[0][1]["args"])
        assert (tmp_path / "vpn/chrome-profile").stat().st_mode & 0o777 == 0o700
        page.missing = True
        with pytest.raises(LoginFailure, match="login_selector_missing"):
            await driver.step("workspace", {})
    finally:
        await driver.close()
    assert closed == ["context", "playwright"]


_ocr_with_fake_frameworks = MacNative.candidates


def test_native_ocr_uses_pyobjc_pool_and_converts_crop_coordinates(monkeypatch):
    import sys
    from contextlib import nullcontext

    class Request:
        def init(self):
            return self

        def setRecognitionLanguages_(self, values):
            assert values == ["en-US"]

        def setRecognitionLevel_(self, value):
            pass

        def results(self):
            box = SimpleNamespace(
                origin=SimpleNamespace(x=0.2, y=0.3), size=SimpleNamespace(width=0.2, height=0.2)
            )
            return [
                SimpleNamespace(
                    topCandidates_=lambda limit: [SimpleNamespace(string=lambda: "Connect")],
                    boundingBox=lambda: box,
                )
            ]

    class Handler:
        def initWithCGImage_options_(self, image, options):
            return self

        def performRequests_error_(self, requests, error):
            return True, None

    fake_q = SimpleNamespace(
        CGRectMake=lambda *args: args,
        CGWindowListCreateImage=lambda *args: object(),
        kCGWindowListOptionOnScreenOnly=1,
        kCGNullWindowID=0,
        kCGWindowImageDefault=0,
    )
    fake_v = SimpleNamespace(
        VNRecognizeTextRequest=SimpleNamespace(alloc=Request),
        VNImageRequestHandler=SimpleNamespace(alloc=Handler),
        VNRequestTextRecognitionLevelAccurate=1,
    )
    monkeypatch.setitem(sys.modules, "Quartz", fake_q)
    monkeypatch.setitem(sys.modules, "Vision", fake_v)
    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "objc", SimpleNamespace(autorelease_pool=nullcontext))
    result = _ocr_with_fake_frameworks(MacNative(), [Rect(10, 20, 100, 50)])
    assert len(result) == 1 and result[0].text == "Connect"
    assert (result[0].x, result[0].y) == pytest.approx((40, 50))


async def test_child_guard_blocks_browser_before_any_native_launch(monkeypatch):
    from playwright._impl._browser_type import BrowserType

    from tests.guards import install_vpn_native_guard

    monkeypatch.delenv("TOOLBOX_TEST_GUARD_LOG", raising=False)
    restore = install_vpn_native_guard()
    try:
        with pytest.raises(RuntimeError, match="native.vpn"):
            await BrowserType.launch_persistent_context(None)
    finally:
        restore()
