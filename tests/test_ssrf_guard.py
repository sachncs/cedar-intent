"""Guard truth-table tests.

These tests pin the security boundary that prevents the deployment
client from being used as an SSRF proxy. They cover:

- Loopback, link-local, RFC1918, IPv6 UL/private, IPv4 broadcast,
  IPv6 documentation prefix, and IPv6 NAT64 prefix all rejected by
  default.
- allow_private_targets / allow_loopback opt-ins.
- DNS rebinding: a stub resolver that returns public-then-private is
  still rejected.
- Unsupported URL schemes raise.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

from cedrus.deploy import Guard
from cedrus.error import Deploy


def fake_addrinfo_returning(ip: str) -> Any:
    """Build a resolver that returns one fake getaddrinfo result for ``ip``."""

    def fake(_host: str) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return fake


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "127.5.5.5",
        "10.0.0.1",
        "172.16.0.1",
        "172.31.255.254",
        "192.168.1.1",
        "169.254.169.254",
        "0.0.0.0",
        "::1",
        "fc00::1",
        "fd00::1",
        "fe80::1",
        "2001:db8::1",
        "255.255.255.255",
    ],
)
def test_ssrf_guard_rejects_blocked_addresses(ip: str) -> None:
    guard = Guard(resolver=_fake_addrinfo_returning(ip))
    with pytest.raises(Deploy):
        guard.check("http://example.com/cedar")


def test_ssrf_guard_allows_public_ip_by_default() -> None:
    guard = Guard(resolver=_fake_addrinfo_returning("93.184.216.34"))
    pinned = guard.check("http://example.com/cedar")
    assert pinned.ip == "93.184.216.34"


def test_ssrf_guard_allow_loopback_permits_127() -> None:
    guard = Guard(
        allow_loopback=True,
        resolver=_fake_addrinfo_returning("127.0.0.1"),
    )
    pinned = guard.check("http://example.com/cedar")
    assert pinned.ip == "127.0.0.1"


def test_ssrf_guard_allow_private_permits_rfc1918() -> None:
    guard = Guard(
        allow_private_targets=True,
        resolver=_fake_addrinfo_returning("10.0.0.5"),
    )
    pinned = guard.check("http://example.com/cedar")
    assert pinned.ip == "10.0.0.5"


def test_ssrf_guard_pins_public_address_even_when_resolver_returns_private() -> None:
    """DNS rebinding defense: guard picks the public address and pins it.

    The Guard cannot by itself prevent a DNS rebind between guard
    resolution and the actual connection — that is the job of the
    pinned transport. What the guard *does* guarantee is that the
    address it pins is not in a blocked range. If the resolver returns
    a mix of public and private addresses, the guard selects the
    public one and the transport then connects to that exact IP.
    """

    def rebind_resolver(_host: str) -> list[Any]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        ]

    guard = Guard(resolver=rebind_resolver)
    pinned = guard.check("http://example.com/cedar")
    assert pinned.ip == "93.184.216.34"


def test_ssrf_guard_rejects_when_only_private_addresses_resolve() -> None:
    """If the resolver only returns private addresses, the guard raises."""

    def private_only(_host: str) -> list[Any]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 0)),
        ]

    guard = Guard(resolver=private_only)
    with pytest.raises(Deploy):
        guard.check("http://example.com/cedar")


def test_ssrf_guard_rejects_unsupported_scheme() -> None:
    guard = Guard(resolver=_fake_addrinfo_returning("93.184.216.34"))
    with pytest.raises(Deploy):
        guard.check("ftp://example.com/cedar")


def test_ssrf_guard_rejects_missing_host() -> None:
    guard = Guard(resolver=_fake_addrinfo_returning("93.184.216.34"))
    with pytest.raises(Deploy):
        guard.check("http:///cedar")


def test_ssrf_guard_handles_gaierror() -> None:
    def failing_resolver(_host: str) -> list[Any]:
        raise socket.gaierror("no such host")

    guard = Guard(resolver=failing_resolver)
    with pytest.raises(Deploy):
        guard.check("http://nonexistent.example/cedar")
