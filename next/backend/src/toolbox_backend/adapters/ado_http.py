"""Bounded ADO reads. PAT is sent once, only to a stored library's origin."""

import time
from typing import Literal

from pydantic import BaseModel

from toolbox_backend.adapters.ado_read import AdoFailure, AdoRead
from toolbox_backend.logging_setup import redact_exception

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


class AdoHTTP(AdoRead):
    """S1 compatibility facade over the public read client (existing 10s/1MiB contract)."""

    def projects(self, library, collection, pat, *, listing=False):
        if not pat:
            return ConnectionResult(category="no_credential", message="未配置 PAT"), []
        status = None
        try:
            payload, status = self._json(
                library,
                pat,
                "GET",
                [collection, "_apis", "projects"],
                {"api-version": "7.0", "$top": 500 if listing else 1},
                None,
                limit=LIMIT,
                seconds=10.0,
                clock=time.monotonic,
            )
            values = payload.get("value")
            if not isinstance(values, list) or any(
                not isinstance(x, dict) or not isinstance(x.get("name"), str) for x in values
            ):
                raise AdoFailure("bad_response", "远端响应格式无效", status)
            return ConnectionResult(
                ok=True, http_status=status, category="ok", message="连接成功"
            ), [RemoteProject(name=redact_exception(x["name"])) for x in values[:500]]
        except AdoFailure as exc:
            return ConnectionResult(
                http_status=exc.status,
                category="bad_response" if exc.category == "too_large" else exc.category,
                message=exc.message,
            ), []
