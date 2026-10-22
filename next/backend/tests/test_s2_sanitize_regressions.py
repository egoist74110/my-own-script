import httpx
import pytest

from toolbox_backend.adapters.ado_read import AdoRead
from toolbox_backend.adapters.html_sanitize import sanitize_html
from toolbox_backend.domain.settings import Library


@pytest.mark.parametrize("value", ["https://[", "http://[invalid", "https://host:invalid"])
def test_malformed_hrefs_are_removed_without_crashing(value):
    result = sanitize_html(f'<a href="{value}">safe</a>', lambda _: (None, ""))
    assert result.html == "<a>safe</a>"


def test_encoded_quoted_pat_echo_is_redacted_before_public_shaping():
    pat = 'FAKE_QUOTED_"_PAT_391b'
    payload = {"fields": {"System.Title": pat}, "echo": [pat, {"name": pat}]}
    client = AdoRead(httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    result = client.request_json(
        Library(id="lib:x", name="fake", base_url="https://fake.test"), pat, "GET", ["_apis"]
    )
    assert result["fields"]["System.Title"] == "***"
    assert result["echo"] == ["***", {"name": "***"}]


def test_production_logging_never_records_outbound_url_paths(capsys):
    import logging

    from toolbox_backend.logging_setup import setup_logging

    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    http_log, core_log = logging.getLogger("httpx"), logging.getLogger("httpcore")
    http_level, core_level = http_log.level, core_log.level
    try:
        setup_logging([])
        client = AdoRead(httpx.MockTransport(lambda _: httpx.Response(200, json={})))
        client.request_json(
            Library(id="lib:x", name="fake", base_url="https://fake.test"),
            "FAKE_LOG_PAT_817c",
            "GET",
            ["private-project", "_apis"],
            {"secret_query": "private-query"},
        )
        output = capsys.readouterr().err
        assert "private-project" not in output and "private-query" not in output
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)
        http_log.setLevel(http_level)
        core_log.setLevel(core_level)


def test_table_span_values_are_bounded_even_for_huge_numeric_attributes():
    result = sanitize_html(
        '<table><tr><td colspan="' + "9" * 5000 + '" rowspan="100">cell</td></tr></table>',
        lambda _: (None, ""),
    )
    assert "colspan=" not in result.html and 'rowspan="100"' in result.html
