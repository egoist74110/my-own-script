"""Pure, isolated S7-A adapter safety requirements."""

import pytest

from toolbox_backend.adapters.net_info import parse_ifconfig
from toolbox_backend.adapters.service_runtime import (
    read_code_server_config,
    resolve_binary,
    validate_tunnel_target,
)
from toolbox_backend.domain.errors import SettingsError


def test_custom_tunnel_requires_explicit_public_exposure_acknowledgement():
    with pytest.raises(SettingsError) as exc:
        validate_tunnel_target("http://127.0.0.1:8080", ack_public=False)
    assert exc.value.code == "tunnel_target_forbidden"

    assert validate_tunnel_target("http://127.0.0.1:8080", ack_public=True)


def test_custom_tunnel_allows_canonical_ipv6_loopback():
    assert validate_tunnel_target("http://[::1]:8080", ack_public=True) == "http://[::1]:8080"


@pytest.mark.parametrize(
    "target",
    ["http://127.0.0.1:0", "http://127.0.0.1:65536", "http://127.0.0.1"],
)
def test_custom_tunnel_rejects_missing_or_out_of_range_port(target):
    with pytest.raises(SettingsError) as exc:
        validate_tunnel_target(target, ack_public=True)
    assert exc.value.code == "tunnel_target_forbidden"


@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1@evil.example:8080",
        "http://[::1]@evil.example:8080",
        "http://[2001:db8::1]:8080",
        "http://[::ffff:127.0.0.1]:8080",
        "http://localhost.evil.example:8080",
        "http://127.0.0.1.evil.example:8080",
        "http://127.0.0.1\\@evil.example:8080",
        "http://127.0.0.1:8080@evil.example",
    ],
)
def test_custom_tunnel_rejects_non_loopback_or_ambiguous_authorities(target):
    with pytest.raises(SettingsError) as exc:
        validate_tunnel_target(target, ack_public=True)
    assert exc.value.code == "tunnel_target_forbidden"


def test_code_server_config_returns_only_safe_connection_metadata(tmp_path):
    config = tmp_path / "code-server.yaml"
    config.write_text(
        "auth: password\n"
        "bind-addr: 127.0.0.1:8080\n"
        "password: TOP_SECRET_DO_NOT_READ\n"
        "cert: /private/cert.pem\n",
        encoding="utf-8",
    )

    result = read_code_server_config(config)
    assert result.auth == "password"
    assert result.bind_addr == "127.0.0.1:8080"
    assert result.host == "127.0.0.1"
    assert result.port == 8080
    assert result.safe is True
    assert "TOP_SECRET_DO_NOT_READ" not in repr(result)


@pytest.mark.parametrize(
    "raw",
    [
        "auth: none\nbind-addr: 0.0.0.0:8080\npassword: SHOULD_NOT_BE_READ\n",
        "auth: none\nbind-addr: 192.168.1.8:8080\n",
    ],
)
def test_code_server_rejects_unauthenticated_non_loopback_config(tmp_path, raw):
    config = tmp_path / "code-server.yaml"
    config.write_text(raw, encoding="utf-8")

    result = read_code_server_config(config)
    assert result.safe is False
    assert "SHOULD_NOT_BE_READ" not in repr(result)


def test_code_server_config_without_auth_or_unreadable_file_fails_closed(tmp_path):
    config = tmp_path / "code-server.yaml"
    config.write_text("bind-addr: 127.0.0.1:8080\n", encoding="utf-8")

    undeclared = read_code_server_config(config)
    unreadable = read_code_server_config(tmp_path / "missing-code-server.yaml")
    assert undeclared.auth is None
    assert undeclared.safe is False
    assert unreadable.safe is False


def test_binary_resolver_rejects_world_writable_executable(tmp_path):
    binary = tmp_path / "cloudflared"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o777)

    with pytest.raises(SettingsError) as exc:
        resolve_binary("cloudflared", confirmed=str(binary))
    assert exc.value.code == "service_binary_missing"


def test_ifconfig_uses_only_en_private_address_for_lan_and_utun_for_vpn():
    sample = """\
lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
        inet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
        inet 192.168.10.7 netmask 0xffffff00 broadcast 192.168.10.255
utun4: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380
        inet 10.254.0.3 --> 10.254.0.3 netmask 0xffffffff
"""

    result = parse_ifconfig(sample)
    assert result.vpn_ip == "10.254.0.3"
    assert result.lan_ip == "192.168.10.7"
    assert result.on_lan is True


def test_ifconfig_does_not_fallback_to_other_interfaces_or_default_route():
    sample = """\
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
        inet 169.254.12.8 netmask 0xffff0000
bridge0: flags=8863<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> mtu 1500
        inet 192.168.1.42 netmask 0xffffff00
utun4: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380
        inet 10.254.0.3 --> 10.254.0.3 netmask 0xffffffff
default            192.168.1.1            UGScg                 en0
"""

    result = parse_ifconfig(sample)
    assert result.vpn_ip == "10.254.0.3"
    assert result.lan_ip is None
    assert result.on_lan is False


def test_ifconfig_uses_first_en_private_ip_and_allows_missing_vpn():
    sample = """\
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
        inet 10.20.0.9 netmask 0xffffff00
en1: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
        inet 172.20.4.5 netmask 0xffffff00
bridge0: flags=8863<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> mtu 1500
        inet 192.168.1.99 netmask 0xffffff00
"""

    result = parse_ifconfig(sample)
    assert result.lan_ip == "10.20.0.9"
    assert result.vpn_ip is None
    assert result.on_lan is True
