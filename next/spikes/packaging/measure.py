#!/usr/bin/env python3
"""S0-D measurement harness (stdlib only, py3.9+ compatible; run with /usr/bin/python3).

Spawns the backend per variant, reads the READY line, polls /health, samples RSS, tears down by
process group (the group id is the pid we spawned with start_new_session; never by process name).
Every number written to the results JSON carries the command/method that produced it.
"""
import argparse
import http.client
import json
import os
import platform
import re
import select
import shutil
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SPIKE = REPO / "next/.local/spike"
SCRATCH = SPIKE / "measure-scratch"
CLEAN_ENV = {"HOME": "/nonexistent", "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}
READY_TIMEOUT = 60.0


def variants():
    pbs = SPIKE / "pbs/runtime"
    pyi = SPIKE / "pyinstaller/toolbox-backend"
    return {
        "A_pbs": (pbs, ["bin/python3.14", "-m", "toolbox_backend"]),
        "B_pyinstaller": (pyi, ["toolbox-backend"]),
    }


def du_kib(path):
    return int(subprocess.check_output(["du", "-sk", str(path)]).split()[0])


def group_procs(pgid):
    out = subprocess.run(["ps", "-axo", "pid=,pgid=,rss=,comm="], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 3 and parts[1] == str(pgid):
            rows.append((int(parts[0]), int(parts[2])))
    return rows


def run_once(app_dir, rel_cmd, idle_s=0.0, cwd="/"):
    """Return dict of timings. t0 = just before Popen."""
    cmd = [str(Path(app_dir) / rel_cmd[0])] + rel_cmd[1:]
    errlog = open(SCRATCH / "stderr.log", "wb")
    t0 = time.monotonic()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errlog,
                         env=CLEAN_ENV, cwd=cwd, start_new_session=True)
    res = {"ok": False}
    pgid = p.pid
    try:
        buf = b""
        fd = p.stdout.fileno()
        while b"\n" not in buf:
            left = READY_TIMEOUT - (time.monotonic() - t0)
            if left <= 0:
                raise TimeoutError("no READY line")
            r, _, _ = select.select([fd], [], [], left)
            if not r:
                continue
            chunk = os.read(fd, 4096)
            if not chunk:
                raise RuntimeError("stdout closed before READY, rc=%s" % p.poll())
            buf += chunk
        t_ready = time.monotonic()
        line = buf.split(b"\n")[0].decode()
        m = re.match(r"TOOLBOX_READY (\{.*\})$", line)
        if not m:
            raise RuntimeError("bad READY line shape")
        info = json.loads(m.group(1))
        res["ready_s"] = t_ready - t0
        res["ready_pid_matches_child"] = info["pid"] == p.pid or info["pid"] in [x[0] for x in group_procs(pgid)]
        # first /health 200
        status = None
        while True:
            conn = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=5)
            conn.putrequest("GET", "/health", skip_host=True)
            conn.putheader("Host", "127.0.0.1:%d" % info["port"])
            conn.putheader("Authorization", "Bearer " + info["token"])
            conn.endheaders()
            resp = conn.getresponse()
            status = resp.status
            resp.read()
            conn.close()
            if status == 200 or time.monotonic() - t0 > READY_TIMEOUT:
                break
        t_health = time.monotonic()
        res["health_status"] = status
        res["health_from_spawn_s"] = t_health - t0
        res["health_after_ready_s"] = t_health - t_ready
        if idle_s:
            time.sleep(idle_s)
            procs = group_procs(pgid)
            res["rss_group_kib"] = sum(x[1] for x in procs)
            res["rss_ready_pid_kib"] = sum(x[1] for x in procs if x[0] == info["pid"])
            res["group_proc_count"] = len(procs)
        res["ok"] = status == 200
    except Exception as exc:  # record and fall through to teardown
        res["error"] = repr(exc)
    finally:
        # graceful: close stdin (contract: EOF -> coordinated exit), then escalate by pgid
        t1 = time.monotonic()
        try:
            p.stdin.close()
        except Exception:
            pass
        try:
            p.wait(timeout=8)
            res["exit_code"] = p.returncode
            res["graceful_exit_s"] = time.monotonic() - t1
        except subprocess.TimeoutExpired:
            res["exit_code"] = "killed"
            os.killpg(pgid, signal.SIGKILL)
            p.wait()
        time.sleep(0.05)
        left = group_procs(pgid)
        if left:
            res["leftover_pids"] = [x[0] for x in left]
            os.killpg(pgid, signal.SIGKILL)
        p.stdout.close()
        errlog.close()
    return res


def med(xs):
    return statistics.median(xs) if xs else None


def summarize(runs, keys):
    out = {"samples": runs}
    for k in keys:
        vals = [r[k] for r in runs if k in r and r.get("ok")]
        out[k + "_median"] = med(vals)
        out[k + "_min"] = min(vals) if vals else None
        out[k + "_max"] = max(vals) if vals else None
    out["all_ok"] = all(r.get("ok") for r in runs)
    out["all_graceful_exit_0"] = all(r.get("exit_code") == 0 for r in runs)
    out["leftover_any"] = any("leftover_pids" in r for r in runs)
    return out


def macho_deps(app_dir):
    """otool -L over every Mach-O file; classify deps."""
    files = []
    for root, _dirs, names in os.walk(app_dir):
        for n in names:
            fp = os.path.join(root, n)
            if os.path.islink(fp):
                continue
            try:
                with open(fp, "rb") as f:
                    magic = f.read(4)
            except OSError:
                continue
            if magic in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xce\xfa\xed\xfe"):
                files.append(fp)
    deps = {}
    for fp in files:
        out = subprocess.run(["otool", "-L", fp], capture_output=True, text=True).stdout.splitlines()[1:]
        for line in out:
            d = line.strip().split(" (")[0]
            deps.setdefault(d, 0)
            deps[d] += 1
    system, internal, foreign = {}, {}, {}
    for d, c in sorted(deps.items()):
        if d.startswith("/usr/lib/") or d.startswith("/System/Library/"):
            system[d] = c
        elif d.startswith("@"):
            internal[d] = c
        else:
            foreign[d] = c
    return {"macho_files_scanned": len(files), "system_libs": system, "relative_libs": internal,
            "non_system_absolute_libs": foreign,
            "method": "walk dir, magic-number detect Mach-O, `otool -L` each, classify by prefix"}


def zip_size(src, dst):
    if dst.exists():
        dst.unlink()
    subprocess.check_call(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(src), str(dst)])
    kib = (dst.stat().st_size + 1023) // 1024
    dst.unlink()
    return kib


def copy_tree(src, dst):
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["cp", "-R", str(src), str(dst)])


def strip_pyc(d):
    subprocess.check_call(["find", str(d), "-type", "d", "-name", "__pycache__", "-prune", "-exec", "rm", "-rf", "{}", "+"])


def measure_variant(name, app, rel, n):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    r = {"dir": str(app), "launch_cmd": rel}
    r["size_uncompressed_kib"] = du_kib(app)
    r["size_uncompressed_method"] = "du -sk <dir>"
    r["size_compressed_kib"] = zip_size(app, SCRATCH / (name + ".zip"))
    r["size_compressed_method"] = "ditto -c -k --sequesterRsrc --keepParent <dir> x.zip ; stat size (deflate, NOT ULFO)"
    # warm
    run_once(app, rel)  # discarded warm-up (primes page cache)
    warm = [run_once(app, rel, idle_s=10.0) for _ in range(n)]
    r["warm"] = summarize(warm, ["ready_s", "health_from_spawn_s", "health_after_ready_s", "rss_group_kib", "rss_ready_pid_kib"])
    r["warm"]["definition"] = "after one discarded warm-up run; same dir; page cache hot; env -i; idle 10s before RSS sample"
    # cold: fresh copy per run (new inodes -> first-exec code-signature/amfid check + no cache for those inodes)
    cold = []
    for i in range(n):
        cdir = SCRATCH / ("cold-%s-%d" % (name, i))
        copy_tree(app, cdir)
        cold.append(run_once(cdir, rel))
        shutil.rmtree(cdir)
    r["cold"] = summarize(cold, ["ready_s", "health_from_spawn_s", "health_after_ready_s"])
    r["cold"]["definition"] = ("each run on a freshly `cp -R` copy (first execution of new files); page cache NOT purged "
                               "(`sudo purge` unavailable), so this is 'first run of a new copy', not true cold-disk")
    # relocation: mv the original away, run from the new path, mv back
    moved = SCRATCH / ("moved-" + name)
    if moved.exists():
        shutil.rmtree(moved)
    shutil.move(str(app), str(moved))
    try:
        rr = run_once(moved, rel)
    finally:
        shutil.move(str(moved), str(app))
    r["relocatable"] = {"ok": bool(rr.get("ok")), "run": rr,
                        "method": "mv dir to another path (original path absent), env -i, cwd=/, run once, expect READY+/health 200"}
    r["linkage"] = macho_deps(app)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--only", choices=["A_pbs", "B_pyinstaller", "A_pbs_nopyc", "startup-only"], default=None)
    ap.add_argument("--startup-only", action="store_true", help="just re-run warm startup/health 3x, print, write nothing")
    ap.add_argument("--out", default=str(REPO / "next/spikes/packaging/results-2026-10-22.json"))
    a = ap.parse_args()
    v = variants()

    if a.startup_only:
        SCRATCH.mkdir(parents=True, exist_ok=True)
        for name, (app, rel) in v.items():
            runs = [run_once(app, rel) for _ in range(a.runs)]
            print(name, json.dumps([{k: (round(x[k], 3) if isinstance(x.get(k), float) else x.get(k)) for k in
                                     ("ok", "ready_s", "health_from_spawn_s", "exit_code", "leftover_pids") if k in x} for x in runs]))
        return 0

    info = {}
    info["date"] = "2026-10-22"
    info["macos"] = subprocess.check_output(["sw_vers", "-productVersion"], text=True).strip()
    info["macos_build"] = subprocess.check_output(["sw_vers", "-buildVersion"], text=True).strip()
    info["chip"] = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
    info["arch"] = platform.machine()
    info["uv"] = subprocess.check_output(["uv", "--version"], text=True).strip()
    pbs_py = v["A_pbs"][0] / "bin/python3.14"
    info["pbs_python"] = subprocess.check_output([str(pbs_py), "--version"], text=True, env=CLEAN_ENV).strip()
    pyi_py = SPIKE / "pyi-env/bin/python"
    info["pyinstaller"] = subprocess.check_output([str(pyi_py), "-m", "PyInstaller", "--version"], text=True).strip()
    info["pyinstaller_build_interpreter"] = subprocess.check_output([str(pyi_py), "--version"], text=True).strip()
    info["harness_python"] = sys.version.split()[0]

    results = {"machine": info, "runs_per_metric": a.runs, "variants": {}}
    for name, (app, rel) in v.items():
        results["variants"][name] = measure_variant(name, app, rel, a.runs)

    # PBS without precompiled pyc (shows what prune-only costs at startup)
    app, rel = v["A_pbs"]
    nopyc = SCRATCH / "pbs-nopyc"
    copy_tree(app, nopyc)
    strip_pyc(nopyc)
    nr = {"dir": str(nopyc), "launch_cmd": rel, "size_uncompressed_kib": du_kib(nopyc),
          "size_uncompressed_method": "cp -R then delete all __pycache__, du -sk",
          "size_compressed_kib": zip_size(nopyc, SCRATCH / "nopyc.zip"),
          "size_compressed_method": "ditto -c -k --sequesterRsrc --keepParent"}
    # first run writes pyc into the dir itself, so each sample needs a fresh pyc-less copy
    runs = []
    for i in range(a.runs):
        d = SCRATCH / ("nopyc-run-%d" % i)
        copy_tree(nopyc, d)
        runs.append(run_once(d, rel))
        shutil.rmtree(d)
    nr["first_run_no_pyc"] = summarize(runs, ["ready_s", "health_from_spawn_s"])
    nr["first_run_no_pyc"]["definition"] = "fresh pyc-less copy per run; interpreter compiles imports on the fly (and writes pyc)"
    shutil.rmtree(nopyc)
    results["variants"]["A_pbs_without_pyc"] = nr

    results["notes"] = [
        "No Tauri shell included in these numbers: see tauri_shell block if present.",
        "Timings: t0 = immediately before subprocess.Popen; READY = line read from child stdout; health = first HTTP 200 on GET /health.",
        "RSS = sum of `ps -axo rss` over the process group (PyInstaller onedir on macOS execs: group had 1 process in all samples), also ready-pid-only.",
    ]
    Path(a.out).write_text(json.dumps(results, indent=2, sort_keys=False) + "\n")
    print("wrote", a.out)
    shutil.rmtree(SCRATCH, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
