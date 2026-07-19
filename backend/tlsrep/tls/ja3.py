"""JA3 — the original TLS client fingerprint (Salesforce, BSD-3-Clause).

    version,ciphers,extensions,curves,point_formats

all decimal, dash-separated within a field, then MD5 of that string.
"""

from __future__ import annotations

import hashlib

from .clienthello import ClientHello


def _join(values: list[int]) -> str:
    return "-".join(str(v) for v in values)


def ja3_string(hello: ClientHello) -> str:
    return ",".join(
        [
            str(hello.legacy_version),
            _join(hello.ciphers),
            _join(hello.extensions),
            _join(hello.curves),
            _join(hello.point_formats),
        ]
    )


def ja3_hash(ja3: str) -> str:
    return hashlib.md5(ja3.encode()).hexdigest()


def compute_ja3(hello: ClientHello) -> tuple[str, str]:
    """Returns (hash, raw string)."""
    raw = ja3_string(hello)
    return ja3_hash(raw), raw
