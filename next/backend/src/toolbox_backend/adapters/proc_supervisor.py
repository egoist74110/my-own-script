"""Single-thread child supervisor. stdin boot JSON; control EOF tears down its group.

Only this isolated interpreter forks. Git retains its existing supervisor unchanged.
CLI descendants that explicitly create a different session are outside this boundary.
"""

import contextlib
import fcntl
import json
import os
import select
import signal
import subprocess
import sys
import termios
import time


def process_identity(pid):
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "lstart=", "-o", "comm="],
        capture_output=True,
        text=True,
        timeout=2,
    )
    line = result.stdout.strip()
    if result.returncode or len(line) < 26:
        return None
    return {"proc_start_time": line[:24], "executable": line[24:].strip()}


def terminate_group(child, code=None, grace_s=3):
    with contextlib.suppress(ProcessLookupError):
        os.killpg(child, signal.SIGTERM)
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        try:
            os.killpg(child, 0)
        except ProcessLookupError:
            break
        if code is None:
            waited, result = os.waitpid(child, os.WNOHANG)
            if waited:
                code = os.waitstatus_to_exitcode(result)
        time.sleep(0.02)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(child, signal.SIGKILL)
    if code is None:
        _, result = os.waitpid(child, 0)
        code = os.waitstatus_to_exitcode(result)
    return code


def main():
    payload = json.loads(sys.stdin.buffer.readline(1 << 20))
    control, status = payload["control"], payload["status"]
    child = None
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        os.chdir(payload["cwd"])  # Failure never falls back to the backend cwd.
        slave = payload.get("slave")
        stdio = payload.get("stdio")  # {"stdin","stdout","stderr"} fds from the backend (pipe mode)
        stdio_fds = tuple(stdio.values()) if stdio else ()
        # Fork is restricted to this single-thread interpreter. The CLI leads its own
        # group (and its own session for PTY), allowing the supervisor to KILL then reap.
        exec_r, exec_w = os.pipe()
        child = os.fork()  # Only this isolated single-thread interpreter forks.
        if child == 0:
            try:
                os.close(exec_r)
                if slave is None:
                    os.setpgid(0, 0)
                else:
                    os.setsid()
                    fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                if slave is not None:
                    for fd in (0, 1, 2):
                        os.dup2(slave, fd)
                elif stdio:
                    for target, name in enumerate(("stdin", "stdout", "stderr")):
                        os.dup2(stdio[name], target)
                    for fd in stdio_fds:
                        if fd > 2:
                            os.close(fd)
                else:
                    fd = os.open(os.devnull, os.O_RDONLY)
                    os.dup2(fd, 0)
                    os.close(fd)
                os.close(control)
                os.close(status)
                if slave is not None and slave > 2:
                    os.close(slave)
                os.execve(payload["argv"][0], payload["argv"], payload["env"])
            except BaseException:
                os.write(exec_w, b"failed")
                os._exit(127)
        os.close(exec_w)
        for fd in stdio_fds:
            # The CLI owns the child ends now; holding them here would defeat EOF delivery.
            if fd > 2:
                with contextlib.suppress(OSError):
                    os.close(fd)
        try:
            if os.read(exec_r, 16):
                raise RuntimeError("start_failed")
        finally:
            os.close(exec_r)
        if slave is None:
            with contextlib.suppress(PermissionError, ProcessLookupError):
                os.setpgid(child, child)
        if slave is not None:
            os.close(slave)
        identity = process_identity(child) or {}
        os.write(status, (json.dumps(dict(pid=child, pgid=child, **identity)) + "\n").encode())
        os.close(status)
        status = -1
        code = None
        while not stopping:
            waited, result = os.waitpid(child, os.WNOHANG)
            if waited:
                code = os.waitstatus_to_exitcode(result)
                break
            readable, _, _ = select.select([control], [], [], 0.05)
            if readable:
                # Any control message is stop; EOF also covers backend SIGKILL.
                os.read(control, 4096)
                break
        code = terminate_group(child, code)
        return code if code >= 0 else 128 - code
    except BaseException as exc:
        if status >= 0:
            with contextlib.suppress(OSError):
                os.write(
                    status,
                    (
                        json.dumps(
                            {
                                "error": "start_failed",
                                "category": type(exc).__name__,
                                "errno": getattr(exc, "errno", None),
                            }
                        )
                        + "\n"
                    ).encode(),
                )
        return 127
    finally:
        if child:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child, signal.SIGKILL)
            with contextlib.suppress(ChildProcessError):
                os.waitpid(child, 0)
        os.close(control)
        if status >= 0:
            os.close(status)


if __name__ == "__main__":
    sys.exit(main())
