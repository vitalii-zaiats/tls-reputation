"""Destination guard for the collector proxy.

The proxy carries strangers' traffic by design, and it runs on a host that
belongs to other people too — another tenant's services on loopback, whatever
the provider exposes on the link-local metadata address, the rest of the
private network. An open CONNECT proxy with no destination policy is an SSRF
lever pointed at all of that: anyone who finds the listen port can ask it to
reach 127.0.0.1, 169.254.169.254, or 10.0.0.0/8, and the proxy would oblige.

So every destination is resolved and every resulting address is checked before
a connection is opened. Only public unicast addresses are allowed. Resolution
happens here, once, and the connection is made to the vetted IP — not to the
hostname again — so a name that resolves to a public address on the first
lookup and a private one on the second (DNS rebinding) cannot slip through.
"""

from __future__ import annotations

import ipaddress
import socket


class BlockedDestination(Exception):
    """A requested destination is not a permitted public host."""


def _is_public(ip: ipaddress._BaseAddress) -> bool:
    """A globally-routable unicast address, and nothing else.

    `is_global` already excludes private, loopback, link-local and the
    unspecified address. The extra checks cover cases it does not: multicast,
    reserved ranges, and IPv4-mapped IPv6 (::ffff:127.0.0.1 would otherwise
    smuggle a loopback v4 address past a v6 check).
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_public(ip.ipv4_mapped)
    return (
        ip.is_global
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_loopback
        and not ip.is_link_local
    )


def resolve_public(host: str, port: int) -> list[tuple[int, str, int]]:
    """Resolve `host` and return only its public unicast endpoints.

    Returns a list of (family, address, port) suitable for opening a socket.
    Raises BlockedDestination if the name does not resolve, or if NONE of its
    addresses are public — which also stops a name whose addresses are mixed
    public and private from being used to reach the private ones.
    """
    # A literal that is already an address: check it directly. getaddrinfo
    # would accept it too, but doing this first keeps the failure specific.
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public(literal):
            raise BlockedDestination(f"{host} is not a public address")
        family = socket.AF_INET6 if literal.version == 6 else socket.AF_INET
        return [(family, str(literal), port)]

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedDestination(f"cannot resolve {host}: {exc}") from exc

    endpoints = []
    blocked = 0
    for family, _, _, _, sockaddr in infos:
        addr = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            blocked += 1
            continue
        if _is_public(ip):
            endpoints.append((family, addr, port))
        else:
            blocked += 1

    if not endpoints:
        raise BlockedDestination(
            f"{host} resolves only to non-public addresses"
        )
    return endpoints
