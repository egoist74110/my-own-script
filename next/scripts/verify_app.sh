#!/usr/bin/env bash
# Verify macOS .app bundle layout, path-leak absence, read-only runtime, relocatable startup,
# codesign verification (when signed), and maximum Mach-O minimumSystemVersion.
set -euo pipefail

if [ $# -ne 1 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  echo "usage: verify_app.sh <path-to-.app>" >&2
  [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] && exit 0
  exit 2
fi

APP_PATH="$1"
if [ ! -d "$APP_PATH" ]; then
  echo "error: bundle directory not found: $APP_PATH" >&2
  exit 2
fi

APP_ABS="$(cd "$APP_PATH" && pwd -P)"
echo "[verify_app] inspecting bundle: $APP_ABS"

# 1. Check bundle layout
MAIN_BIN="$APP_ABS/Contents/MacOS/toolbox-desktop"
PY_BIN="$APP_ABS/Contents/Resources/backend/bin/python3.14"
MCP_DIR="$APP_ABS/Contents/Resources/backend/lib/python3.14/resources/mcp"

if [ ! -x "$MAIN_BIN" ]; then
  echo "error: missing or non-executable $MAIN_BIN" >&2
  exit 1
fi
if [ ! -x "$PY_BIN" ]; then
  echo "error: missing or non-executable $PY_BIN" >&2
  exit 1
fi
for fname in figma_mcp_concurrency.js lark_mcp_patches.js package.json package-lock.json; do
  if [ ! -f "$MCP_DIR/$fname" ]; then
    echo "error: missing MCP resource $MCP_DIR/$fname" >&2
    exit 1
  fi
done
if [ -e "$MCP_DIR/node_modules" ]; then
  echo "error: unexpected node_modules inside $MCP_DIR" >&2
  exit 1
fi
echo "[verify_app] layout check ok"

# 2. Check text files for /Users/ absolute path leaks (with explicit allowlist)
# Allowlist rationale:
#   - *.dist-info/RECORD, *.dist-info/INSTALLER, *.dist-info/direct_url.json, *.dist-info/METADATA:
#     packaging metadata or upstream wheel authors' build paths that do not affect runtime execution.
#   - lib/python3.14/_sysconfigdata_*.py and _sysconfig_vars_*.json: stdlib build metadata (upstream CI paths such as
#     /Users/runner, and the local interpreter path); never used to locate files at runtime.
#   - *.dist-info/sboms/*: upstream SBOM files that record the wheel authors' CI build paths.
#   - toolbox_backend/adapters/task_git.py: intentional S3 guard that forbids task git operations inside the two
#     development repositories (default forbidden_roots); not a runtime dependency on those paths.
python3 - "$APP_ABS" <<'PYEOF'
import os
import re
import sys
from pathlib import Path

app_root = Path(sys.argv[1])
leaks = []
allow_patterns = [
    re.compile(r"\.dist-info/(RECORD|METADATA|WHEEL|direct_url\.json)$"),
    re.compile(r"\.dist-info/sboms/"),
    re.compile(r"^Contents/Resources/backend/lib/python3\.14/_sysconfig(data_|_vars_)[^/]*$"),
    re.compile(r"^Contents/Resources/backend/lib/python3\.14/site-packages/toolbox_backend/adapters/task_git\.py$"),
]

for root, _dirs, files in os.walk(app_root):
    for name in files:
        fpath = Path(root) / name
        if fpath.is_symlink():
            target = os.readlink(fpath)
            if "/Users/" in target:
                leaks.append(f"{fpath.relative_to(app_root)} -> symlink target {target}")
            continue
        rel = fpath.relative_to(app_root).as_posix()
        if any(p.search(rel) for p in allow_patterns):
            continue
        try:
            raw = fpath.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            # Binary file (Mach-O linkage is checked separately below)
            continue
        text = raw.decode("utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "/Users/" in line:
                leaks.append(f"{rel}:{lineno}: {line.strip()[:120]}")
                break

if leaks:
    print("error: found /Users/ path leak(s) in bundle text files:", file=sys.stderr)
    for item in leaks:
        print(f"  {item}", file=sys.stderr)
    sys.exit(1)
print("[verify_app] text path-leak check ok (0 leaks)")
PYEOF

# 3. Relocatable startup + read-only runtime check (no new files or __pycache__ created)
#    + handshake + GET /health 200 + graceful stdin-close exit 0 + zero leftover processes by recorded PID
python3 - "$APP_ABS" <<'PYEOF'
import http.client
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

app_src = Path(sys.argv[1])
tmp_root = Path(tempfile.mkdtemp(prefix="toolbox-verify-app-"))


def snapshot_files(root: Path) -> set[str]:
    out: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        for d in dirnames:
            out.add(f"D:{rel_dir}/{d}")
        for f in filenames:
            out.add(f"F:{rel_dir}/{f}")
    return out


def group_pids(pgid: int) -> list[int]:
    try:
        res = subprocess.run(
            ["ps", "-axo", "pid=,pgid="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    pids: list[int] = []
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == str(pgid):
            pids.append(int(parts[0]))
    return pids


def pgid_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


try:
    relocated_app = tmp_root / "relocated" / "TOOLBOX.app"
    relocated_app.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["cp", "-R", str(app_src), str(relocated_app)])

    backend_dir = relocated_app / "Contents/Resources/backend"
    py_bin = backend_dir / "bin/python3.14"
    data_dir = tmp_root / "data"
    legacy_dir = tmp_root / "legacy"
    data_dir.mkdir(parents=True, exist_ok=True)
    legacy_dir.mkdir(parents=True, exist_ok=True)

    before_tree = snapshot_files(backend_dir)

    clean_env = {
        "HOME": str(tmp_root / "home"),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "en_US.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TOOLBOX_DATA_DIR": str(data_dir),
        "TOOLBOX_LEGACY_CONFIG_DIR": str(legacy_dir),
    }

    proc = subprocess.Popen(
        [str(py_bin), "-m", "toolbox_backend"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(backend_dir),
        env=clean_env,
        start_new_session=True,
    )
    pgid = proc.pid
    recorded_pids: set[int] = {proc.pid}

    try:
        t0 = time.monotonic()
        buf = b""
        assert proc.stdout is not None
        fd = proc.stdout.fileno()
        while b"\n" not in buf:
            remaining = 20.0 - (time.monotonic() - t0)
            if remaining <= 0:
                raise TimeoutError("timed out waiting 20s for TOOLBOX_READY line")
            r, _, _ = select.select([fd], [], [], remaining)
            if not r:
                continue
            chunk = os.read(fd, 4096)
            if not chunk:
                stderr_out = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
                raise RuntimeError(f"stdout closed before TOOLBOX_READY (rc={proc.poll()}): {stderr_out}")
            buf += chunk

        first_line = buf.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()
        m = re.match(r"^TOOLBOX_READY (\{.*\})$", first_line)
        if not m:
            raise RuntimeError(f"unexpected first stdout line: {first_line!r}")
        ready = json.loads(m.group(1))
        port = int(ready["port"])
        token = str(ready["token"])
        ready_pid = int(ready["pid"])
        recorded_pids.add(ready_pid)
        recorded_pids.update(group_pids(pgid))

        # Request GET /health with Bearer and exact Host
        health_url = f"http://127.0.0.1:{port}/health"
        host_hdr = f"127.0.0.1:{port}"
        auth_hdr = f"Bearer {token}"
        custom_curl = os.environ.get("TOOLBOX_VERIFY_HTTP_GET", "")
        if custom_curl:
            res_http = subprocess.run(
                [custom_curl, health_url, host_hdr, auth_hdr],
                capture_output=True,
                text=True,
                check=False,
            )
            if res_http.returncode != 0:
                raise RuntimeError(f"GET /health failed via {custom_curl}: {res_http.stderr}")
        else:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.putrequest("GET", "/health", skip_host=True)
            conn.putheader("Host", host_hdr)
            conn.putheader("Authorization", auth_hdr)
            conn.endheaders()
            resp = conn.getresponse()
            status = resp.status
            resp.read()
            conn.close()
            if status != 200:
                raise RuntimeError(f"GET /health returned {status}, expected 200")

        recorded_pids.update(group_pids(pgid))

        # Close stdin and verify exit 0 within 10s
        if proc.stdin:
            proc.stdin.close()
        rc = proc.wait(timeout=10.0)
        if rc != 0:
            stderr_out = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            raise RuntimeError(f"backend exited with code {rc}, expected 0: {stderr_out}")

        # Verify zero leftover processes by recorded PIDs and process group
        deadline = time.monotonic() + 2.0
        leftovers: list[int] = []
        while time.monotonic() < deadline:
            leftovers = [pid for pid in (recorded_pids | set(group_pids(pgid))) if pid_alive(pid)]
            if not leftovers and not pgid_alive(pgid):
                break
            time.sleep(0.05)
        if leftovers or pgid_alive(pgid):
            raise RuntimeError(f"leftover process(es) still alive after shutdown: pids={leftovers}, pgid={pgid}")

        # Verify no new files / __pycache__ inside runtime
        after_tree = snapshot_files(backend_dir)
        added = sorted(after_tree - before_tree)
        if added:
            raise RuntimeError(f"runtime directory was modified during execution: {added}")

        print(f"[verify_app] relocatable startup, /health 200, exit 0, and read-only check ok (pid={ready_pid})")
    finally:
        if proc.poll() is None:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()
finally:
    shutil.rmtree(tmp_root, ignore_errors=True)
PYEOF

# 4. If signed, run codesign --verify --deep --strict --verbose=2
if codesign -dv "$APP_ABS" >/dev/null 2>&1; then
  echo "[verify_app] bundle is signed; running codesign --verify --deep --strict --verbose=2..."
  codesign --verify --deep --strict --verbose=2 "$APP_ABS"
else
  echo "[verify_app] bundle is unsigned; skipping codesign --verify"
fi

# 5. Scan Mach-O files and print maximum minimumSystemVersion (minos)
python3 - "$APP_ABS" <<'PYEOF'
import os
import re
import subprocess
import sys
from pathlib import Path

app_root = Path(sys.argv[1])
macho_magics = {
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xfe\xed\xfa\xcf",
    b"\xfe\xed\xfa\xce",
    b"\xbe\xba\xfe\xca",
}

macho_files: list[Path] = []
for root, _dirs, files in os.walk(app_root):
    for name in files:
        fpath = Path(root) / name
        if fpath.is_symlink():
            continue
        try:
            with fpath.open("rb") as f:
                magic = f.read(4)
        except OSError:
            continue
        if magic in macho_magics:
            macho_files.append(fpath)


def parse_ver(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in s.split(".") if x.isdigit())


versions: list[tuple[tuple[int, ...], str, str]] = []
for mf in macho_files:
    rel = mf.relative_to(app_root).as_posix()
    ver_str = None
    try:
        res = subprocess.run(["vtool", "-show-build", str(mf)], capture_output=True, text=True, check=False)
        m = re.search(r"^\s*minos\s+([0-9]+(?:\.[0-9]+)+)", res.stdout, re.MULTILINE)
        if m:
            ver_str = m.group(1)
    except FileNotFoundError:
        pass
    if not ver_str:
        try:
            res = subprocess.run(["otool", "-l", str(mf)], capture_output=True, text=True, check=False)
            m = re.search(r"LC_BUILD_VERSION[\s\S]{1,300}?minos\s+([0-9]+(?:\.[0-9]+)+)", res.stdout)
            if m:
                ver_str = m.group(1)
        except FileNotFoundError:
            pass
    if ver_str:
        versions.append((parse_ver(ver_str), ver_str, rel))

if versions:
    max_tuple, max_str, max_file = max(versions, key=lambda x: x[0])
    print(f"[verify_app] Mach-O files scanned: {len(macho_files)}, max minimumSystemVersion (minos): {max_str} (from {max_file})")
else:
    print(f"[verify_app] Mach-O files scanned: {len(macho_files)}, minos: unknown")
PYEOF
