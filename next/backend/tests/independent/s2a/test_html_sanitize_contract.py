from html.parser import HTMLParser

import pytest

from toolbox_backend.adapters.html_sanitize import sanitize_html


class MarkupInventory(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend((tag, name, value) for name, value in attrs)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


@pytest.mark.parametrize(
    "payload",
    [
        '<p>safe<script>alert(1)</script>end</p>',
        '<img src="x" onerror="alert(1)">',
        '<a href="javascript:alert(1)">click</a>',
        '<a href="java&#x73;cript:alert(1)">click</a>',
        '<div style="background:url(javascript:alert(1))" onclick="x">safe</div>',
        '<svg onload="alert(1)"><text>secret svg</text></svg>',
        '<iframe src="https://evil.example">secret frame</iframe>',
        '<object>secret object</object><embed src="x">',
        '<style>secret css</style><form><input value="secret"></form>',
        '<p><b>broken<i>nested</b>tail</i></p>',
        '<img src="https://ado.example/org/_apis/a" srcset="https://evil.example/x 2x">',
    ],
)
def test_untrusted_html_cannot_keep_active_content_or_unsafe_attributes(payload):
    cleaned = sanitize_html(payload, lambda _url: ("media-id", None))
    markup = MarkupInventory()
    markup.feed(cleaned.html or "")

    assert not ({"script", "style", "iframe", "object", "embed", "svg", "math", "form", "input"} & set(markup.tags))
    assert all(not name.lower().startswith("on") for _, name, _ in markup.attributes)
    assert all(name not in {"style", "src", "srcset", "class", "id", "target"} for _, name, _ in markup.attributes)
    assert all(
        value is None or not value.strip().lower().startswith(("javascript:", "data:"))
        for _, name, value in markup.attributes
        if name in {"href", "src"}
    )
    assert "alert(1)" not in (cleaned.html or "")
    assert "secret svg" not in (cleaned.html or "")
    assert "secret frame" not in (cleaned.html or "")
    assert "secret css" not in (cleaned.html or "")


def test_html_whitelist_keeps_safe_formatting_and_links():
    cleaned = sanitize_html(
        '<p class="x"><strong>safe</strong> '
        '<a href="https://docs.example/path" target="_blank">docs</a>'
        '<span id="x" style="color:red">text</span></p>',
        lambda _url: (None, None),
    )
    markup = MarkupInventory()
    markup.feed(cleaned.html or "")

    assert {"p", "strong", "a", "span"} <= set(markup.tags)
    assert ("a", "href", "https://docs.example/path") in markup.attributes
    assert all(name not in {"class", "id", "style", "target"} for _, name, _ in markup.attributes)


def test_images_are_rewritten_to_registered_or_blocked_markers():
    def register(url):
        if url.startswith("https://ado.example/org/"):
            return "registered-media-id", None
        if url.startswith("https://outside.example/"):
            return None, "https://outside.example:443"
        return None, ""

    cleaned = sanitize_html(
        '<img src="https://ado.example/org/image.png" alt="same">'
        '<img src="https://outside.example/image.png" alt="external">'
        '<img src="data:image/png;base64,AAAA" alt="inline">',
        register,
    )
    markup = MarkupInventory()
    markup.feed(cleaned.html or "")

    assert ("img", "data-media-id", "registered-media-id") in markup.attributes
    assert ("img", "alt", "same") in markup.attributes
    assert ("span", "data-blocked-origin", "https://outside.example:443") in markup.attributes
    assert ("span", "data-blocked-origin", "") in markup.attributes
    assert "[已拦截外部图片]" in (cleaned.html or "")
    assert "[内嵌图片未显示]" in (cleaned.html or "")
    assert all(name != "src" for _, name, _ in markup.attributes)


def test_html_larger_than_one_mib_is_omitted_without_sanitizing():
    cleaned = sanitize_html("x" * ((1 << 20) + 1), lambda _url: pytest.fail("must not register"))
    assert cleaned.html is None
    assert cleaned.omitted == "too_large"
