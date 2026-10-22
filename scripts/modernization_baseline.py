"""Read-only modernization inventory; intentionally not an application benchmark."""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import math
import os
from pathlib import Path
import platform
import signal
import stat
import subprocess
import sys

DISTRIBUTIONS = (
    "PySide6-Essentials", "shiboken6", "PySide6-Fluent-Widgets", "pydantic",
    "PySide6-Addons", "PySide6", "keyring", "httpx", "PyYAML", "pyte", "segno",
    "playwright", "Pillow", "pyotp", "pyobjc-framework-Vision", "pyobjc-framework-Quartz",
)


def file_bytes(paths, boundary: Path) -> dict:
    """Count logical regular-file bytes once per inode; never follow symlinks."""
    seen = set()
    total = skipped = errors = 0
    boundary = boundary.resolve()
    for path in paths:
        path = Path(path)
        try:
            # Check every component, including intermediate directory symlinks.
            relative = path.absolute().relative_to(boundary)
            if ".." in relative.parts:
                raise ValueError("outside boundary")
            cursor = boundary
            for part in relative.parts:
                cursor /= part
                if cursor.is_symlink():
                    raise ValueError("symlink")
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                skipped += 1
                continue
            identity = (info.st_dev, info.st_ino)
            if identity not in seen:
                total += info.st_size
                seen.add(identity)
        except ValueError:
            skipped += 1
        except OSError:
            errors += 1
    return {"bytes": total, "files": len(seen), "skipped": skipped,
            "errors": errors, "status": "partial" if errors or skipped else "ok"}


def directory_size(root: Path, relative: str) -> dict:
    path = root / relative
    result = {"path": relative, "measurement": "logical_file_bytes_not_release_size"}
    if path.is_symlink():
        return result | {"status": "symlink_skipped", "bytes": None}
    if not path.is_dir():
        return result | {"status": "missing", "bytes": None}
    paths = []
    errors = []
    skipped_directories = 0
    for directory, dirs, files in os.walk(path, followlinks=False, onerror=errors.append):
        retained = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        skipped_directories += len(dirs) - len(retained)
        dirs[:] = retained
        paths.extend(Path(directory) / name for name in files)
    sizes = file_bytes(paths, root)
    sizes["errors"] += len(errors)
    sizes["skipped"] += skipped_directories
    if sizes["errors"] or sizes["skipped"]:
        sizes["status"] = "partial"
    return result | sizes


def distribution_size(name: str) -> dict:
    result = {"name": name, "measurement": "declared_distribution_files_logical_bytes",
              "scope": "current_interpreter", "additive": False}
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return result | {"status": "not_installed", "version": None, "bytes": None}
    except Exception:
        return result | {"status": "error", "error": "metadata_unavailable", "bytes": None}
    try:
        result["version"] = distribution.version
        files = distribution.files
        if files is None:
            return result | {"status": "unmeasured", "reason": "no_file_manifest", "bytes": None}
        # Ownership follows this distribution's manifest, not a shared import directory.
        boundary = Path(distribution.locate_file("")).resolve()
        return result | file_bytes((distribution.locate_file(item) for item in files), boundary)
    except Exception:
        return result | {"status": "error", "error": "manifest_unavailable", "bytes": None}


def git_inventory(root: Path) -> dict:
    def run(*args):
        return subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True).stdout
    try:
        head = run("rev-parse", "HEAD").decode("ascii").strip()
        records = run("status", "--porcelain=v1", "-z", "--untracked-files=all").split(b"\0")
        dirty = []
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            paths = [record[3:]]
            if record[:1] in (b"R", b"C") or record[1:2] in (b"R", b"C"):
                paths.append(records[index])
                index += 1
            for raw in paths:
                path = raw.decode("utf-8", "replace")
                # Git paths are relative. Do not echo absolute or traversal entries.
                if not Path(path).is_absolute() and ".." not in Path(path).parts:
                    dirty.append(path)
        return {"status": "ok", "head": head, "dirty_paths": sorted(set(dirty))}
    except (OSError, subprocess.SubprocessError, UnicodeError, IndexError):
        return {"status": "error", "error": "git_inventory_unavailable"}


# Only the child imports the application. Diagnostics never include exception text.
PROBE_CODE = r'''
import contextlib, json, os, pathlib, resource, sys, time, types
root = pathlib.Path(sys.argv[1]).resolve()
allowed = (root, pathlib.Path(sys.prefix).resolve(), pathlib.Path(sys.base_prefix).resolve())
blocked = set()
def deny(event):
    if event not in blocked:
        blocked.add(event)
        os.write(1, (json.dumps({'guard_event': event}) + '\n').encode('ascii'))
    raise PermissionError('guard blocked')
def credentials_denied(*args, **kwargs):
    deny('keyring.credentials')
keyring_stub = types.ModuleType('keyring')
keyring_stub.__path__ = []
for name in ('get_password', 'set_password', 'delete_password', 'get_credential', 'get_keyring', 'set_keyring'):
    setattr(keyring_stub, name, credentials_denied)
keyring_stub.__getattr__ = credentials_denied
sys.modules['keyring'] = keyring_stub
def audit(event, args):
    if event.startswith('socket.'):
        deny('network')
    if event.startswith(('subprocess.', 'os.spawn', 'os.exec', 'os.fork')) or event == 'os.system':
        deny('subprocess')
    if event == 'ctypes.dlopen':
        deny('ctypes.dlopen')
    if event == 'import' and args[0].split('.')[0] == 'Security':
        deny('import.Security')
    if event == 'open':
        name, mode, flags = args
        if isinstance(name, int):
            return
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            deny('file.write')
        path = pathlib.Path(name).resolve()
        if not any(path.is_relative_to(base) for base in allowed):
            deny('file.read.outside_roots')
    if event == 'os.putenv':
        deny('os.putenv')
    if event in ('os.remove', 'os.rename', 'os.mkdir', 'os.rmdir', 'os.chmod', 'os.link', 'os.symlink', 'os.truncate', 'os.utime'):
        deny('filesystem.mutation')
sys.path.insert(0, str(root))
with open(os.devnull, 'w') as sink:
    sys.addaudithook(audit)
    started = time.perf_counter()
    error_type = None
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            import app_main
        status = 'error' if blocked else 'ok'
    except BaseException as error:
        status = 'error'
        safe_types = (PermissionError, ModuleNotFoundError, ImportError, OSError, RuntimeError, TypeError, ValueError, AttributeError, SystemExit)
        error_type = next((kind.__name__ for kind in safe_types if isinstance(error, kind)), 'ApplicationError')
    elapsed = time.perf_counter() - started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(json.dumps({'status': status, 'error_type': error_type, 'blocked_events': sorted(blocked),
                      'elapsed_seconds': elapsed,
                      'peak_rss_bytes': rss if sys.platform == 'darwin' else rss * 1024}))
'''

# Retain ownership if the OS refuses to reap a child within the cleanup deadlines.
UNREAPED_PROBES = []
SAFE_BLOCKED_EVENTS = {'network', 'subprocess', 'ctypes.dlopen', 'import.Security',
                       'file.write', 'file.read.outside_roots', 'os.putenv',
                       'filesystem.mutation', 'keyring.credentials'}
SAFE_ERROR_TYPES = {'PermissionError', 'ModuleNotFoundError', 'ImportError', 'OSError',
                    'RuntimeError', 'TypeError', 'ValueError', 'AttributeError',
                    'SystemExit', 'ApplicationError'}


def cleanup_probe(process) -> dict:
    """Bounded process-group cleanup; retain the handle on any cleanup failure."""
    failed = False
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        failed = True
    try:
        process.communicate(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.communicate(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            failed = True
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
    if failed:
        UNREAPED_PROBES.append(process)
        return {"status": "cleanup_failed", "process_id": process.pid,
                "reason": "group_kill_or_bounded_reap_failed", "handle_retained": True}
    return {"status": "ok"}


def import_probe(root: Path, timeout: float) -> dict:
    result = {"kind": "import_only", "gui": False,
              "meaning": "guarded_variant_import_not_startup_time_or_idle_memory",
              "guard": "read_only_no_network_no_subprocess_keychain_stub",
              "stubs": ["keyring_credentials_denied"],
              "timeout_seconds": timeout}
    process = None
    try:
        process = subprocess.Popen([sys.executable, "-I", "-B", "-c", PROBE_CODE, str(root)],
                                   cwd=root, env={}, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        stdout, _ = process.communicate(timeout=timeout)
        messages = []
        for line in stdout.splitlines():
            try:
                message = json.loads(line)
                if isinstance(message, dict):
                    messages.append(message)
            except (ValueError, UnicodeError):
                pass
        events = {message.get("guard_event") for message in messages
                  if isinstance(message.get("guard_event"), str) and message["guard_event"] in SAFE_BLOCKED_EVENTS}
        if process.returncode != 0:
            result.update(status="error", error="probe_process_failed", error_type="ProcessExit",
                          return_code=process.returncode, blocked_events=sorted(events))
        else:
            if not messages:
                raise ValueError("missing result")
            data = messages[-1]
            if not isinstance(data, dict) or data.get("status") not in ("ok", "error"):
                raise ValueError("invalid status")
            if not all(isinstance(data.get(key), (int, float)) and math.isfinite(data[key]) and data[key] >= 0
                       for key in ("elapsed_seconds", "peak_rss_bytes")):
                raise ValueError("invalid measurement")
            if data["status"] == "error":
                result.update(status="error", error="import_failed_or_guard_blocked")
                if data.get("error_type") in SAFE_ERROR_TYPES:
                    result["error_type"] = data["error_type"]
                result["blocked_events"] = sorted(events | {event for event in data.get("blocked_events", [])
                                            if isinstance(event, str) and event in SAFE_BLOCKED_EVENTS})
            else:
                result.update({key: data[key] for key in ("status", "elapsed_seconds", "peak_rss_bytes")})
    except subprocess.TimeoutExpired:
        result.update(status="timeout")
    except (OSError, ValueError, TypeError):
        result.update(status="error", error="probe_unavailable_or_invalid_result")
    finally:
        if process is not None:
            result["cleanup"] = cleanup_probe(process)
            if result["cleanup"]["status"] == "cleanup_failed" and result.get("status") == "ok":
                result.update(status="error", import_status="ok", error="cleanup_failed")
                result.pop("elapsed_seconds", None)
                result.pop("peak_rss_bytes", None)
    return result


def collect(root: Path, probe: bool = False, timeout: float = 15) -> dict:
    return {
        "schema_version": 1,
        "repository": git_inventory(root),
        "runtime": {"target_python": "3.14", "observed_python": platform.python_version(),
                    "platform": sys.platform, "machine": platform.machine()},
        "directories": [directory_size(root, name) for name in (".venv", "ok", "dist")],
        "distributions": [distribution_size(name) for name in DISTRIBUTIONS],
        "size_notes": "Independent scopes; do not add directories or distributions. Logical regular-file bytes only, not allocated disk or release-package size. Inodes deduplicated per scope. Symlinks, outside-boundary manifest entries and non-regular files are skipped; errors/skips make counts partial.",
        "import_probe": import_probe(root, timeout) if probe else {"status": "not_run", "kind": "import_only", "gui": False},
        "not_measured": ["gui_startup_time", "gui_idle_memory", "release_package_size", "functional_tests", "network_services"],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-probe", action="store_true", help="Opt in to guarded fresh-process import app_main with keyring stub; non-GUI variant. May fail on blocked imports.")
    parser.add_argument("--timeout", type=float, default=15, metavar="SECONDS", help="Import probe timeout (positive, default: 15).")
    parser.add_argument("--output", type=Path, help="Also write JSON to this explicit file; parent directory must already exist. Never creates directories.")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    report = collect(Path(__file__).resolve().parents[1], args.import_probe, args.timeout)
    rendered = json.dumps(report, indent=2, ensure_ascii=True) + "\n"
    if args.output is not None:
        try:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
        except OSError:
            print(json.dumps({"status": "error", "error": "output_write_failed_no_overwrite"}))
            return 2
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
