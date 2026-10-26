"""Shared, bounded synchronous ADO reads; callers own the async concurrency gate."""

import base64
import json
import re
import ssl
import time
from collections.abc import Callable
from urllib.parse import quote, unquote, urljoin, urlsplit

import httpx

from toolbox_backend.domain.settings import Library, origin, segment
from toolbox_backend.logging_setup import redact_exception, register_secret

JSON_LIMIT = 4 << 20
IMAGE_LIMIT = 10 << 20
ATTACHMENT_LIMIT = 25 << 20


class AdoFailure(Exception):
    def __init__(self, category, message, status=None):
        super().__init__(message)
        self.category, self.message, self.status = category, message, status
        self.version_unsupported = False


def safe_origin(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        return redact_exception(origin(url))
    except ValueError:
        return ""


def within(library: Library, url: str) -> bool:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(ord(c) < 33 or ord(c) == 127 for c in url)
            or "\\" in url
            or origin(url) != origin(library.base_url)
        ):
            return False
        # Match S1's decoded path boundary, rejecting encoded traversal too.
        path = httpx.URL(url).path
        decoded = path
        for _ in range(4):
            previous, decoded = decoded, unquote(decoded)
            if decoded == previous:
                break
        if "\\" in decoded or any(p in {".", ".."} for p in decoded.split("/")):
            return False
        prefix = httpx.URL(library.base_url).path.rstrip("/") + "/"
        # raw_path includes the query string; the encoded-separator check is for the path only.
        raw_path = httpx.URL(url).raw_path.split(b"?", 1)[0]
        raw_prefix = httpx.URL(library.base_url).raw_path.rstrip(b"/") + b"/"
        return (
            path.startswith(prefix)
            and raw_path.startswith(raw_prefix)
            and not re.search(rb"%(?:2f|5c|2e)", raw_path, re.IGNORECASE)
        )
    except ValueError, httpx.InvalidURL:
        return False


def build_url(library, segments):
    try:
        url = library.base_url + "/" + "/".join(quote(segment(str(s)), safe="") for s in segments)
    except ValueError:
        raise AdoFailure("network", "请求地址越界") from None
    if not within(library, url):
        raise AdoFailure("network", "请求地址越界")
    return url


def _status(response, url):
    status = response.status_code
    if 300 <= status < 400:
        target = safe_origin(urljoin(url, response.headers.get("location", ""))) or "未知地址"
        raise AdoFailure("redirect", "被重定向到 " + target, status)
    if status in {401, 403, 404}:
        category, message = {
            401: ("unauthorized", "认证失败"),
            403: ("forbidden", "无访问权限"),
            404: ("not_found", "项目接口不存在"),
        }[status]
        raise AdoFailure(category, message, status)
    if not 200 <= status < 300:
        raise AdoFailure("bad_response", "远端返回异常状态", status)


class AdoRead:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.transport = transport

    def _read(
        self,
        library,
        pat,
        method,
        url,
        params=None,
        json_body=None,
        *,
        limit=JSON_LIMIT,
        seconds=15.0,
        media=False,
        clock: Callable | None = None,
        content_type: str | None = None,
    ):
        if not pat:
            raise AdoFailure("no_credential", "未配置 PAT")
        register_secret(pat)
        if not within(library, url):
            raise AdoFailure("blocked_origin" if media else "network", "请求地址越界")
        auth = base64.b64encode((":" + pat).encode()).decode()
        clock = clock or time.monotonic
        deadline = clock() + seconds
        status = None
        try:
            with httpx.Client(
                transport=self.transport,
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(seconds, connect=5.0),
            ) as client:
                for hop in range(6):
                    if clock() >= deadline:
                        raise httpx.ReadTimeout("total deadline")
                    # Each hop has at most the remaining total budget.
                    with client.stream(
                        method,
                        url,
                        params=params,
                        json=json_body,
                        headers={
                            "Authorization": f"Basic {auth}",
                            "Accept": "*/*" if media else "application/json",
                            **({"Content-Type": content_type} if content_type else {}),
                        },
                        timeout=httpx.Timeout(max(0.001, deadline - clock()), connect=5.0),
                    ) as response:
                        status = response.status_code
                        if clock() >= deadline:
                            raise httpx.ReadTimeout("total deadline")
                        if media and 300 <= status < 400:
                            target = urljoin(
                                str(response.url), response.headers.get("location", "")
                            )
                            if not within(library, target):
                                raise AdoFailure(
                                    "blocked_origin",
                                    "已拦截媒体重定向到 " + (safe_origin(target) or "未知地址"),
                                    status,
                                )
                            if hop == 5:
                                raise AdoFailure("redirect", "媒体重定向次数超限", status)
                            url, params = target, None
                            continue
                        if status in {400, 404} and method == "GET":
                            # Inspect only a bounded structured error code, never emit its body.
                            error_body = bytearray()
                            for chunk in response.iter_bytes():
                                if clock() >= deadline:
                                    raise httpx.ReadTimeout("total deadline")
                                if len(error_body) + len(chunk) > limit:
                                    raise AdoFailure("too_large", "远端响应超过大小限制", status)
                                error_body.extend(chunk)
                            try:
                                error = json.loads(error_body)
                                explicit = isinstance(error, dict) and error.get("typeKey") in {
                                    "VssVersionNotSupportedException",
                                    "UnsupportedApiVersionException",
                                    "ApiVersionNotSupportedException",
                                }
                            except (ValueError, RecursionError):
                                explicit = False
                            try:
                                _status(response, url)
                            except AdoFailure as exc:
                                exc.version_unsupported = explicit
                                raise
                        _status(response, url)
                        try:
                            length = int(response.headers.get("content-length", "0"))
                        except ValueError:
                            raise AdoFailure("bad_response", "远端响应格式无效", status) from None
                        if length > limit:
                            raise AdoFailure("too_large", "远端响应超过大小限制", status)
                        body = bytearray()
                        # No chunk_size: each incoming chunk checks both limits.
                        for chunk in response.iter_bytes():
                            if clock() >= deadline:
                                raise httpx.ReadTimeout("total deadline")
                            if len(body) + len(chunk) > limit:
                                raise AdoFailure("too_large", "远端响应超过大小限制", status)
                            body.extend(chunk)
                        if clock() >= deadline:
                            raise httpx.ReadTimeout("total deadline")
                        return bytes(body), status
        except AdoFailure:
            raise
        except httpx.TimeoutException:
            category, message = "timeout", "连接超时"
        except (ssl.SSLError, httpx.ConnectError) as exc:
            tls = (
                isinstance(exc, ssl.SSLError)
                or "ssl" in str(exc).lower()
                or "certificate" in str(exc).lower()
            )
            category, message = ("tls", "TLS 验证失败") if tls else ("network", "网络连接失败")
        except httpx.HTTPError, OSError:
            category, message = "network", "网络连接失败"
        except ValueError, RecursionError:
            category, message = "bad_response", "远端响应格式无效"
        raise AdoFailure(category, message, status) from None

    def _json(self, library, pat, method, segments, params, json_body, **options):
        body, status = self._read(
            library, pat, method, build_url(library, segments), params, json_body, **options
        )
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError

            # Remote data can echo a PAT. Redact before any public shaping/registration.
            def redact(value):
                if isinstance(value, str):
                    return re.sub(r"[\ud800-\udfff]", "\ufffd", redact_exception(value))
                if isinstance(value, list):
                    return [redact(x) for x in value]
                if isinstance(value, dict):
                    return {redact(k): redact(v) for k, v in value.items()}
                return value

            return redact(payload), status
        except ValueError, RecursionError:
            raise AdoFailure("bad_response", "远端响应格式无效", status) from None

    def request_json(self, library, pat, method, segments, params=None, json_body=None):
        return self._json(library, pat, method, segments, params, json_body)[0]

    def fetch_media(self, library, pat, url, kind):
        if kind not in {"image", "attachment"}:
            raise ValueError("invalid media kind")
        # Keep existing query parameters; add the ADO download switch on the first hop.
        if not within(library, url):
            raise AdoFailure("blocked_origin", "请求地址越界")
        parsed = httpx.URL(url)
        url = str(parsed.copy_merge_params({"download": "true"}))
        return self._read(
            library,
            pat,
            "GET",
            url,
            limit=IMAGE_LIMIT if kind == "image" else ATTACHMENT_LIMIT,
            seconds=30.0,
            media=True,
        )[0]
