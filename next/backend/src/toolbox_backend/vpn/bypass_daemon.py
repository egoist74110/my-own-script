"""Standalone macOS IPv4 bypass helper, Python >=3.9, standard library only.

Copied verbatim on export. No imports from the app, no shell, no IPC, fixed root
snapshot/state paths. Run with a separately provisioned root-owned Python -I -S.
"""

import argparse
import ctypes
import fcntl
import hashlib
import ipaddress
import json
import os
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path("/Library/Application Support/toolbox-vpn-bypass")
MAX_ROUTES = 1024


def target(value):
    if not isinstance(value, str) or len(value) > 32:
        raise ValueError("invalid IPv4 target")
    network = ipaddress.IPv4Network(value, strict=True)
    # Never permit defaults, loopback, link-local, multicast or reserved space.
    forbidden = ["0.0.0.0/8", "127.0.0.0/8", "169.254.0.0/16", "224.0.0.0/3"]
    if network.prefixlen == 0 or any(network.overlaps(ipaddress.IPv4Network(n)) for n in forbidden):
        raise ValueError("target must be an ordinary unicast IPv4 address/network")
    return str(network)


def safe_path(value):
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or len(value) > 4096
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
        or any(p in {".", ".."} for p in value.split("/"))
    ):
        raise ValueError("expected absolute path without controls or dot components")
    return value


def validate_config(raw):
    fields = {"enabled", "gateway", "interface", "interval_s", "retention_s", "apps", "targets"}
    if not isinstance(raw, dict) or set(raw) != fields:
        raise ValueError("invalid snapshot fields")
    if type(raw["enabled"]) is not bool:
        raise ValueError("invalid enabled")
    for key, low, high in [("interval_s", 5, 300), ("retention_s", 0, 3600)]:
        if type(raw[key]) is not int or not low <= raw[key] <= high:
            raise ValueError("invalid timing")
    gateway = raw["gateway"]
    if gateway is not None and ("/" in gateway or target(gateway).endswith("/32") is False):
        raise ValueError("invalid gateway")
    interface = raw["interface"]
    if interface is not None and not re.fullmatch(r"en[0-9]{1,3}", interface):
        raise ValueError("invalid physical interface")
    if not isinstance(raw["targets"], list) or len(raw["targets"]) > 256:
        raise ValueError("too many manual targets")
    result = dict(raw, targets=sorted({target(v) for v in raw["targets"]}))
    apps = raw["apps"]
    if not isinstance(apps, list) or len(apps) > 32:
        raise ValueError("too many apps")
    ids = set()
    for app in apps:
        if not isinstance(app, dict) or set(app) != {
            "id",
            "name",
            "enabled",
            "executable_path",
            "application_path",
        }:
            raise ValueError("invalid application")
        if (
            not isinstance(app["id"], str)
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", app["id"])
            or app["id"] in ids
            or type(app["enabled"]) is not bool
            or not isinstance(app["name"], str)
            or not 1 <= len(app["name"]) <= 80
            or any(ord(c) < 32 for c in app["name"])
        ):
            raise ValueError("invalid application fields")
        ids.add(app["id"])
        exe, bundle = app["executable_path"], app["application_path"]
        if (exe is None) == (bundle is None):
            raise ValueError("specify exactly one executable_path/application_path")
        safe_path(exe if exe is not None else bundle)
        if bundle is not None and not bundle.endswith(".app"):
            raise ValueError("application_path must end with .app")
    return result


def command(argv, allowed=(0,)):
    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=8,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
    )
    if completed.returncode not in allowed or len(completed.stdout) > 8_000_000:
        raise RuntimeError("system inspection/route command failed")
    return completed.stdout


def route_table(run=command):
    """Only unscoped IPv4 entries. Parse failure aborts the sweep, never means empty."""
    text = run(["/usr/sbin/netstat", "-rn", "-f", "inet"])
    if "Destination" not in text or "Netif" not in text:
        raise RuntimeError("unrecognized route table")
    routes = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4 or not re.match(r"^(default|[0-9])", parts[0]):
            continue
        dest, gw, flags, interface = parts[:4]
        if "I" in flags:  # interface scoped route is not our unscoped route
            continue
        if dest == "default":
            net = "0.0.0.0/0"
        else:
            address, _, prefix = dest.partition("/")
            octets = len(address.split("."))
            address += ".0" * (4 - octets)
            net = str(
                ipaddress.IPv4Network(address + "/" + (prefix or str(octets * 8)), strict=False)
            )
        if net in routes:
            raise RuntimeError("ambiguous unscoped route")
        routes[net] = {"gateway": gw, "interface": interface, "flags": flags}
    return routes


def physical_gateway(config, routes, run=command):
    gw, iface = config["gateway"], config["interface"]
    if not gw or not iface:
        raise RuntimeError("configure both a physical IPv4 gateway and interface")
    ports = run(["/usr/sbin/networksetup", "-listallhardwareports"])
    if iface not in re.findall(r"^Device: (en[0-9]+)$", ports, flags=re.M):
        raise RuntimeError("interface is not a known physical hardware port")
    link = run(["/sbin/ifconfig", iface])
    if not re.search(r"^\s*status: active\s*$", link, flags=re.M):
        raise RuntimeError("physical interface has no active link")
    address = ipaddress.IPv4Address(gw)
    if not any(
        address in ipaddress.IPv4Network(net)
        and row["interface"] == iface
        and "U" in row["flags"]
        and "G" not in row["flags"]
        and row["gateway"].startswith("link#")
        for net, row in routes.items()
    ):
        raise RuntimeError("gateway has no active on-link physical route")
    return gw, iface


def executable_paths(apps):
    paths = set()
    for app in apps:
        if not app["enabled"]:
            continue
        if app["executable_path"]:
            paths.add(os.path.realpath(app["executable_path"]))
        else:
            bundle = Path(app["application_path"])
            with (bundle / "Contents/Info.plist").open("rb") as stream:
                metadata = stream.read(1_000_001)
                if len(metadata) > 1_000_000:
                    raise RuntimeError("app metadata too large")
                exe = plistlib.loads(metadata).get("CFBundleExecutable")
            if not isinstance(exe, str) or not exe or "/" in exe or exe in {".", ".."}:
                raise RuntimeError("invalid app executable metadata")
            paths.add(os.path.realpath(bundle / "Contents/MacOS" / exe))
    return paths


def discover(config, run=command):
    """Match kernel executable paths, never argv or process-name substring."""
    paths = executable_paths(config["apps"])
    if not paths:
        return []
    libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
    libproc.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    libproc.proc_pidpath.restype = ctypes.c_int
    pids = run(["/bin/ps", "-axo", "pid="]).split()
    found = set()
    for value in pids:
        if not value.isdigit():
            continue
        buffer = ctypes.create_string_buffer(4096)
        if libproc.proc_pidpath(int(value), buffer, len(buffer)) <= 0:
            continue  # processes may exit or be inaccessible
        if os.path.realpath(os.fsdecode(buffer.value)) not in paths:
            continue
        output = run(["/usr/sbin/lsof", "-nP", "-a", "-p", value, "-i4", "-Fn"], (0, 1))
        # Recheck identity after lsof to mitigate PID reuse.
        again = ctypes.create_string_buffer(4096)
        if libproc.proc_pidpath(int(value), again, len(again)) <= 0 or again.value != buffer.value:
            continue
        for line in output.splitlines():
            if not line.startswith("n") or "->" not in line:
                continue
            remote = line.split("->", 1)[1].split(":", 1)[0]
            try:
                found.add(target(remote))
            except ValueError:
                continue
            if len(found) > MAX_ROUTES:
                raise RuntimeError("too many discovered endpoints")
    return sorted(found)


def matches(row, owner):
    return (
        row is not None
        and row["gateway"] == owner["gateway"]
        and row["interface"] == owner["interface"]
        and "G" in row["flags"]
    )


def reconcile(config, state, discovered, routes, gateway, read_routes, mutate, persist, now):
    """Durable ownership journal. Never adopt existing routes or replace conflicts."""
    cache, owned = state["cache"], state["owned"]
    for net in discovered:
        cache[net] = now
    state["cache"] = cache = {
        net: seen for net, seen in cache.items() if 0 <= now - seen <= config["retention_s"]
    }
    desired = set(config["targets"]) | set(cache) if config["enabled"] else set()
    if len(desired | set(owned)) > MAX_ROUTES:
        raise RuntimeError("route capacity exceeded; no changes made")
    events = []
    persist(state)
    for net in sorted(set(owned) | desired):
        row = routes.get(net)
        owner = owned.get(net)
        if owner and owner["phase"] == "pending":
            # Crash between add and acknowledgement: ownership cannot be proven.
            if row is not None:
                events.append([net, "pending_conflict_manual_recovery"])
                continue
            del owned[net]
            persist(state)
            owner = None
        if owner and not matches(row, owner):
            del owned[net]  # route replaced externally: relinquish, never delete it
            persist(state)
            owner = None
        wanted_owner = {"gateway": gateway[0], "interface": gateway[1], "phase": "owned"}
        if owner and (net not in desired or owner != wanted_owner):
            # Refresh immediately before deletion, only remove still-owned exact route.
            if matches(read_routes().get(net), owner):
                mutate("delete", net, owner)
                routes = read_routes()
                if matches(routes.get(net), owner):
                    raise RuntimeError("route deletion verification failed")
                events.append([net, "removed"])
            del owned[net]
            persist(state)
            row = routes.get(net)
            owner = None
        if net not in desired or owner:
            continue
        routes = read_routes()
        if net in routes:
            events.append([net, "unowned_conflict"])
            continue
        owned[net] = dict(wanted_owner, phase="pending")
        persist(state)  # crash-safe journal BEFORE invoking route
        mutate("add", net, wanted_owner)
        routes = read_routes()
        if not matches(routes.get(net), wanted_owner):
            raise RuntimeError("route addition verification failed; pending retained")
        owned[net] = wanted_owner
        persist(state)
        events.append([net, "added_verified"])
    return events


def protected(path, directory=False):
    """Reject symlinks and any user-writable ancestor (including group writable)."""
    path = Path(path)
    for node in [*reversed(path.parents), path]:
        info = node.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError("root path is not protected")
    info = path.lstat()
    if directory and not stat.S_ISDIR(info.st_mode):
        raise RuntimeError("expected protected directory")
    if not directory and not stat.S_ISREG(info.st_mode):
        raise RuntimeError("expected protected file")


def read_json(path):
    protected(path)
    with path.open("rb") as stream:
        data = stream.read(1_000_001)
    if len(data) > 1_000_000:
        raise RuntimeError("root file too large")
    return json.loads(data)


def config_hash(config):
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def save_json(path, value, mode=0o600):
    protected(ROOT, directory=True)
    if path.exists() or path.is_symlink():
        protected(path)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=ROOT)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), mode)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(ROOT, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_state(state):
    save_json(ROOT / "state.json", state)


def publish_status(config, state, routes, events, errors, now):
    desired = (set(config["targets"]) | set(state["cache"])) if config["enabled"] else set()
    rows = []
    for net in sorted(desired | set(state["owned"])):
        owner = state["owned"].get(net)
        row = routes.get(net)
        owned = bool(owner and owner["phase"] == "owned")
        rows.append(
            {
                "target": net,
                "gateway": row["gateway"] if row else None,
                "interface": row["interface"] if row else None,
                "owned": owned,
                "verified": bool(owned and matches(row, owner)),
            }
        )
    save_json(
        ROOT / "status.json",
        {
            "config_hash": config_hash(config),
            "enabled": config["enabled"],
            "last_sweep_at": now,
            "pid": os.getpid(),
            "events": events,
            "targets": rows,
            "errors": errors,
        },
        0o644,
    )


def sweep_once(config, action):
    state = {"cache": {}, "owned": {}}
    routes, events, errors = {}, [], []
    try:
        state_path = ROOT / "state.json"
        if state_path.exists() or state_path.is_symlink():
            state = validate_state(read_json(state_path))
        if action == "undo":
            config = dict(config, enabled=False)
        routes = route_table()
        # Undo requires no gateway or app discovery, and can never add a route.
        gateway = physical_gateway(config, routes) if config["enabled"] else ("", "")
        discovered = discover(config) if config["enabled"] else []

        def mutate(operation, net, owner):
            command(
                [
                    "/sbin/route",
                    "-n",
                    operation,
                    "-net",
                    net,
                    owner["gateway"],
                    "-ifp",
                    owner["interface"],
                ]
            )

        events = reconcile(
            config,
            state,
            discovered,
            routes,
            gateway,
            route_table,
            mutate,
            save_state,
            time.time(),
        )
        routes = route_table()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):  # fmt: skip
        # No paths, process output, or app metadata in the world-readable report.
        errors = ["路由检查、应用发现或修复失败；将在下一周期重试。"]
        routes = {}  # Never publish a successful verification from a stale table.
    publish_status(config, state, routes, events, errors, time.time())
    return 1 if errors else (2 if any("conflict" in e[1] for e in events) else 0)


def validate_state(state):
    if not isinstance(state, dict) or set(state) != {"cache", "owned"}:
        raise ValueError("invalid state")
    for key in ("cache", "owned"):
        if not isinstance(state[key], dict) or len(state[key]) > MAX_ROUTES:
            raise ValueError("invalid state capacity")
        for net, value in state[key].items():
            if target(net) != net:
                raise ValueError("invalid state target")
            if key == "cache":
                if type(value) not in (float, int) or not 0 <= value < 1e12:
                    raise ValueError("invalid cache timestamp")
            elif (
                not isinstance(value, dict)
                or set(value) != {"gateway", "interface", "phase"}
                or target(value["gateway"]) != value["gateway"] + "/32"
                or not re.fullmatch(r"en[0-9]{1,3}", value["interface"])
                or value["phase"] not in {"pending", "owned"}
            ):
                raise ValueError("invalid ownership record")
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["sweep", "loop", "undo"])
    args = parser.parse_args(argv)
    if sys.platform != "darwin" or os.geteuid() != 0:
        parser.error("requires macOS root; use exported installation instructions")
    protected(ROOT, directory=True)
    protected(Path(__file__).absolute())
    executable = Path(sys.executable)
    while executable.is_symlink():
        protected(executable.parent, directory=True)
        if executable.lstat().st_uid != 0:
            raise RuntimeError("unprotected runtime link")
        executable = Path(os.path.abspath(executable.parent / os.readlink(executable)))
    protected(executable)
    lock_path = ROOT / "lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        protected(lock_path)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            config = None
            try:
                config = validate_config(read_json(ROOT / "config.json"))
                result = sweep_once(config, args.action)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):  # fmt: skip
                save_json(
                    ROOT / "status.json",
                    {
                        "config_hash": None,
                        "enabled": False,
                        "last_sweep_at": time.time(),
                        "pid": os.getpid(),
                        "events": [],
                        "targets": [],
                        "errors": ["后台快照或状态无法读取；将在下一周期重试。"],
                    },
                    0o644,
                )
                result = 1
            if args.action != "loop":
                return result
            time.sleep(config["interval_s"] if config else 20)

    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("bypass failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
