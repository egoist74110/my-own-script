"""S8-B worker behaviour using no browser or native automation."""

import pytest

from toolbox_backend.vpn.login_worker import CallbackCapture, LoginFailure, login_flow


class Driver:
    def __init__(self, failure=None):
        self.failure = failure
        self.steps = []
        self.capture = CallbackCapture("s8probe")

    async def step(self, name, values):
        self.steps.append(name)
        if self.failure == name:
            raise LoginFailure("login_selector_missing")

    async def outcome(self, stage):
        return "mfa" if stage == "credentials" else "callback"

    async def callback(self):
        return "s8probe://callback#private"


@pytest.mark.parametrize("failure", [None, "workspace", "residency", "credentials", "mfa"])
async def test_scripted_flow(failure):
    driver = Driver(failure)
    events = []

    async def mfa():
        return "123456"

    if failure:
        with pytest.raises(LoginFailure, match="login_selector_missing"):
            await login_flow(
                driver,
                {"workspace": "fake", "password": "private"},
                mfa,
                lambda event, **kw: events.append(event),
            )
    else:
        assert await login_flow(driver, {}, mfa, lambda event, **kw: events.append(event))
        assert driver.steps == ["workspace", "residency", "credentials", "mfa"]
        assert events[-1] == "captured"


@pytest.mark.parametrize(
    "stage,result,code",
    [
        ("credentials", "rejected", "login_credentials_rejected"),
        ("mfa", "rejected", "login_mfa_rejected"),
        ("callback", None, "login_callback_not_captured"),
    ],
)
async def test_flow_failure_codes(stage, result, code):
    driver = Driver()
    original = driver.outcome

    async def outcome(name):
        return result if name == stage else await original(name)

    async def callback():
        return None if stage == "callback" else "s8probe://ok"

    async def mfa():
        return "123456"

    driver.outcome, driver.callback = outcome, callback
    with pytest.raises(LoginFailure, match=code):
        await login_flow(driver, {}, mfa, lambda *a, **kw: None)
    assert driver.steps.count("mfa") <= 3


async def test_delivery_scheme_and_limit():
    from toolbox_backend.vpn.login_worker import deliver_callback

    calls, delays = [], []

    async def opener(url, app):
        calls.append((url, app))

    async def sleep(delay):
        delays.append(delay)

    assert await deliver_callback("wrong://x", "s8probe", "/fake", opener=opener) == 0
    assert calls == []
    assert (
        await deliver_callback("S8Probe://x", "s8probe", "/fake", opener=opener, sleep=sleep) == 6
    )
    assert len(calls) == 6 and delays == [8] * 5


async def test_profile_rejects_symlinks(tmp_path):
    from toolbox_backend.adapters.vpn_browser import secure_profile

    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "vpn").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        secure_profile(tmp_path)


async def test_reclaim_requires_pid_start_profile_and_group_identity(tmp_path):
    from toolbox_backend.adapters.vpn_browser import ChromeRegistry

    signals = []

    async def inspect(pid):
        return {"pid": pid, "pgid": pid, "lstart": "start", "command": "unrelated"}

    registry = ChromeRegistry(tmp_path, inspect=inspect, killpg=lambda *x: signals.append(x))
    registry.record({"pid": 987654, "lstart": "start"})
    await registry.cleanup()
    assert signals == []


async def test_window_permissions_fail_closed():
    from toolbox_backend.adapters.window_automation import WindowAutomation
    from toolbox_backend.domain.errors import SettingsError

    class Native:
        def permissions(self):
            return {"screen_recording": False, "accessibility": False}

        def windows(self):
            pytest.fail("permission failure must precede native capture")

    window = WindowAutomation(None, None, native=Native())
    with pytest.raises(SettingsError) as exc:
        await window.connect("connect")
    assert exc.value.code == "window_permission_missing"


def test_service_selects_real_defaults_and_unavailable_fallback(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import toolbox_backend.services.vpn as service_module
    from toolbox_backend.adapters.vpn_browser import ProcessLoginRunner
    from toolbox_backend.adapters.window_automation import WindowAutomation
    from toolbox_backend.services.vpn import (
        UnimplementedLoginRunner,
        UnimplementedWindowAutomation,
        VpnService,
    )

    store = SimpleNamespace(data_dir=tmp_path)
    monkeypatch.setattr(service_module, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(service_module, "find_spec", lambda name: object())
    service = VpnService(store, None, None, object(), None)
    assert isinstance(service.login_runner, ProcessLoginRunner)
    assert isinstance(service.window_automation, WindowAutomation)
    monkeypatch.setattr(service_module, "find_spec", lambda name: None)
    service = VpnService(store, None, None, object(), None)
    assert isinstance(service.login_runner, UnimplementedLoginRunner)
    assert isinstance(service.window_automation, UnimplementedWindowAutomation)


async def test_window_permissions_use_existing_snapshot_string_contract():
    from toolbox_backend.adapters.window_automation import WindowAutomation

    class Native:
        def permissions(self):
            return {"screen_recording": True, "accessibility": False}

    assert await WindowAutomation(None, None, native=Native()).permissions() == {
        "screen_recording": "granted",
        "accessibility": "denied",
    }


async def test_hung_driver_has_login_timeout():
    import asyncio

    driver = Driver()

    async def hang(*args):
        await asyncio.Event().wait()

    driver.step = hang
    with pytest.raises(LoginFailure, match="login_timeout"):
        await login_flow(driver, {}, hang, lambda *a, **kw: None, timeout_s=0.01)


async def test_registry_reclaims_exact_group_with_profile_path_containing_spaces(tmp_path):
    import signal

    from toolbox_backend.adapters.vpn_browser import ChromeRegistry

    calls = []
    data_dir = tmp_path / "data with spaces"

    async def inspect(pid):
        return {
            "pid": pid,
            "pgid": pid,
            "lstart": "start",
            "command": f"chrome --user-data-dir={data_dir}/vpn/chrome-profile --other",
        }

    async def sleep(delay):
        assert delay == 3

    registry = ChromeRegistry(
        data_dir, inspect=inspect, killpg=lambda *x: calls.append(x), sleep=sleep
    )
    registry.record({"pid": 987654, "lstart": "start"})
    await registry.cleanup()
    assert calls == [(987654, signal.SIGTERM), (987654, signal.SIGKILL)]


def test_profile_rejects_linked_data_root(tmp_path):
    from toolbox_backend.adapters.vpn_browser import secure_profile

    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        secure_profile(linked)
    assert not (outside / "vpn").exists()


async def test_remembered_browser_callback_skips_missing_login_form():
    driver = Driver(failure="workspace")
    driver.captured_url = "s8probe://callback#remembered"

    async def mfa():
        pytest.fail("remembered browser must not ask MFA")

    assert await login_flow(driver, {}, mfa, lambda *a, **kw: None) == "s8probe://callback#private"
    assert driver.steps == []


async def test_login_flow_discards_wrong_configured_callback_scheme():
    events = []

    async def mfa():
        return "123456"

    with pytest.raises(LoginFailure, match="login_callback_not_captured"):
        await login_flow(
            Driver(), {"scheme": "CheckPointSASE"}, mfa, lambda event, **kw: events.append(event)
        )
    assert "captured" not in events


async def test_delivery_reports_only_scheme_and_bounded_attempt_number():
    from toolbox_backend.vpn.login_worker import deliver_callback

    observed = []

    async def opener(url, app):
        pass

    async def sleep(delay):
        pass

    await deliver_callback(
        "S8Probe://cb#id_token=S8_FAKE_TOKEN",
        "s8probe",
        "/fake",
        opener=opener,
        sleep=sleep,
        on_delivery=lambda scheme, attempt: observed.append((scheme, attempt)),
    )
    assert observed == [("s8probe", attempt) for attempt in range(1, 7)]
    assert "S8_FAKE_TOKEN" not in str(observed)
