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
