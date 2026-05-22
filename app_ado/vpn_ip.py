from __future__ import annotations

import re
import subprocess

# Harmony VPN 给本机分配的地址都在 10.254.x.x 段。
_HARMONY_PREFIX = "10.254."


def get_vpn_ip() -> str | None:
    """返回当前 Harmony VPN 的 IPv4 地址；没连上则返回 None。

    utun 网卡编号不固定（今天 utun4、明天可能 utun5），所以这里不写死网卡名，
    而是扫描所有 utun* 网卡，挑出带 Harmony（10.254.x.x）地址的那一个。
    """
    try:
        out = subprocess.run(
            ["ifconfig"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except Exception:
        return None

    in_utun = False
    for line in out.splitlines():
        if line and not line[0].isspace():
            # 网卡头一行，例如 "utun4: flags=8051<...>"
            name = line.split(":", 1)[0]
            in_utun = name.startswith("utun")
            continue
        if in_utun:
            m = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)", line)
            if m and m.group(1).startswith(_HARMONY_PREFIX):
                return m.group(1)
    return None
