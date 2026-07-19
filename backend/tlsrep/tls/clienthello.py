"""TLS ClientHello parser.

Parses a raw ClientHello (TLS record layer included) into the fields JA3 and
JA4 are built from. GREASE values (RFC 8701) are stripped everywhere they
would otherwise pollute a fingerprint.

The parser is deliberately total: it never raises on malformed input, it
returns None. Traffic reaching this code is attacker-controlled by
construction, so a parse failure has to be an ordinary outcome.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

# Extension IDs we decode rather than merely record.
EXT_SNI = 0x0000
EXT_SUPPORTED_GROUPS = 0x000A
EXT_EC_POINT_FORMATS = 0x000B
EXT_SIG_ALGS = 0x000D
EXT_ALPN = 0x0010
EXT_SUPPORTED_VERSIONS = 0x002B
# Resumption markers. Their presence changes the extension set, and so the
# JA4, for what is otherwise the same client stack.
EXT_PRE_SHARED_KEY = 0x0029
EXT_EARLY_DATA = 0x002A

_HANDSHAKE_RECORD = 0x16
_CLIENT_HELLO = 0x01


def is_grease(value: int) -> bool:
    """RFC 8701 GREASE: both bytes equal, low nibble 0xa."""
    hi, lo = value >> 8, value & 0xFF
    return hi == lo and (lo & 0x0F) == 0x0A


@dataclass
class ClientHello:
    legacy_version: int
    # JA4's first character is the transport: t=TCP, q=QUIC, d=DTLS. Carried as
    # a field rather than hardcoded at hash time, because JA4 is the identity
    # key — the day a QUIC collector is added, a QUIC hello must not collide
    # with the TCP hello of the same client.
    transport: str = "t"
    # Set when the hello did not arrive whole. A short hello yields a smaller
    # extension count and a truncated extension set, which produces a
    # confident, distinct, WRONG JA4. Callers must refuse to store those.
    truncated: bool = False
    ciphers: list[int] = field(default_factory=list)
    extensions: list[int] = field(default_factory=list)
    curves: list[int] = field(default_factory=list)
    point_formats: list[int] = field(default_factory=list)
    sig_algs: list[int] = field(default_factory=list)
    supported_versions: list[int] = field(default_factory=list)
    alpn: list[str] = field(default_factory=list)
    sni: str | None = None
    has_sni_ext: bool = False
    # A resumed TLS 1.3 handshake carries pre_shared_key (and 0-RTT adds
    # early_data). Both change the extension count in ja4_a and the sorted
    # set in ja4_c, so the same client stack yields a different JA4 cold
    # than resumed. Recorded so that difference is explainable rather than
    # appearing as two unrelated clients.
    has_psk: bool = False
    has_early_data: bool = False

    @property
    def negotiated_version(self) -> int:
        """Highest version offered — supported_versions wins over the legacy field."""
        if self.supported_versions:
            return max(self.supported_versions)
        return self.legacy_version


class _Reader:
    """Bounds-checked sequential reader. Raises _Truncated past the end."""

    __slots__ = ("_buf", "_pos")

    def __init__(self, buf: bytes) -> None:
        self._buf = buf
        self._pos = 0

    @property
    def remaining(self) -> int:
        return len(self._buf) - self._pos

    def u8(self) -> int:
        if self.remaining < 1:
            raise _Truncated
        value = self._buf[self._pos]
        self._pos += 1
        return value

    def u16(self) -> int:
        if self.remaining < 2:
            raise _Truncated
        value = struct.unpack_from("!H", self._buf, self._pos)[0]
        self._pos += 2
        return value

    def u24(self) -> int:
        if self.remaining < 3:
            raise _Truncated
        value = int.from_bytes(self._buf[self._pos : self._pos + 3], "big")
        self._pos += 3
        return value

    def take(self, n: int) -> bytes:
        if n < 0 or self.remaining < n:
            raise _Truncated
        value = self._buf[self._pos : self._pos + n]
        self._pos += n
        return value

    def skip(self, n: int) -> None:
        self.take(n)


class _Truncated(Exception):
    """Buffer ended mid-structure."""


def _u16_list(payload: bytes) -> list[int]:
    """A u16 length prefix followed by that many bytes of u16 items."""
    reader = _Reader(payload)
    total = reader.u16()
    body = reader.take(min(total, reader.remaining))
    return [
        struct.unpack_from("!H", body, i)[0] for i in range(0, len(body) - 1, 2)
    ]


def _parse_sni(payload: bytes) -> str | None:
    """First host_name (name_type 0) entry of the server_name list."""
    reader = _Reader(payload)
    list_len = reader.u16()
    end = min(list_len, reader.remaining)
    consumed = 0
    while consumed + 3 <= end:
        name_type = reader.u8()
        name_len = reader.u16()
        name = reader.take(min(name_len, reader.remaining))
        consumed += 3 + len(name)
        if name_type == 0:
            return name.decode("ascii", errors="replace")
    return None


def _parse_alpn(payload: bytes) -> list[str]:
    reader = _Reader(payload)
    total = reader.u16()
    end = min(total, reader.remaining)
    consumed = 0
    protocols: list[str] = []
    while consumed + 1 <= end:
        proto_len = reader.u8()
        proto = reader.take(min(proto_len, reader.remaining))
        consumed += 1 + len(proto)
        if proto:
            # latin-1, not ascii+replace: it maps bytes 1:1 onto U+0000..U+00FF,
            # so the original bytes survive and can be recovered exactly.
            # Decoding with errors="replace" turned every non-ASCII ALPN into
            # U+FFFD before JA4 ever saw it, destroying the very bytes the
            # spec's hex fallback is computed from.
            protocols.append(proto.decode("latin-1"))
    return protocols


def _parse_ec_point_formats(payload: bytes) -> list[int]:
    reader = _Reader(payload)
    count = reader.u8()
    return list(reader.take(min(count, reader.remaining)))


def parse_client_hello(data: bytes) -> ClientHello | None:
    """Parse a TLS ClientHello. Returns None if `data` is not one.

    `data` starts at the TLS record header. A ClientHello split across several
    TLS records is reassembled — browsers do this once the hello outgrows a
    single record, and a parser that ignores it silently loses those clients.
    """
    result = _reassemble_handshake(data)
    if result is None:
        return None
    handshake, truncated = result

    try:
        hello = _parse_handshake_body(handshake)
    except _Truncated:
        return None

    hello.truncated = truncated
    return hello


def _reassemble_handshake(data: bytes) -> tuple[bytes, bool] | None:
    """Concatenate the handshake payloads of consecutive TLS records.

    Returns (handshake message body past the 4-byte header, truncated flag),
    or None if this isn't a ClientHello.
    """
    reader = _Reader(data)
    payload = bytearray()

    try:
        while reader.remaining >= 5:
            content_type = reader.u8()
            if content_type != _HANDSHAKE_RECORD:
                break
            reader.skip(2)  # record version — not used by JA3/JA4
            record_len = reader.u16()
            payload += reader.take(min(record_len, reader.remaining))
            if len(payload) >= 4:
                declared = int.from_bytes(payload[1:4], "big")
                if len(payload) - 4 >= declared:
                    break
    except _Truncated:
        pass

    if len(payload) < 4 or payload[0] != _CLIENT_HELLO:
        return None

    declared = int.from_bytes(payload[1:4], "big")
    body = bytes(payload[4:])
    # A short body still parses into something, but what it parses into is a
    # LIE: fewer extensions than the client actually sent means a different
    # ja4_a count and a different ja4_c hash — a confident, distinct, wrong
    # identity. Report the shortfall so the caller can refuse to store it.
    if len(body) >= declared:
        return body[:declared], False
    return body, True


def _parse_handshake_body(body: bytes) -> ClientHello:
    reader = _Reader(body)

    legacy_version = reader.u16()
    reader.skip(32)  # random

    session_id_len = reader.u8()
    reader.skip(session_id_len)

    ciphers_len = reader.u16()
    cipher_bytes = reader.take(ciphers_len)
    ciphers = [
        struct.unpack_from("!H", cipher_bytes, i)[0]
        for i in range(0, len(cipher_bytes) - 1, 2)
    ]

    compression_len = reader.u8()
    reader.skip(compression_len)

    hello = ClientHello(
        legacy_version=legacy_version,
        ciphers=[c for c in ciphers if not is_grease(c)],
    )

    if reader.remaining < 2:
        return hello

    ext_total = reader.u16()
    ext_reader = _Reader(reader.take(min(ext_total, reader.remaining)))

    while ext_reader.remaining >= 4:
        ext_type = ext_reader.u16()
        ext_len = ext_reader.u16()
        ext_data = ext_reader.take(min(ext_len, ext_reader.remaining))

        if not is_grease(ext_type):
            hello.extensions.append(ext_type)

        try:
            _decode_extension(hello, ext_type, ext_data)
        except _Truncated:
            # A malformed extension body costs us that one field, not the hello.
            continue

    # Leftover bytes that are too few to form another extension header mean the
    # block was cut mid-entry: the extension list we just built is incomplete.
    if ext_reader.remaining:
        hello.truncated = True

    return hello


def _decode_extension(hello: ClientHello, ext_type: int, ext_data: bytes) -> None:
    if ext_type == EXT_SNI:
        hello.has_sni_ext = True
        hello.sni = _parse_sni(ext_data)
    elif ext_type == EXT_SUPPORTED_GROUPS:
        hello.curves = [c for c in _u16_list(ext_data) if not is_grease(c)]
    elif ext_type == EXT_EC_POINT_FORMATS:
        hello.point_formats = _parse_ec_point_formats(ext_data)
    elif ext_type == EXT_SIG_ALGS:
        hello.sig_algs = [s for s in _u16_list(ext_data) if not is_grease(s)]
    elif ext_type == EXT_ALPN:
        hello.alpn = _parse_alpn(ext_data)
    elif ext_type == EXT_PRE_SHARED_KEY:
        hello.has_psk = True
    elif ext_type == EXT_EARLY_DATA:
        hello.has_early_data = True
    elif ext_type == EXT_SUPPORTED_VERSIONS:
        reader = _Reader(ext_data)
        count = reader.u8()
        body = reader.take(min(count, reader.remaining))
        hello.supported_versions = [
            v
            for v in (
                struct.unpack_from("!H", body, i)[0]
                for i in range(0, len(body) - 1, 2)
            )
            if not is_grease(v)
        ]
