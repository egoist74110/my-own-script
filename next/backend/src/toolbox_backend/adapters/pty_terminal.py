"""A nonblocking PTY with a byte-offset ring; no terminal bytes reach disk."""

import asyncio
import base64
import binascii
import contextlib
import errno
import fcntl
import os
import pty
import struct
import termios
import time

from toolbox_backend.domain.errors import SettingsError


class PTYTerminal:
    capacity = 2 * 1024 * 1024

    def __init__(self, rows=30, cols=100):
        self.master, self.slave = pty.openpty()
        self.buffer = bytearray()
        self.offset = 0
        self.closed = False
        self.connections = 0
        self.changed = asyncio.Event()
        self._rate_start = time.monotonic()
        self._input_bytes = 0
        try:
            self.resize(rows, cols)
            os.set_blocking(self.master, False)
            asyncio.get_running_loop().add_reader(self.master, self._read)
        except BaseException:
            self.close()
            raise

    @property
    def base_offset(self):
        return self.offset - len(self.buffer)

    def _read(self):
        try:
            data = os.read(self.master, 64 * 1024)
        except BlockingIOError:
            return
        except OSError as exc:
            if exc.errno not in (errno.EIO, errno.EBADF):
                raise
            data = b""
        if not data:
            asyncio.get_running_loop().remove_reader(self.master)
            self.changed.set()
            return
        self.buffer.extend(data)
        self.offset += len(data)
        if len(self.buffer) > self.capacity:
            del self.buffer[: len(self.buffer) - self.capacity]
        self.changed.set()

    def replay(self, after):
        if type(after) is not int or after < 0 or after > self.offset:
            raise ValueError("invalid offset")
        after = max(after, self.base_offset)
        return after, bytes(self.buffer[after - self.base_offset :])

    def resize(self, rows, cols):
        if (
            type(rows) is not int
            or type(cols) is not int
            or not 5 <= rows <= 300
            or not 20 <= cols <= 500
        ):
            raise ValueError("invalid terminal size")
        if not self.closed:
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    async def input(self, encoded):
        if not isinstance(encoded, str) or len(encoded) > 22000:
            raise ValueError("invalid input")
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError, binascii.Error:
            raise ValueError("invalid input") from None
        if len(data) > 16 * 1024:
            raise ValueError("input too large")
        if time.monotonic() - self._rate_start >= 1:
            self._rate_start, self._input_bytes = time.monotonic(), 0
        if self._input_bytes + len(data) > 256 * 1024:
            raise ValueError("input rate exceeded")
        self._input_bytes += len(data)
        await self.write(data)

    async def write(self, data):
        if self.closed:
            raise SettingsError("session_ended", "会话已结束", 409)
        loop = asyncio.get_running_loop()
        while data:
            try:
                written = os.write(self.master, data)
                data = data[written:]
            except BlockingIOError:
                ready = loop.create_future()
                loop.add_writer(self.master, lambda f=ready: f.done() or f.set_result(None))
                try:
                    await ready
                finally:
                    loop.remove_writer(self.master)
            except OSError:
                raise SettingsError("session_ended", "会话已结束", 409) from None

    def close_slave(self):
        if self.slave is not None:
            os.close(self.slave)
            self.slave = None

    def close(self):
        if self.closed:
            return
        self.closed = True
        loop = asyncio.get_running_loop()
        loop.remove_reader(self.master)
        loop.remove_writer(self.master)
        with contextlib.suppress(OSError):
            os.close(self.master)
        self.close_slave()
        self.changed.set()
