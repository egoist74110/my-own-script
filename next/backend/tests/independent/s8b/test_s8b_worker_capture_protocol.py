"""Independent S8-B callback and worker event protocol requirements."""

import json

import pytest

from toolbox_backend.vpn.login_worker import CallbackCapture, encode_event


def test_callback_capture_is_scheme_case_insensitive_and_keeps_first_url():
    capture = CallbackCapture("CheckPointSASE")

    assert capture.capture({"url": "https://login.example.invalid/callback"}) is False
    assert capture.capture({"url": "checkpointSASE://callback?code=first"}) is True
    assert capture.capture({"url": "CheckPointSASE://callback?code=second"}) is False
    assert capture.url == "checkpointSASE://callback?code=first"


@pytest.mark.parametrize(
    "url",
    [
        "javascript://callback",
        "CheckPointSASE.evil://callback",
        "not-checkpointsase://callback",
        "",
    ],
)
def test_callback_capture_rejects_wrong_or_malformed_scheme(url):
    capture = CallbackCapture("CheckPointSASE")

    assert capture.capture({"url": url}) is False
    assert capture.url is None


def test_encode_event_caps_utf8_json_line_at_64_kibibytes():
    line = encode_event("step", step="workspace")
    assert len(line) <= 64 * 1024
    assert json.loads(line)["event"] == "step"

    with pytest.raises((ValueError, OverflowError)):
        encode_event("chrome_started", pid=1, lstart="x" * (64 * 1024))


@pytest.mark.parametrize(
    "field",
    ["password", "token", "secret", "id_token", "deep_link", "callback_url"],
)
def test_encode_event_rejects_sensitive_field_names(field):
    with pytest.raises((ValueError, TypeError)):
        encode_event("step", step="workspace", **{field: "TEST_SECRET_MUST_NOT_ESCAPE"})
