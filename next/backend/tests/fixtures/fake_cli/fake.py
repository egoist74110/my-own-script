#!/usr/bin/env python3
"""Offline AI fixture. Never imports or calls a real AI client."""

import argparse
import json
import os
import signal
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--version", action="store_true")
parser.add_argument("--env", action="store_true")
parser.add_argument("--echo", action="store_true")
parser.add_argument("--ignore-term", action="store_true")
parser.add_argument("--grandchild", action="store_true")
parser.add_argument("--pid-file")
parser.add_argument("--output", default="ready")
args = parser.parse_args()
if args.version:
    print("toolbox-fake-ai 1.0")
    sys.exit(0)
if args.ignore_term:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if args.pid_file:
    with open(args.pid_file, "a") as stream:
        stream.write(str(os.getpid()) + "\n")
if args.grandchild:
    subprocess.Popen([sys.executable, __file__, "--ignore-term", "--pid-file", args.pid_file])
if args.env:
    print(json.dumps(dict(os.environ)), flush=True)
print(args.output, flush=True)
if args.echo:
    for line in sys.stdin:
        print("echo:" + line, end="", flush=True)
else:
    while True:
        time.sleep(0.1)
