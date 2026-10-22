"""Pure ASGI security middleware. Order (outermost first): Host -> CORS -> Auth."""

import json
import secrets

from starlette.types import ASGIApp, Receive, Scope, Send


def token_matches(supplied: str, expected: str) -> bool:
    return secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


async def _json_response(send: Send, status: int, detail: str, extra: list | None = None) -> None:
    body = json.dumps({"detail": detail}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    await send(
        {"type": "http.response.start", "status": status, "headers": headers + (extra or [])}
    )
    await send({"type": "http.response.body", "body": body})


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key == name:
            return value.decode("latin-1")
    return None


class HostGuard:
    """Reject any Host other than 127.0.0.1:<port> (DNS rebinding defence)."""

    def __init__(self, app: ASGIApp, expected_host: str) -> None:
        self.app = app
        self.expected_host = expected_host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and _header(scope, b"host") != self.expected_host:
            if scope["type"] == "http":
                await _json_response(send, 400, "invalid host")
            else:
                await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)


class BearerAuth:
    """Require ``Authorization: Bearer <token>`` on every HTTP request.

    WebSockets are not handled here: they authenticate with a first frame.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            auth = _header(scope, b"authorization") or ""
            scheme, _, supplied = auth.partition(" ")
            if scheme.lower() != "bearer" or not token_matches(supplied.strip(), self.token):
                await _json_response(send, 401, "unauthorized", [(b"www-authenticate", b"Bearer")])
                return
        await self.app(scope, receive, send)
