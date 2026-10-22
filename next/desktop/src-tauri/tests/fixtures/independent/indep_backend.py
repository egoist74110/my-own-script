#!/usr/bin/env python3
"""Independent stand-in for toolbox_backend (S0-C independent tests).

It never opens a socket. Behaviour is selected by IND_MODE:

  ready               READY; SIGTERM -> exit 0; exit 0 when stdin closes
  silent              never prints READY (SIGTERM uses the default action)
  raw                 prints $IND_RAW_LINE verbatim as the first stdout line
  chatter             READY, then writes to stdout for 1 s, then like ready
  crash_fast          READY, then exit(1) at once
  term_count          READY; each SIGTERM is recorded in "term" and ignored
  grandchild_running  READY after spawning a SIGTERM-ignoring grandchild;
                      SIGTERM -> exit 0
  spawn_on_eof        READY; SIGTERM is recorded, a SIGTERM-ignoring grandchild
                      is spawned from the handler, and the leader exits 0 once
                      both stdin EOF and that grandchild have happened
  stderr_long         READY, then one stderr line with the token starting at
                      byte 4076 (straddles the 4096-byte forwarder chunk)

State files in IND_STATE_DIR:
  procs   "leader <pid>" and "gc <pid>" lines (every process this stand-in makes)
  term    one "TERM" line per SIGTERM received by the leader
"""
import os
import signal
import subprocess
import sys
import time

MODE = os.environ.get("IND_MODE", "ready")
TOKEN = os.environ.get("IND_TOKEN", "ind-token-fixture")
STATE = os.environ.get("IND_STATE_DIR", "")
RAW = os.environ.get("IND_RAW_LINE", "")
# The grandchild announces (via a marker file) that it has installed its
# SIGTERM-ignoring handler, so the leader never reports READY before that.
GC_CODE = (
    "import os,signal,sys,time;"
    "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
    "open(os.path.join(sys.argv[1],'gc_ready_%d'%os.getpid()),'w').close();"
    "time.sleep(3600)"
)


def mark(name, text):
    if STATE:
        with open(os.path.join(STATE, name), "a") as f:
            f.write(text + "\n")


def spawn_grandchild(wait_ready=True):
    gc = subprocess.Popen(
        [sys.executable, "-c", GC_CODE, STATE],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    mark("procs", "gc %d" % gc.pid)
    if wait_ready:
        marker = os.path.join(STATE, "gc_ready_%d" % gc.pid)
        deadline = time.time() + 10
        while not os.path.exists(marker) and time.time() < deadline:
            time.sleep(0.01)
    return gc


def on_term_exit(_sig, _frm):
    os._exit(0)


spawned_on_term = []


def on_term_record(_sig, _frm):
    # Recorded, then (for spawn_on_eof) a grandchild is started *after* the
    # group SIGTERM was delivered, so it is not signalled by it.
    mark("term", "TERM")
    if MODE == "spawn_on_eof" and not spawned_on_term:
        spawned_on_term.append(spawn_grandchild(wait_ready=False))


def emit_ready():
    sys.stdout.write(
        'TOOLBOX_READY {"v":1,"port":41001,"token":"%s","pid":%d}\n'
        % (TOKEN, os.getpid())
    )
    sys.stdout.flush()


mark("procs", "leader %d" % os.getpid())

if MODE in ("term_count", "spawn_on_eof"):
    signal.signal(signal.SIGTERM, on_term_record)
else:
    signal.signal(signal.SIGTERM, on_term_exit)

if MODE == "silent":
    time.sleep(3600)

if MODE == "raw":
    sys.stdout.write(RAW + "\n")
    sys.stdout.flush()
    time.sleep(3600)

if MODE == "grandchild_running":
    spawn_grandchild()

emit_ready()

if MODE == "crash_fast":
    os._exit(1)

if MODE == "chatter":
    end = time.time() + 1.0
    while time.time() < end:
        sys.stdout.write("CHATTER-SECRET-PAYLOAD\n")
        sys.stdout.flush()
        time.sleep(0.02)

if MODE == "stderr_long":
    sys.stderr.write("A" * 4076 + TOKEN + "\n")
    sys.stderr.flush()

if MODE == "term_count":
    while True:
        time.sleep(3600)

if MODE == "spawn_on_eof":
    sys.stdin.read()  # EOF (stop_group drops stdin first)
    while not spawned_on_term:  # wait for the SIGTERM handler's grandchild
        time.sleep(0.01)
    os._exit(0)

# ready / chatter / grandchild_running / stderr_long: exit 0 when stdin closes.
sys.stdin.read()
sys.exit(0)
