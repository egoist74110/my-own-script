"""Subprocess supervisor: EOF kills the owned group; inherited flock survives parent death.

Invoked only by GitAdapter with fixed executable arguments, never by HTTP input.
"""

import contextlib
import os
import select
import signal
import subprocess
import sys
import time


def main():
    control = int(sys.argv[1])
    lock_fds = tuple(int(value) for value in sys.argv[2].split(","))
    proc = subprocess.Popen(
        sys.argv[3:], stdin=subprocess.DEVNULL, start_new_session=True, pass_fds=lock_fds
    )
    try:
        while proc.poll() is None:
            readable, _, _ = select.select([control], [], [], 0.05)
            if readable and not os.read(control, 1):
                break
        # Also clean descendants left after the direct child has exited.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        return proc.wait()
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        os.close(control)
        for fd in lock_fds:
            os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
