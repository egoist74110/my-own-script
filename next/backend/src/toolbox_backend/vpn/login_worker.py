"""Bounded JSON protocol; all authentication material stays in worker memory."""

import asyncio
import contextlib
import json
import os
import signal
import sys
from typing import Protocol
from urllib.parse import urlsplit

MAX_LINE = 65536
CHROME_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-sync",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-default-apps",
]
# Both brands deliberately retain the last verified legacy entry pending real acceptance.
LEGACY_ENTRY = (
    "https://app.perimeter81.com/sign-in?"
    "redirectUrl={scheme}://perimeter81.com/macos/callback&allowTenantSelect="
)
SELECTORS = {
    brand: {
        "entry": LEGACY_ENTRY,
        "workspace": "input[name='name']",
        "residency": "div[role='button']:has-text('Data Residency')",
        "email": "input[name='username']",
        "password": "input[name='password']",
        "submit": "button[type='submit']",
        "mfa": (
            "input[name='code'], input[autocomplete='one-time-code'], "
            "input[placeholder*='digit'], input[placeholder*='code'], "
            "input[inputmode='numeric']:not([name='username']):not([type='password']), "
            "input[type='tel']"
        ),
        "rejected": "[role='alert']",
    }
    for brand in ("perimeter81", "checkpoint")
}
ERRORS = frozenset(
    {
        "login_selector_missing",
        "login_credentials_rejected",
        "login_mfa_rejected",
        "login_timeout",
        "login_callback_not_captured",
    }
)
EVENT_FIELDS = {
    "step": {"step", "scheme", "attempt"},
    "need_mfa": {"attempt"},
    "captured": {"scheme"},
    "chrome_started": {"pid", "lstart"},
    "done": set(),
    "error": {"code"},
}


class LoginFailure(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else "login_timeout"
        super().__init__(self.code)


def encode_event(event, **fields):
    if event not in EVENT_FIELDS or fields.keys() - EVENT_FIELDS[event]:
        raise ValueError("invalid worker event")
    if event == "error" and fields.get("code") not in ERRORS:
        raise ValueError("invalid worker error")
    if event == "step" and fields.get("step") not in {
        "workspace",
        "residency",
        "credentials",
        "mfa",
        "callback",
        "delivery",
    }:
        raise ValueError("invalid worker step")
    if event == "captured" and not str(fields.get("scheme", "")).isalnum():
        raise ValueError("invalid scheme")
    if event == "step" and ("scheme" in fields or "attempt" in fields):
        if (
            fields.get("step") != "delivery"
            or not str(fields.get("scheme", "")).isalnum()
            or type(fields.get("attempt")) is not int
            or not 1 <= fields["attempt"] <= 6
        ):
            raise ValueError("invalid delivery event")
    raw = (json.dumps(dict(event=event, **fields), ensure_ascii=True) + "\n").encode()
    if len(raw) > MAX_LINE:
        raise ValueError("worker line too large")
    return raw


class CallbackCapture:
    def __init__(self, scheme):
        self.scheme, self.url = scheme.lower(), None
        self.ready = asyncio.Event()

    def capture(self, event):
        url = event.get("url", "")
        if not isinstance(url, str) or len(url.encode()) > MAX_LINE - 1024:
            return False
        try:
            valid = urlsplit(url).scheme.lower() == self.scheme
        except ValueError:
            return False
        if self.url is None and valid:
            self.url = url
            self.ready.set()
            return True
        return False


class BrowserDriver(Protocol):
    @property
    def captured_url(self) -> str | None: ...
    async def step(self, name, values): ...
    async def outcome(self, stage): ...
    async def callback(self): ...


async def login_flow(driver: BrowserDriver, values, request_mfa, emit, *, timeout_s=75):
    remaining = timeout_s

    async def browser_operation(operation, *, callback=False):
        nonlocal remaining
        started = asyncio.get_running_loop().time()
        try:
            return await asyncio.wait_for(operation, min(30, max(0.001, remaining)))
        except TimeoutError:
            raise LoginFailure(
                "login_callback_not_captured" if callback else "login_timeout"
            ) from None
        finally:
            remaining -= asyncio.get_running_loop().time() - started

    for name in ("workspace", "residency", "credentials"):
        if getattr(driver, "captured_url", None):
            break
        emit("step", step=name)
        await browser_operation(driver.step(name, values))
    result = (
        "callback"
        if getattr(driver, "captured_url", None)
        else await browser_operation(driver.outcome("credentials"))
    )
    if result == "rejected":
        raise LoginFailure("login_credentials_rejected")
    if result == "mfa":
        for attempt in range(3):  # first submission + at most two retries
            emit("need_mfa", attempt=attempt + 1)
            code = await asyncio.wait_for(request_mfa(), 120)
            if (
                not isinstance(code, str)
                or len(code) != 6
                or not code.isascii()
                or not code.isdigit()
            ):
                raise LoginFailure("login_mfa_rejected")
            emit("step", step="mfa")
            await browser_operation(driver.step("mfa", {"code": code}))
            result = await browser_operation(driver.outcome("mfa"))
            if result != "rejected":
                break
        else:
            raise LoginFailure("login_mfa_rejected")
    emit("step", step="callback")
    url = await browser_operation(driver.callback(), callback=True)
    expected_scheme = values.get("scheme")
    if not url or (expected_scheme and urlsplit(url).scheme.lower() != expected_scheme.lower()):
        raise LoginFailure("login_callback_not_captured")
    emit("captured", scheme=urlsplit(url).scheme)
    return url


class PlaywrightDriver:
    def __init__(self, options, emit):
        self.options, self.emit = options, emit
        self.capture = CallbackCapture(options["scheme"])
        self.context = self.playwright = None
        self.table = SELECTORS[options.get("brand", "perimeter81")]

    @property
    def captured_url(self):
        return self.capture.url

    async def start(self):
        from playwright.async_api import async_playwright

        from toolbox_backend.adapters.vpn_browser import discover_chrome, secure_profile

        profile = secure_profile(self.options["data_dir"])
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            str(profile),
            channel="chrome",
            executable_path=self.options.get("chrome_path"),
            headless=bool(self.options.get("headless") and self.options.get("has_seed")),
            args=CHROME_ARGS,
        )
        identity = await discover_chrome(os.getpid(), profile)
        if not identity:
            raise LoginFailure("login_timeout")
        self.emit("chrome_started", **identity)
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        self.sessions = []
        await self._watch(self.page)
        self.context.on("page", self._watch)
        await self.page.goto(
            self.table["entry"].format(scheme=self.options["scheme"]),
            wait_until="domcontentloaded",
            timeout=30000,
        )

    async def _watch(self, page):
        session = await self.context.new_cdp_session(page)
        self.sessions.append(session)
        await session.send("Page.enable")
        for name in ("Page.frameRequestedNavigation", "Page.frameScheduledNavigation"):
            session.on(name, self.capture.capture)

    async def step(self, name, values):
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        try:
            if name == "workspace":
                await self.page.locator(self.table[name]).fill(
                    values.get("workspace", ""), timeout=15000
                )
            elif name == "residency":
                trigger = self.page.locator(self.table[name]).first
                text = await trigger.inner_text(timeout=15000)
                residency = values.get("residency", "US Data Residency")
                if residency not in text:
                    await trigger.click(timeout=5000)
                    await self.page.get_by_role("menuitem", name=residency, exact=True).click(
                        timeout=5000
                    )
                await self.page.locator(self.table["submit"]).click(timeout=5000)
            elif name == "credentials":
                await self.page.locator(self.table["email"]).fill(
                    values.get("email", ""), timeout=15000
                )
                await self.page.locator(self.table["password"]).fill(
                    values["password"], timeout=15000
                )
                await self.page.locator(self.table["submit"]).click(timeout=5000)
            elif name == "mfa":
                await self.page.locator(self.table["mfa"]).first.fill(values["code"], timeout=15000)
                remember = self.page.get_by_role("checkbox", name="Remember this browser")
                if await remember.count() and await remember.first.is_visible():
                    await remember.first.check(timeout=5000)
                await self.page.locator(self.table["submit"]).click(timeout=5000)
        except PlaywrightTimeout:
            raise LoginFailure("login_selector_missing") from None

    async def outcome(self, stage):
        # Polling only known selectors; never dump page text or control attributes.
        deadline = asyncio.get_running_loop().time() + 20
        while asyncio.get_running_loop().time() < deadline:
            if self.capture.url:
                return "callback"
            if await self.page.locator(self.table["rejected"]).first.is_visible():
                return "rejected"
            if (
                stage == "credentials"
                and await self.page.locator(self.table["mfa"]).first.is_visible()
            ):
                return "mfa"
            await asyncio.sleep(0.1)
        if stage == "credentials":
            raise LoginFailure("login_selector_missing")
        return "callback"  # callback() supplies its own bounded capture deadline

    async def callback(self):
        try:
            await asyncio.wait_for(self.capture.ready.wait(), 30)
        except TimeoutError:
            raise LoginFailure("login_callback_not_captured") from None
        return self.capture.url

    async def close(self):
        try:
            if self.context:
                await self.context.close()
        finally:
            if self.playwright:
                await self.playwright.stop()


async def deliver_callback(
    url, scheme, app_path, *, opener=None, sleep=asyncio.sleep, on_delivery=None
):
    if urlsplit(url).scheme.lower() != scheme.lower():
        return 0
    if opener is None:
        from toolbox_backend.adapters.vpn_browser import open_callback

        opener = open_callback
    for attempt in range(6):
        await opener(url, app_path)
        if on_delivery:
            on_delivery(scheme.lower(), attempt + 1)
        if attempt < 5:
            await sleep(8)
    return 6


async def run_worker(reader, emit, *, driver_factory=PlaywrightDriver, opener=None):
    line = await reader.readline()
    if len(line) > MAX_LINE or not line.endswith(b"\n"):
        raise LoginFailure("login_timeout")
    options = json.loads(line)
    # Entry URL is never an input to this protocol.
    if set(options) - {
        "data_dir",
        "scheme",
        "app_path",
        "headless",
        "has_seed",
        "chrome_path",
        "workspace",
        "residency",
        "email",
        "password",
        "timeout_s",
        "brand",
    }:
        raise LoginFailure("login_timeout")
    driver = driver_factory(options, emit)
    queue = asyncio.Queue()

    async def control():
        while True:
            raw = await reader.readline()
            if not raw:
                raise asyncio.CancelledError
            if len(raw) > MAX_LINE:
                raise LoginFailure("login_timeout")
            message = json.loads(raw)
            if message.get("event") == "mfa":
                await queue.put(message.get("code"))

    async def flow():
        try:
            await asyncio.wait_for(driver.start(), 30)
            url = await login_flow(
                driver, options, queue.get, emit, timeout_s=options.get("timeout_s", 75)
            )
            await deliver_callback(
                url,
                options["scheme"],
                options["app_path"],
                opener=opener,
                on_delivery=lambda scheme, attempt: emit(
                    "step", step="delivery", scheme=scheme, attempt=attempt
                ),
            )
            emit("done")
        finally:
            await driver.close()

    task, watcher = asyncio.create_task(flow()), asyncio.create_task(control())
    try:
        done, _ = await asyncio.wait([task, watcher], return_when=asyncio.FIRST_COMPLETED)
        for finished in done:
            await finished
    finally:
        for pending in (task, watcher):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, watcher, return_exceptions=True)


async def main():
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=MAX_LINE)
    transport, _ = await loop.connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer
    )
    current = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, current.cancel)

    def emit(event, **fields):
        sys.stdout.buffer.write(encode_event(event, **fields))
        sys.stdout.buffer.flush()

    try:
        await run_worker(reader, emit)
    except asyncio.CancelledError:
        pass
    except LoginFailure as exc:
        emit("error", code=exc.code)
    except Exception:
        emit("error", code="login_timeout")
    finally:
        transport.close()
        loop.remove_signal_handler(signal.SIGTERM)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
