#!/usr/bin/env python3
"""Stand-in for toolbox_backend used by the supervisor tests.

It never opens a port: only the process/handshake semantics are simulated.
Behaviour is selected by environment variables:

  FAKE_MODE                 ok (default) | stdin_only | ignore_term | no_output |
                            bad_line | long_line | leak_token | stdout_after_ready |
                            grandchild_crash
  FAKE_TOKEN                token to announce (default: test-token-fixture)
  FAKE_STATE_DIR            directory for marker files (runs, pids, term, stdin_eof,
                            grandchild.pid)
  FAKE_FAIL_BEFORE_READY_RUNS  exit(2) before READY for the first N runs
  FAKE_CRASH_RUNS           exit(3) shortly after READY for the first N runs
  FAKE_CRASH_DELAY          seconds between READY and the crash (default 0.05)
"""
import os
import signal
import subprocess
import sys
import time

mode = os.environ.get("FAKE_MODE", "ok")
token = os.environ.get("FAKE_TOKEN", "test-token-fixture")
state_dir = os.environ.get("FAKE_STATE_DIR")


def mark(name, text=""):
    if not state_dir:
        return
    with open(os.path.join(state_dir, name), "a") as f:
        f.write(text + "\n")


def run_number():
    mark("runs", str(os.getpid()))
    mark("pids", str(os.getpid()))
    with open(os.path.join(state_dir, "runs")) as f:
        return len(f.read().split())


run = run_number() if state_dir else 1
sys.stderr.write("fake backend starting run=%d mode=%s\n" % (run, mode))
sys.stderr.flush()

if run <= int(os.environ.get("FAKE_FAIL_BEFORE_READY_RUNS", "0")):
    sys.exit(2)


def on_term(_sig, _frm):
    mark("term", "TERM")
    if mode in ("ok", "leak_token", "stdout_after_ready"):
        os._exit(0)
    # ignore_term / stdin_only: keep running (but record the signal)


signal.signal(signal.SIGTERM, on_term)

if mode == "no_output":
    time.sleep(3600)
if mode == "bad_line":
    sys.stdout.write("garbage-secret-content not a ready line\n")
    sys.stdout.flush()
    time.sleep(3600)
if mode == "long_line":
    sys.stdout.write("x" * 100000 + "\n")
    sys.stdout.flush()
    time.sleep(3600)

if mode in ("ignore_term", "grandchild_crash"):
    # Grandchild in the same process group that ignores SIGTERM.
    gc = subprocess.Popen(
        [sys.executable, "-c",
         "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(3600)"],
        stdin=subprocess.DEVNULL,
    )
    mark("grandchild.pid", str(gc.pid))

ready = 'TOOLBOX_READY {"v":1,"port":%d,"token":"%s","pid":%d}\n' % (
    40000 + run, token, os.getpid())
sys.stdout.write(ready)
sys.stdout.flush()

if mode == "leak_token":
    sys.stderr.write("leaked token=%s end\n" % token)
    sys.stderr.flush()
if mode == "stdout_after_ready":
    sys.stdout.write("unexpected-stdout-content\n")
    sys.stdout.flush()

if run <= int(os.environ.get("FAKE_CRASH_RUNS", "0")):
    time.sleep(float(os.environ.get("FAKE_CRASH_DELAY", "0.05")))
    sys.exit(3)
if mode == "grandchild_crash":
    time.sleep(0.2)
    os._exit(4)  # leave the grandchild behind

if mode == "ignore_term":
    while True:  # ignores stdin EOF too
        time.sleep(3600)

# ok / stdin_only / leak_token / stdout_after_ready: exit 0 when stdin closes.
try:
    sys.stdin.read()
finally:
    mark("stdin_eof", "EOF")
sys.exit(0)
