"""JA4 — TLS client fingerprint (FoxIO, BSD-3-Clause).

Format: ``ja4_a _ ja4_b _ ja4_c``

    a  t<ver><d|i><cipher count><ext count><alpn first+last>
    b  sha256(sorted ciphers, comma-joined lowercase hex)[:12]
    c  sha256(sorted extensions sans SNI/ALPN + "_" + sig algs)[:12]

Only JA4 itself is implemented here. The rest of the JA4+ suite (JA4S/H/X/T/…)
is under the FoxIO License 1.1, which restricts commercial use; JA4 and JA3 are
both BSD-3-Clause and carry no such condition.

Two details the spec is easy to get wrong, both deliberate below:
  * the extension *count* in ja4_a includes SNI and ALPN, while the extension
    *hash* in ja4_c excludes them;
  * signature algorithms are NOT sorted — their order is part of the signal.
"""

from __future__ import annotations

import hashlib

from .clienthello import EXT_ALPN, EXT_SNI, ClientHello

_EMPTY = "000000000000"

_VERSION_NAMES = {
    0x0304: "13",
    0x0303: "12",
    0x0302: "11",
    0x0301: "10",
    0x0300: "s3",
    0x0200: "s2",
}


def _version_code(version: int) -> str:
    return _VERSION_NAMES.get(version, "00")


def _join_hex(values: list[int]) -> str:
    return ",".join(f"{v:04x}" for v in values)


def _sha12(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _is_ascii_alnum(byte: int) -> bool:
    return (
        0x30 <= byte <= 0x39  # 0-9
        or 0x41 <= byte <= 0x5A  # A-Z
        or 0x61 <= byte <= 0x7A  # a-z
    )


def _alpn_code(alpn: list[str]) -> str:
    """First and last character of the first ALPN value.

    When either is non-alphanumeric the spec substitutes hex nibbles: the high
    nibble of the first byte and the low nibble of the last.
    """
    if not alpn or not alpn[0]:
        return "00"
    value = alpn[0].encode("latin-1", errors="replace")
    first, last = value[0], value[-1]
    # ASCII alphanumeric, checked on the byte. str.isalnum() is Unicode-aware
    # and answers True for bytes like 0xEF ('ï'), which sent non-ASCII ALPNs
    # down the wrong branch — verified against FoxIO's tls-non-ascii-alpn
    # vector, which expects the hex fallback here.
    if _is_ascii_alnum(first) and _is_ascii_alnum(last):
        return f"{chr(first)}{chr(last)}"
    # The spec's fallback: first and last character of the first ALPN's hex
    # representation — i.e. the high nibble of the first byte and the low
    # nibble of the last.
    return f"{first >> 4:x}{last & 0x0F:x}"


def compute_ja4(hello: ClientHello) -> tuple[str, str]:
    """Returns (ja4, ja4_r) — the hashed form and the raw/expanded form."""
    cipher_count = min(len(hello.ciphers), 99)
    ext_count = min(len(hello.extensions), 99)

    # The transport prefix comes from the hello, not from a literal: a QUIC
    # ClientHello from the same client must not produce the same JA4 as its
    # TCP one, and JA4 is the identity key.
    part_a = (
        f"{hello.transport}{_version_code(hello.negotiated_version)}"
        f"{'d' if hello.has_sni_ext else 'i'}"
        f"{cipher_count:02d}{ext_count:02d}{_alpn_code(hello.alpn)}"
    )

    ciphers_hex = _join_hex(sorted(hello.ciphers))
    part_b = _sha12(ciphers_hex) if hello.ciphers else _EMPTY

    hashed_exts = sorted(
        e for e in hello.extensions if e not in (EXT_SNI, EXT_ALPN)
    )
    ext_hex = _join_hex(hashed_exts)
    sig_hex = _join_hex(hello.sig_algs)  # order-sensitive: do not sort
    part_c_input = f"{ext_hex}_{sig_hex}" if sig_hex else ext_hex
    part_c = (
        _EMPTY if not hashed_exts and not hello.sig_algs else _sha12(part_c_input)
    )

    return (
        f"{part_a}_{part_b}_{part_c}",
        f"{part_a}_{ciphers_hex}_{part_c_input}",
    )
