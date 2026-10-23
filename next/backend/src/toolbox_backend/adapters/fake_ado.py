"""Explicit dev-only, in-process fake ADO. Never opens a listener or network socket."""

import base64
import json
import os
from pathlib import Path

import httpx

from toolbox_backend.adapters.fake_task_ado import FakeTaskADO

FAKE_ADO_ENV = "TOOLBOX_DEV_FAKE_ADO"


def fake_transport(dev: bool) -> httpx.MockTransport | None:
    directory = os.environ.get(FAKE_ADO_ENV)
    if directory is None:
        return None
    if not (dev and os.environ.get("TOOLBOX_CREDENTIALS") == "memory"):
        raise ValueError("TOOLBOX_DEV_FAKE_ADO requires --dev and TOOLBOX_CREDENTIALS=memory")
    # The developer explicitly chooses this local fixture; request paths never select files.
    with (Path(directory) / "fixture.json").open(encoding="utf-8") as stream:
        fixture = json.load(stream)

    tasks = FakeTaskADO()

    def handler(request):
        response = tasks(request)
        if response is not None:
            return response
        path = request.url.path
        if path.endswith("/_apis/projects"):
            return httpx.Response(200, json={"value": fixture["projects"]})
        if path.endswith("/wiql"):
            return httpx.Response(
                200, json={"workItems": [{"id": x["id"]} for x in fixture["items"]]}
            )
        if path.endswith("/workitemsbatch"):
            ids = json.loads(request.content)["ids"]
            return httpx.Response(
                200, json={"value": [x for x in fixture["items"] if x["id"] in ids]}
            )
        if "/attachments/" in path:
            name = path.rsplit("/", 1)[-1]
            media = fixture["media"].get(name)
            return (
                httpx.Response(200, content=base64.b64decode(media))
                if media
                else httpx.Response(404)
            )
        pieces = path.split("/")
        try:
            if pieces[-1] in {"comments", "updates"}:
                ident = pieces[-2]
                key = "comments" if pieces[-1] == "comments" else "value"
                return httpx.Response(200, json={key: fixture[pieces[-1]].get(ident, [])})
            ident = int(pieces[-1])
            item = next((x for x in fixture["items"] if x["id"] == ident), None)
            return httpx.Response(200, json=item) if item else httpx.Response(404)
        except ValueError, IndexError:
            return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    transport.task_service = tasks
    return transport
