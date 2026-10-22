"""HTML5 parsing/sanitization before image rewriting, then a final strict whitelist."""

import html
import re
from functools import partial
from html.parser import HTMLParser
from urllib.parse import urlsplit

import nh3

from toolbox_backend.api.work_item_schemas import HtmlField

TAGS = set(
    (
        "p br div span b strong i em u s strike sub sup ul ol li blockquote pre code "
        "h1 h2 h3 h4 h5 h6 hr table thead tbody tfoot tr th td a img"
    ).split()
)
DROP = set("script style iframe object embed form input svg math".split())
ATTRS = {"a": {"href"}, "img": {"alt"}, "td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan"}}
FIRST_ATTRS = {**ATTRS, "img": {"src", "alt"}}
FINAL_ATTRS = {**ATTRS, "img": {"alt", "data-media-id"}, "span": {"data-blocked-origin"}}


def attribute(tag, attr, value, *, allowed):
    if attr not in allowed.get(tag, set()):
        return None
    if attr in {"colspan", "rowspan"}:
        digits = value.lstrip("0")
        return (
            value
            if value.isascii()
            and value.isdecimal()
            and len(digits) <= 3
            and 1 <= int(digits or "0") <= 100
            else None
        )
    if attr == "href":
        try:
            return value if urlsplit(value).scheme.lower() in {"http", "https", "mailto"} else None
        except ValueError:
            return None
    return value


class Images(HTMLParser):
    def __init__(self, register):
        super().__init__(convert_charrefs=True)
        self.register, self.parts = register, []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "img":
            ident, blocked = self.register(values.get("src") or "")
            if ident:
                self.parts.append(
                    '<img data-media-id="'
                    + html.escape(ident, quote=True)
                    + '" alt="'
                    + html.escape(values.get("alt") or "", quote=True)
                    + '">'
                )
            else:
                self.parts.append(
                    '<span data-blocked-origin="'
                    + html.escape(blocked or "", quote=True)
                    + '">'
                    + ("[已拦截外部图片]" if blocked else "[内嵌图片未显示]")
                    + "</span>"
                )
        else:
            self.parts.append(
                "<"
                + tag
                + "".join(" " + k + '="' + html.escape(v or "", quote=True) + '"' for k, v in attrs)
                + ">"
            )

    def handle_endtag(self, tag):
        self.parts.append("</" + tag + ">")

    def handle_data(self, data):
        self.parts.append(html.escape(data))


def sanitize_html(value: str, register) -> HtmlField:
    if len(value.encode("utf-8")) > 1 << 20:
        return HtmlField(html=None, omitted="too_large")
    # nh3's HTML5 parser eliminates foreign-content/malformed markup before Python's
    # parser sees it. src is retained only for this trusted intermediate rewrite.
    first = nh3.clean(
        value,
        tags=TAGS,
        clean_content_tags=DROP,
        attributes=FIRST_ATTRS,
        url_schemes={"http", "https", "mailto", "data", "blob", "file", "javascript"},
        link_rel=None,
        attribute_filter=partial(attribute, allowed=FIRST_ATTRS),
    )
    parser = Images(register)
    parser.feed(first)
    return HtmlField(
        html=nh3.clean(
            "".join(parser.parts),
            tags=TAGS,
            clean_content_tags=DROP,
            attributes=FINAL_ATTRS,
            url_schemes={"http", "https", "mailto"},
            link_rel=None,
            attribute_filter=partial(attribute, allowed=FINAL_ATTRS),
        )
    )


class Plain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        self.parts.append(" ")

    def handle_endtag(self, tag):
        self.parts.append(" ")


def plain_text(value) -> str:
    parser = Plain()
    parser.feed(str(value) if value is not None else "")
    return re.sub(r"\s+", " ", html.unescape("".join(parser.parts))).strip()[:2000]
