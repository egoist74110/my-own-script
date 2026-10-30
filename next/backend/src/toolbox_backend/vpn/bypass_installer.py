"""Reviewed inline macOS installer, Python >=3.9 and standard library only.

Executed with a preflighted canonical system Python -I -S -c after OS authorization.
All destinations and commands are fixed here. Payload source/config are data,
never paths to user-writable staged files. No imports from the application.
"""

import ctypes
import fcntl
import json
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path("/Library/Application Support/toolbox-vpn-bypass")
PLIST = Path("/Library/LaunchDaemons/com.toolbox.vpn-bypass.plist")
JOB = "system/com.toolbox.vpn-bypass"
PYTHON = "/usr/bin/python3"
ENV = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"}


def protected(path, directory=False):
    path = Path(path)
    for node in [*reversed(path.parents), path]:
        info = node.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError("unprotected root path")
    mode = path.lstat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise RuntimeError("unexpected root path type")


def runtime_preflight():
    """Check the system launcher, resolved runtime, stdlib and loaded dylibs.

    Apple's system launcher selects Xcode/CLT Python. Validate the resolved
    runtime as well; trusting /usr/bin/python3 alone is insufficient.
    """
    if sys.version_info < (3, 9) or sys.platform != "darwin":
        raise RuntimeError("macOS system Python >=3.9 is required")
    protected(PYTHON)
    # Apple's launcher reports an Xcode symlink as sys.executable. Check every
    # link's containing directory/owner, then the canonical executable itself.
    executable = Path(sys.executable)
    while executable.is_symlink():
        protected(executable.parent, directory=True)
        if executable.lstat().st_uid != 0:
            raise RuntimeError("unprotected runtime link")
        executable = Path(os.path.abspath(executable.parent / os.readlink(executable)))
    protected(executable)
    for raw in sys.path:
        path = Path(raw)
        if not path.is_absolute():
            raise RuntimeError("relative runtime search path")
        if not path.exists():
            if path.is_symlink():
                raise RuntimeError("dangling runtime symlink")
            protected(path.parent, directory=True)
            continue  # standard optional python39.zip
        if path.is_dir():
            protected(path, directory=True)
            for folder, dirs, files in os.walk(path, followlinks=False):
                for name in dirs:
                    protected(Path(folder) / name, directory=True)
                for name in files:
                    if name.endswith((".py", ".so", ".zip")):
                        protected(Path(folder) / name)
        else:
            protected(path)
    # Load all extension families used by the standalone helper before checking
    # dyld images, including hashlib's crypto libraries.
    for module in ("argparse", "hashlib", "ipaddress", "re"):
        __import__(module)
    dyld = ctypes.CDLL(None)
    dyld._dyld_image_count.restype = ctypes.c_uint32
    dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    dyld._dyld_get_image_name.restype = ctypes.c_char_p
    for index in range(dyld._dyld_image_count()):
        raw = os.fsdecode(dyld._dyld_get_image_name(index))
        path = Path(raw)
        if path.exists():
            # Framework aliases may be root-owned links; resolved images must
            # themselves have protected ancestors and no writable components.
            protected(path.parent, directory=True)
            if path.is_symlink() and path.lstat().st_uid != 0:
                raise RuntimeError("unprotected runtime image link")
            protected(path.resolve())
        elif raw.startswith(("/System/Library/", "/usr/lib/")):
            # Sealed OS images can live solely in the dyld shared cache.
            while not path.exists():
                path = path.parent
            protected(path, directory=True)
        else:
            raise RuntimeError("unverifiable runtime image")


def command(argv, allowed=(0,)):
    result = subprocess.run(argv, capture_output=True, text=True, env=ENV, timeout=20)
    if result.returncode not in allowed:
        raise RuntimeError("privileged system operation failed")
    return result


def job_present():
    return command(["/bin/launchctl", "print", JOB], allowed=range(256)).returncode == 0


def stop_job():
    if job_present():
        command(["/bin/launchctl", "bootout", JOB])
    deadline = time.monotonic() + 15
    while job_present():
        if time.monotonic() >= deadline:
            raise RuntimeError("daemon did not stop")
        time.sleep(0.1)


def lock(name, wait=False):
    path = ROOT / name
    if path.exists() or path.is_symlink():
        protected(path)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        protected(path)
        deadline = time.monotonic() + (15 if wait else 0)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("privileged action or daemon busy") from None
                time.sleep(0.1)
    except BaseException:
        os.close(fd)
        raise


def write_file(path, content, mode):
    protected(path.parent, directory=True)
    if path.exists() or path.is_symlink():
        protected(path)
    fd, name = tempfile.mkstemp(prefix=".install-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def execute(action, helper_source, config):
    if action not in {"activate", "deactivate"} or os.geteuid() != 0:
        raise RuntimeError("invalid privileged action")
    runtime_preflight()
    protected(ROOT.parent, directory=True)
    protected(PLIST.parent, directory=True)
    if ROOT.exists() or ROOT.is_symlink():
        protected(ROOT, directory=True)
    else:
        ROOT.mkdir(mode=0o755)
    os.chmod(ROOT, 0o755)
    action_fd = lock("action.lock")
    try:
        stop_job()
        daemon_fd = lock("lock", wait=True)
        try:
            # Preserve state.json, especially unresolved pending ownership.
            state_path = ROOT / "state.json"
            if state_path.exists() or state_path.is_symlink():
                protected(state_path)
                os.chmod(state_path, 0o600)
            snapshot = dict(config, enabled=(action == "activate"))
            write_file(ROOT / "helper.py", helper_source.encode(), 0o600)
            write_file(ROOT / "config.json", json.dumps(snapshot).encode(), 0o600)
            enabled = action == "activate"
            plist = {
                "Label": "com.toolbox.vpn-bypass",
                "ProgramArguments": [PYTHON, "-I", "-S", str(ROOT / "helper.py"), "loop"],
                "RunAtLoad": enabled,
                "KeepAlive": enabled,
                "Disabled": not enabled,
                "ThrottleInterval": 30,
                "Umask": 0o077,
                "WorkingDirectory": str(ROOT),
                "StandardOutPath": "/dev/null",
                "StandardErrorPath": "/dev/null",
            }
            write_file(PLIST, plistlib.dumps(plist), 0o644)
        finally:
            os.close(daemon_fd)
        # The daemon's own lock protects this one-shot reconciliation too.
        command(
            [
                PYTHON,
                "-I",
                "-S",
                str(ROOT / "helper.py"),
                "sweep" if enabled else "undo",
            ],
            allowed=(0, 1, 2),
        )
        command(["/bin/launchctl", "enable" if enabled else "disable", JOB])
        if enabled:
            command(["/bin/launchctl", "bootstrap", "system", str(PLIST)])
    finally:
        os.close(action_fd)
