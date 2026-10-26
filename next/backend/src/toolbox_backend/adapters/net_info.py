"""Bounded fixed-argv ifconfig adapter. No default-route fallback or DNS lookup."""

import asyncio
import ipaddress
import re
import shutil

from toolbox_backend.adapters.ai_process import SupervisedProcess, child_environment
from toolbox_backend.api.services_schemas import NetworkInfo

LIMIT = 1 << 20
PRIVATE = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def parse_ifconfig(text: str) -> NetworkInfo:
    info = NetworkInfo()
    interface = ""
    for line in text.splitlines():
        header = re.match(r"^([A-Za-z0-9]+):", line)
        if header:
            interface = header[1]
        address = re.match(r"^\s+inet\s+(\d+\.\d+\.\d+\.\d+)\b", line)
        if not address:
            continue
        try:
            ip = ipaddress.IPv4Address(address[1])
        except ValueError:
            continue
        if interface.startswith("utun") and str(ip).startswith("10.254.") and info.vpn_ip is None:
            info.vpn_ip = str(ip)
        if interface.startswith("en") and any(ip in n for n in PRIVATE) and info.lan_ip is None:
            info.lan_ip, info.on_lan = str(ip), True
    return info


async def read_network(*, cwd, path_extras=None) -> NetworkInfo:
    env = child_environment(path_extras=path_extras)
    executable = shutil.which("ifconfig", path=env["PATH"])
    if not executable:
        return NetworkInfo()
    owner = None
    try:
        async with asyncio.timeout(5):
            owner = await SupervisedProcess.start([executable], str(cwd), stdio=True, env=env)
            data = bytearray()

            async def drain(stream, collect=False):
                while chunk := await stream.read(65536):
                    data.extend(chunk if collect else b"")
                    if len(data) > LIMIT:
                        raise ValueError("ifconfig output limit")

            await asyncio.gather(drain(owner.stdout, True), drain(owner.stderr, True))
            if await owner.proc.wait() != 0:
                return NetworkInfo()
            return parse_ifconfig(data.decode(errors="replace"))
    except OSError, RuntimeError, ValueError, TimeoutError:
        return NetworkInfo()
    finally:
        if owner:
            await owner.close()
