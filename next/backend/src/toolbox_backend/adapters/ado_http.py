"""Bounded ADO reads. PAT is sent once, only to a stored library's origin."""

import base64
import json
import ssl
import time
from typing import Literal
from urllib.parse import quote, urljoin

import httpx
from pydantic import BaseModel

from toolbox_backend.domain.settings import Library, origin
from toolbox_backend.logging_setup import redact_exception, register_secret

LIMIT = 1 << 20
ConnectionCategory = Literal[
    "ok",
    "unauthorized",
    "forbidden",
    "not_found",
    "redirect",
    "tls",
    "timeout",
    "network",
    "bad_response",
    "no_credential",
]


class ConnectionResult(BaseModel):
    ok: bool = False
    http_status: int | None = None
    category: ConnectionCategory
    message: str


class RemoteProject(BaseModel):
    name: str


class AdoHTTP:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.transport = transport

    def projects(
        self, library: Library, collection: str, pat: str | None, *, listing: bool = False
    ) -> tuple[ConnectionResult, list[RemoteProject]]:
        if not pat:
            return ConnectionResult(category="no_credential", message="未配置 PAT"), []
        register_secret(pat)
        url = library.base_url + "/" + quote(collection, safe="") + "/_apis/projects"
        # httpx normalizes dot segments; check the actual outgoing path boundary.
        path = httpx.URL(url).path
        prefix = httpx.URL(library.base_url).path.rstrip("/") + "/"
        if origin(url) != origin(library.base_url) or not path.startswith(prefix):
            return ConnectionResult(category="network", message="请求地址越界"), []
        auth = base64.b64encode((":" + pat).encode()).decode()
        status = None
        deadline = time.monotonic() + 10.0
        try:
            with httpx.Client(
                transport=self.transport,
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(10.0, connect=5.0),
            ) as client:
                with client.stream(
                    "GET",
                    url,
                    params={"api-version": "7.0", "$top": 500 if listing else 1},
                    headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
                ) as response:
                    status = response.status_code
                    if time.monotonic() >= deadline:
                        raise httpx.ReadTimeout("total deadline")
                    if 300 <= status < 400:
                        try:
                            target = origin(urljoin(url, response.headers.get("location", "")))
                        except ValueError:
                            target = "未知地址"
                        return ConnectionResult(
                            http_status=status,
                            category="redirect",
                            message=redact_exception("被重定向到 " + target),
                        ), []
                    if status in {401, 403, 404}:
                        category, message = {
                            401: ("unauthorized", "认证失败"),
                            403: ("forbidden", "无访问权限"),
                            404: ("not_found", "项目接口不存在"),
                        }[status]
                        return ConnectionResult(
                            http_status=status,
                            category=category,
                            message=message,
                        ), []
                    if not 200 <= status < 300:
                        return ConnectionResult(
                            http_status=status,
                            category="bad_response",
                            message="远端返回异常状态",
                        ), []
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic() >= deadline:
                            raise httpx.ReadTimeout("total deadline")
                        if len(body) + len(chunk) > LIMIT:
                            return ConnectionResult(
                                http_status=status,
                                category="bad_response",
                                message="响应超过 1 MiB",
                            ), []
                        body.extend(chunk)
                    payload = json.loads(body)
                    values = payload.get("value") if isinstance(payload, dict) else None
                    if not isinstance(values, list) or any(
                        not isinstance(item, dict) or not isinstance(item.get("name"), str)
                        for item in values
                    ):
                        raise ValueError
                    projects = [
                        RemoteProject(name=redact_exception(x["name"])) for x in values[:500]
                    ]
                    return ConnectionResult(
                        ok=True,
                        http_status=status,
                        category="ok",
                        message="连接成功",
                    ), projects
        except httpx.TimeoutException:
            category, message = "timeout", "连接超时"
        except (ssl.SSLError, httpx.ConnectError) as exc:
            # Exception text is inspected locally only, never returned or logged.
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
        return ConnectionResult(http_status=status, category=category, message=message), []
