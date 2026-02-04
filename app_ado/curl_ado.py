from __future__ import annotations

import base64
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class CurlResult:
    status: int | None
    headers: dict[str, str]
    body: str
    raw: str


def _basic_auth_from_pat(pat: str) -> str:
    token = base64.b64encode(f":{pat}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


def curl_get_raw(url: str, *, pat: str, timeout_sec: int = 12) -> CurlResult:
    # -sS: silent but show errors
    # -i : include headers
    # --max-time: overall timeout
    cmd = [
        "curl",
        "-sS",
        "-i",
        "--max-time",
        str(timeout_sec),
        "-H",
        f"Authorization: {_basic_auth_from_pat(pat)}",
        "-H",
        "Accept: application/json",
        url,
    ]

    cp = subprocess.run(cmd, capture_output=True, text=True)
    raw = (cp.stdout or "") + (cp.stderr or "")

    # Parse status line + headers
    status: int | None = None
    headers: dict[str, str] = {}
    body = cp.stdout or ""

    if cp.stdout and "\r\n\r\n" in cp.stdout:
        head, body = cp.stdout.split("\r\n\r\n", 1)
    elif cp.stdout and "\n\n" in cp.stdout:
        head, body = cp.stdout.split("\n\n", 1)
    else:
        head = ""

    lines = [ln.strip() for ln in head.splitlines() if ln.strip()]
    for ln in lines:
        if ln.lower().startswith("http/"):
            # HTTP/1.1 200 OK
            parts = ln.split()
            if len(parts) >= 2 and parts[1].isdigit():
                status = int(parts[1])
        elif ":" in ln:
            k, v = ln.split(":", 1)
            headers[k.strip().lower()] = v.strip()

    return CurlResult(status=status, headers=headers, body=body, raw=raw)
