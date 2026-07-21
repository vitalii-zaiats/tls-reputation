"""Minimal STUN (RFC 5389) — just enough to answer a Binding Request.

We are the STUN server the browser's WebRTC talks to. A genuine client sends a
Binding Request over UDP; we reply with its reflexive address so it gets an
srflx candidate, and — the point of the whole exercise — we *record that the
packet actually arrived*. A browser that forges an srflx candidate without
sending the packet never reaches this code, and the mismatch is the tell.
"""

from __future__ import annotations

import socket
import struct

MAGIC = 0x2112A442
_MAGIC_BYTES = b"\x21\x12\xa4\x42"

_BINDING_REQUEST = 0x0001
_BINDING_SUCCESS = 0x0101
_XOR_MAPPED_ADDRESS = 0x0020


def is_binding_request(data: bytes) -> bool:
    """A well-formed STUN Binding Request: type, magic cookie, and a length that
    matches. Anything else on the port is not our client and is ignored."""
    if len(data) < 20 or data[4:8] != _MAGIC_BYTES:
        return False
    msg_type, msg_len = struct.unpack("!HH", data[0:4])
    return msg_type == _BINDING_REQUEST and len(data) >= 20 + msg_len


def transaction_id(data: bytes) -> bytes:
    return data[8:20]


def build_binding_response(txid: bytes, ip: str, port: int) -> bytes:
    """A Binding Success carrying the sender's XOR-MAPPED-ADDRESS (IPv4/IPv6)."""
    try:
        packed = socket.inet_pton(socket.AF_INET, ip)
        family, xaddr = 0x01, bytes(b ^ _MAGIC_BYTES[i] for i, b in enumerate(packed))
    except OSError:
        packed = socket.inet_pton(socket.AF_INET6, ip)
        key = _MAGIC_BYTES + txid
        family, xaddr = 0x02, bytes(b ^ key[i] for i, b in enumerate(packed))
    xport = port ^ (MAGIC >> 16)
    value = struct.pack("!BBH", 0, family, xport) + xaddr
    attr = struct.pack("!HH", _XOR_MAPPED_ADDRESS, len(value)) + value
    header = struct.pack("!HHI", _BINDING_SUCCESS, len(attr), MAGIC) + txid
    return header + attr
