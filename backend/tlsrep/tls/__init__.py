"""TLS ClientHello parsing and fingerprinting.

Both fingerprints implemented here are BSD-3-Clause: JA3 (Salesforce) and JA4
(FoxIO). The wider JA4+ suite is under the FoxIO License 1.1 and is
deliberately not implemented — see ja4.py.
"""

from .clienthello import ClientHello, is_grease, parse_client_hello
from .ja3 import compute_ja3
from .ja4 import compute_ja4

__all__ = [
    "ClientHello",
    "compute_ja3",
    "compute_ja4",
    "is_grease",
    "parse_client_hello",
    "fingerprint",
]


def fingerprint(data: bytes) -> dict | None:
    """Raw ClientHello bytes -> everything we store about it.

    Returns None when `data` is not a parseable ClientHello, or when it arrived
    truncated. A short hello still parses, but into a smaller extension count
    and a clipped extension set — a confident, distinct and WRONG JA4. Since
    JA4 is the identity key, storing one would mint a client that never existed.
    """
    hello = parse_client_hello(data)
    if hello is None or hello.truncated:
        return None

    ja3, ja3_raw = compute_ja3(hello)
    ja4, ja4_r = compute_ja4(hello)

    return {
        "ja3": ja3,
        "ja3_raw": ja3_raw,
        "ja4": ja4,
        "ja4_r": ja4_r,
        "sni": hello.sni,
        "tls_version": hello.negotiated_version,
        "alpn": hello.alpn,
        "ciphers": hello.ciphers,
        # Wire order, as received. The caller sorts it before storing it on the
        # fingerprint and keeps this order on the JA3 variant: the difference
        # between the two is what identifies a permuting client.
        "extensions": hello.extensions,
        "curves": hello.curves,
        "sig_algs": hello.sig_algs,
        "point_formats": hello.point_formats,
        "has_psk": hello.has_psk,
    }
