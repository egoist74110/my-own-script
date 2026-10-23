"""Fail-closed guards shared by pytest and child interpreters."""

import os
import socket
from pathlib import Path

from keyring.backend import KeyringBackend


def violation(kind: str):
    path = os.environ.get("TOOLBOX_TEST_GUARD_LOG")
    if path:
        with Path(path).open("a") as stream:
            stream.write(kind + "\n")
    raise RuntimeError("test isolation guard: " + kind)


class GuardKeyring(KeyringBackend):
    priority = 100

    def get_password(self, service, username):
        violation("keyring.get")

    def set_password(self, service, username, password):
        violation("keyring.set")

    def delete_password(self, service, username):
        violation("keyring.delete")


def install_socket_guard():
    connect, connect_ex, getaddrinfo = (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.getaddrinfo,
    )

    def check(address):
        if isinstance(address, tuple) and address[0] != "127.0.0.1":
            violation("socket.non_loopback")

    def guarded_connect(self, address):
        check(address)
        return connect(self, address)

    def guarded_connect_ex(self, address):
        check(address)
        return connect_ex(self, address)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host not in ("127.0.0.1", b"127.0.0.1", None):
            violation("socket.dns")
        return getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.getaddrinfo = guarded_getaddrinfo

    def restore():
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = (
            connect,
            connect_ex,
            getaddrinfo,
        )

    return restore


def install_ai_cli_guard():
    """A real AI executable is never a valid test subprocess, including Python children."""
    import shutil
    import subprocess

    original = subprocess.Popen
    allowed = (Path(__file__).resolve().parent / "fixtures/fake_cli").resolve()

    def check(executable, env=None):
        if isinstance(executable, (str, bytes, os.PathLike)):
            executable = os.fsdecode(executable)
            if Path(executable).name in {"claude", "codex", "agy"}:
                environment = os.environ if env is None else env
                found = shutil.which(executable, path=environment.get("PATH", "")) or executable
                if not Path(found).resolve().is_relative_to(allowed):
                    violation("subprocess.real_ai_cli")

    class GuardedPopen(original):
        def __init__(self, args, *positional, **kwargs):
            argv = args if isinstance(args, (list, tuple)) else [args]
            executable = kwargs.get("executable") or argv[0]
            check(executable, kwargs.get("env"))
            super().__init__(args, *positional, **kwargs)

    subprocess.Popen = GuardedPopen
    originals = {}

    def wrap(fn, name):
        def guarded(executable, *args, **kwargs):
            env = kwargs.get("env")
            if env is None and (name.endswith("e") or name.startswith("posix_spawn")):
                if args and isinstance(args[-1], dict):
                    env = args[-1]
            check(executable, env)
            return fn(executable, *args, **kwargs)

        return guarded

    for name in (
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "posix_spawn",
        "posix_spawnp",
    ):
        if hasattr(os, name):
            originals[name] = getattr(os, name)
            setattr(os, name, wrap(originals[name], name))

    def restore():
        subprocess.Popen = original
        for name, fn in originals.items():
            setattr(os, name, fn)

    return restore
