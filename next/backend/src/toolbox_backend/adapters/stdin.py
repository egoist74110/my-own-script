import asyncio
import os
import sys
import threading
from collections.abc import Callable


def watch_stdin_eof(loop: asyncio.AbstractEventLoop, on_eof: Callable[[], None]) -> None:
    """Call ``on_eof`` on the loop thread when stdin reaches EOF (supervisor gone).

    Reads the raw fd (not ``sys.stdin``): a daemon thread blocked inside a buffered reader
    holds its lock and makes the interpreter abort at shutdown.
    """

    def run() -> None:
        try:
            fd = sys.stdin.fileno()
            while os.read(fd, 65536):
                pass
        except OSError, ValueError, AttributeError:
            pass
        loop.call_soon_threadsafe(on_eof)

    threading.Thread(target=run, name="stdin-eof-watch", daemon=True).start()
