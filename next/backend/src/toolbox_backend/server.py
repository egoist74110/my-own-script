"""Process entry: self-bind a random port, serve with uvicorn, emit the READY handshake."""

import argparse
import asyncio
import contextlib
import json
import logging
import os
import secrets
import signal
import socket
import sys
from collections.abc import Iterator
from pathlib import Path

import uvicorn

from toolbox_backend.adapters.ado_http import AdoHTTP
from toolbox_backend.adapters.ado_read import AdoRead
from toolbox_backend.adapters.credentials import (
    KeyringCredentials,
    KeyringLegacySource,
    MemoryCredentials,
    seed_fake_credentials,
)
from toolbox_backend.adapters.dev_tasks import git_for_root, seed, task_root
from toolbox_backend.adapters.fake_ado import fake_transport
from toolbox_backend.adapters.stdin import watch_stdin_eof
from toolbox_backend.app import create_app
from toolbox_backend.logging_setup import setup_logging
from toolbox_backend.settings import Settings

log = logging.getLogger("toolbox_backend")

FAKE_CREDENTIALS_ENV = "TOOLBOX_DEV_FAKE_CREDENTIALS"  # dev-only, memory credentials only
HEARTBEAT_ENV = "TOOLBOX_HEARTBEAT_INTERVAL_S"  # test hook; default 5 s


class _Server(uvicorn.Server):
    """uvicorn server whose signal handling is owned by us (exit code must be 0)."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


def bind_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
    except BaseException:
        sock.close()
        raise
    return sock


def ready_line(port: int, token: str) -> str:
    payload = {"v": 1, "port": port, "token": token, "pid": os.getpid()}
    return "TOOLBOX_READY " + json.dumps(payload, separators=(",", ":"))


async def serve(settings: Settings, sock: socket.socket) -> int:
    loop = asyncio.get_running_loop()
    mode = os.environ.get("TOOLBOX_CREDENTIALS", "keyring")
    if mode == "memory" and not settings.dev:
        raise ValueError("memory credentials require --dev")
    if mode not in {"keyring", "memory"}:
        raise ValueError("unsupported credential backend")
    fake_file = os.environ.get(FAKE_CREDENTIALS_ENV)
    if fake_file and not (settings.dev and mode == "memory"):
        raise ValueError(f"{FAKE_CREDENTIALS_ENV} requires --dev and TOOLBOX_CREDENTIALS=memory")
    credentials = MemoryCredentials() if mode == "memory" else KeyringCredentials()
    legacy = MemoryCredentials() if mode == "memory" else KeyringLegacySource()
    if fake_file:
        assert isinstance(credentials, MemoryCredentials) and isinstance(legacy, MemoryCredentials)
        seed_fake_credentials(Path(fake_file), legacy=legacy, current=credentials)
    transport = fake_transport(settings.dev)
    root = task_root(settings.dev)
    app = create_app(
        settings,
        credentials=credentials,
        legacy_credentials=legacy,
        ado_http=AdoHTTP(transport),
        ado_read=AdoRead(transport),
        task_git=git_for_root(settings.data_dir, root) if root else None,
    )
    if root:
        await seed(app, root)
    config = uvicorn.Config(
        app,
        log_config=None,
        ws="websockets-sansio",
        timeout_graceful_shutdown=3,
        access_log=False,
    )
    server = _Server(config)

    def request_exit() -> None:
        server.should_exit = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, request_exit)
    watch_stdin_eof(loop, request_exit)

    task = asyncio.create_task(server.serve(sockets=[sock]))
    # uvicorn exposes no startup event, only the ``started`` flag.
    while not server.started and not task.done():  # noqa: ASYNC110
        await asyncio.sleep(0.01)
    if server.started and not server.should_exit:
        # Listener is created and the app lifespan has started: connections are accepted now.
        sys.stdout.write(ready_line(settings.port, settings.token) + "\n")
        sys.stdout.flush()
    try:
        await task
    except SystemExit as exc:
        log.error("server failed to start (exit %s)", exc.code)
        return 1 if exc.code in (None, 0) else int(exc.code)
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="toolbox_backend")
    parser.add_argument("--dev", action="store_true", help="allow the Vite dev origins in CORS/WS")
    parser.add_argument("--data-dir", type=Path, help="override the independent data directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    token = secrets.token_urlsafe(32)
    setup_logging([token])
    sock = None
    try:
        # Validate dev fixture mode before even attempting to bind.
        if os.environ.get("TOOLBOX_DEV_FAKE_ADO") is not None:
            if not (args.dev and os.environ.get("TOOLBOX_CREDENTIALS") == "memory"):
                raise ValueError(
                    "TOOLBOX_DEV_FAKE_ADO requires --dev and TOOLBOX_CREDENTIALS=memory"
                )
        task_root(args.dev)
        if os.environ.get("TOOLBOX_DEV_FAKE_TELEGRAM") is not None:
            if not (args.dev and os.environ.get("TOOLBOX_CREDENTIALS") == "memory"
                    and os.environ["TOOLBOX_DEV_FAKE_TELEGRAM"] == "1"):
                raise ValueError("TOOLBOX_DEV_FAKE_TELEGRAM requires --dev and memory credentials")
        if os.environ.get("TOOLBOX_DEV_FAKE_AI") is not None:
            if not (args.dev and os.environ.get("TOOLBOX_CREDENTIALS") == "memory"
                    and os.environ["TOOLBOX_DEV_FAKE_AI"] == "1"):
                raise ValueError("TOOLBOX_DEV_FAKE_AI requires --dev and memory credentials")
        sock = bind_socket()
        port = sock.getsockname()[1]
        heartbeat = float(os.environ.get(HEARTBEAT_ENV, "5"))
        overrides = {"data_dir": args.data_dir} if args.data_dir else {}
        settings = Settings(
            token=token,
            port=port,
            dev=args.dev,
            heartbeat_interval_s=heartbeat,
            **overrides,
        )
        return asyncio.run(serve(settings, sock))
    except Exception:
        log.exception("fatal startup/runtime error")
        return 1
    finally:
        if sock is not None:
            sock.close()
