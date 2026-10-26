"""Read-only service configuration and safe direct-exec binary/URL resolution."""

import ipaddress
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from toolbox_backend.domain.errors import SettingsError


@dataclass(frozen=True)
class CodeServerConfig:
    auth: str | None = None
    bind_addr: str | None = None
    host: str = "127.0.0.1"
    port: int = 8080
    safe: bool = False


def read_code_server_config(path: Path) -> CodeServerConfig:
    # Only whitelisted top-level scalar lines reach the YAML parser. Password values
    # are never parsed, returned, registered, or logged. Ambiguous YAML fails closed.
    try:
        allowed = {}
        with path.open("r", encoding="utf-8") as stream:
            size = 0
            for line in stream:
                size += len(line.encode())
                if size > 65536:
                    return CodeServerConfig()
                if (
                    line.strip()
                    and not line.lstrip().startswith("#")
                    and not re.match(r"^[A-Za-z][A-Za-z0-9_-]*:", line)
                ):
                    return CodeServerConfig()
                match = re.match(r"^(auth|bind-addr):\s*(.*?)\s*$", line)
                if match:
                    key, value = match.groups()
                    if key in allowed:
                        return CodeServerConfig()
                    scalar = yaml.safe_load(value)
                    if not isinstance(scalar, str):
                        return CodeServerConfig()
                    allowed[key] = scalar
        bind = allowed.get("bind-addr")
        if not bind or any(c.isspace() for c in bind):
            return CodeServerConfig()
        url = urlsplit("http://" + bind)
        if url.path or url.query or url.fragment or url.username or url.password:
            return CodeServerConfig()
        host, port = url.hostname, url.port
        if not host or not port or not 1 <= port <= 65535:
            return CodeServerConfig()
        # Readiness checks use loopback even for a wildcard bind.
        ip = ipaddress.ip_address(host) if host != "localhost" else None
        probe_host = "127.0.0.1" if host in {"0.0.0.0", "localhost"} else host
        if host == "::":
            probe_host = "::1"
        safe = allowed.get("auth") == "password" and (ip is not None or host == "localhost")
        return CodeServerConfig(allowed.get("auth"), bind, probe_host, port, safe)
    except OSError, ValueError, yaml.YAMLError:
        return CodeServerConfig()


def resolve_binary(name: str, confirmed=None, *, path_extras=None) -> str:
    if name not in {"code-server", "cloudflared"}:
        raise SettingsError("service_binary_missing", "服务程序不可用")
    paths = path_extras if path_extras is not None else ["/opt/homebrew/bin"]
    search = os.pathsep.join([os.environ.get("PATH", ""), *(str(p) for p in paths)])
    found = confirmed or shutil.which(name, path=search)
    try:
        if not found or not Path(found).is_absolute():
            raise ValueError
        path = Path(found).resolve(strict=True)
        info = path.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or not os.access(path, os.X_OK)
            or info.st_uid not in {os.getuid(), 0}
            or info.st_mode & stat.S_IWOTH
        ):
            raise ValueError
        return str(path)
    except OSError, ValueError:
        raise SettingsError("service_binary_missing", "服务程序不可用") from None


def validate_tunnel_target(value: str, ack_public: bool) -> str:
    try:
        if (
            ack_public is not True
            or len(value) > 2048
            or not value.isascii()
            or re.search(r"[\s\\\x00-\x1f\x7f]", value)
            or "%" in value
        ):
            raise ValueError
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or url.hostname not in {"localhost", "127.0.0.1", "::1"}
            or url.username is not None
            or url.password is not None
            or url.port is None
            or not 1 <= url.port <= 65535
            or url.fragment
            or url.query
        ):
            raise ValueError
        host = "[::1]" if url.hostname == "::1" else url.hostname
        # Require a canonical authority; reject encoded, case-folded and unusual IP forms.
        if url.netloc != f"{host}:{url.port}":
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9/_.~!$&()*+,;=:@-]*", url.path):
            raise ValueError
        return value
    except ValueError, TypeError:
        raise SettingsError("tunnel_target_forbidden", "隧道仅允许已确认的本机回环地址") from None
