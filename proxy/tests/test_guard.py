"""The destination guard is the proxy's only defence against being used as an
SSRF lever against its own host and network. These are the cases that matter."""

import pytest

from tlsrep_proxy.guard import BlockedDestination, resolve_public


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",          # loopback
        "localhost",          # loopback by name
        "169.254.169.254",    # cloud metadata
        "10.0.0.1",           # RFC1918
        "192.168.1.1",        # RFC1918
        "172.16.0.1",         # RFC1918
        "::1",                # loopback v6
        "::ffff:127.0.0.1",   # v4-mapped loopback — must not smuggle past a v6 check
        "0.0.0.0",            # unspecified
        "224.0.0.1",          # multicast
        "fe80::1",            # link-local v6
    ],
)
def test_non_public_destinations_are_blocked(host):
    with pytest.raises(BlockedDestination):
        resolve_public(host, 443)


@pytest.mark.parametrize(
    "host",
    ["1.1.1.1", "8.8.8.8", "2606:4700:4700::1111"],
)
def test_public_literals_are_allowed(host):
    endpoints = resolve_public(host, 443)
    assert endpoints
    assert all(port == 443 for _, _, port in endpoints)


def test_a_public_name_resolves():
    # example.com is stable and public; this asserts the allow path works end
    # to end, not just the literal short-circuit.
    assert resolve_public("example.com", 443)


def test_unresolvable_name_is_blocked_not_crashed():
    with pytest.raises(BlockedDestination):
        resolve_public("no-such-host.invalid", 443)
