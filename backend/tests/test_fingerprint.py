"""Fingerprint tests.

The ClientHello below is a real capture, not synthetic: curl connecting to a
local socket. Its JA3 hash was cross-checked against an independent parser
before being frozen here, so a regression in the parser shows up as a changed
hash rather than as a silently different fingerprint.
"""

from __future__ import annotations

import base64

import pytest

from tlsrep.db import spread
from tlsrep.tls import fingerprint, parse_client_hello
from tlsrep.tls.clienthello import is_grease
from tlsrep.tls.ja4 import _alpn_code, compute_ja4

# curl → 127.0.0.1 (no SNI, offers h2)
CURL = base64.b64decode(
    "FgMBASgBAAEkAwNo7DAvZneT0CHWiZM3M1jbcP4lrE+sOFwxEa6GsvqGbiC8Hd7Xs6GAmqCyUPQEmQGvcj8NmGiq"
    "4UBvn30RxVBc7ABiEwMTAhMBzKnMqMyqwDDALMAowCTAFMAKAJ8AawA5/4UAxACIAIEAnQA9ADUAwACEwC/AK8An"
    "wCPAE8AJAJ4AZwAzAL4ARQCcADwALwC6AEHAEcAHAAUABMASwAgAFgAKAP8BAAB5ACsACQgDBAMDAwIDAQAzACYA"
    "JAAdACDXLqXceg0jfgYKU+Pg1qx/fvIfFo5tk/2zMVwrN1yVcQALAAIBAAAKAAoACAAdABcAGAAZAA0AGAAWCAYG"
    "AQYDCAUFAQUDCAQEAQQDAgECAwAQAA4ADAJoMghodHRwLzEuMQ=="
)


def test_curl_ja3_is_stable():
    result = fingerprint(CURL)
    assert result["ja3"] == "4f2655722e37c542ebeaf1eed48cbbbb"


def test_curl_ja4_shape():
    result = fingerprint(CURL)
    ja4a, ja4b, ja4c = result["ja4"].split("_")

    # t=TCP, 13=TLS 1.3, i=no SNI (connected to a bare IP), 49 ciphers,
    # 06 extensions, h2 = first+last char of the first ALPN value.
    assert ja4a == "t13i4906h2"
    assert len(ja4b) == 12 and len(ja4c) == 12


def test_alpn_is_read_from_the_first_protocol_only():
    result = fingerprint(CURL)
    assert result["alpn"] == ["h2", "http/1.1"]


def test_no_sni_when_connecting_to_an_ip():
    assert fingerprint(CURL)["sni"] is None


def test_grease_detection():
    # RFC 8701 GREASE values: both bytes equal, low nibble 0xa.
    assert is_grease(0x0A0A)
    assert is_grease(0xFAFA)
    assert not is_grease(0x1301)
    assert not is_grease(0x0A0B)


def test_grease_is_excluded_from_the_fingerprint():
    hello = parse_client_hello(CURL)
    assert not any(is_grease(c) for c in hello.ciphers)
    assert not any(is_grease(e) for e in hello.extensions)


def test_ja4_counts_saturate_at_99():
    """A hello with 200 ciphers must not produce a 3-digit ja4_a field."""
    hello = parse_client_hello(CURL)
    hello.ciphers = list(range(1, 201))
    ja4, _ = compute_ja4(hello)
    assert ja4.split("_")[0][4:6] == "99"


def test_ja4_extension_count_includes_sni_and_alpn():
    """The count in ja4_a includes SNI/ALPN; only the ja4_c hash drops them."""
    hello = parse_client_hello(CURL)
    hello.has_sni_ext = True
    hello.extensions = [0x0000, 0x0010, 0x002B]
    ja4, _ = compute_ja4(hello)
    assert ja4.split("_")[0][6:8] == "03"


@pytest.mark.parametrize(
    ("alpn", "expected"),
    [
        ([], "00"),
        (["h2"], "h2"),
        (["http/1.1"], "h1"),
        (["h3"], "h3"),
        # Non-alphanumeric edges fall back to hex nibbles.
        (["\x00abc\xff"], "0f"),
    ],
)
def test_alpn_code(alpn, expected):
    assert _alpn_code(alpn) == expected


def test_rejects_non_clienthello():
    assert fingerprint(b"GET / HTTP/1.1\r\n\r\n") is None
    assert fingerprint(b"") is None
    assert fingerprint(b"\x16\x03\x01") is None


def test_truncation_never_raises():
    """Every prefix of a real hello must fail closed, not explode."""
    for cut in range(0, len(CURL), 7):
        fingerprint(CURL[:cut])


def test_fuzzed_bytes_never_raise():
    import random

    rng = random.Random(1234)
    for _ in range(500):
        data = bytearray(CURL)
        for _ in range(rng.randint(1, 20)):
            data[rng.randrange(len(data))] = rng.randrange(256)
        fingerprint(bytes(data))


def test_clienthello_split_across_tls_records():
    """A hello spanning two records must reassemble to the same fingerprint."""
    body = CURL[5:]
    split = len(body) // 2

    def record(payload: bytes) -> bytes:
        return b"\x16\x03\x01" + len(payload).to_bytes(2, "big") + payload

    fragmented = record(body[:split]) + record(body[split:])
    assert fingerprint(fragmented)["ja3"] == fingerprint(CURL)["ja3"]


class TestSpread:
    def test_single_domain_scores_zero(self):
        assert spread([100]) == 0.0

    def test_empty_scores_zero(self):
        assert spread([]) == 0.0

    def test_even_spread_scores_one(self):
        assert spread([10, 10, 10, 10]) == pytest.approx(1.0)

    def test_concentrated_scores_low(self):
        assert spread([1000, 1, 1, 1]) < 0.2

    def test_is_comparable_across_scale(self):
        """Normalisation is the point: 5 even domains and 500 even domains
        both mean 'evenly spread', and must not be ranked differently."""
        assert spread([10] * 5) == pytest.approx(spread([10] * 500))

    def test_browser_ranks_below_scraper(self):
        browser = spread([5000, 3000, 900, 40])
        scraper = spread([12] * 400)
        assert browser < scraper


class TestSniSpread:
    """The mirror metric: entropy over the fingerprints reaching one domain.

    Same function as a fingerprint's spread, applied to the other axis, so the
    reference implementation covers both.
    """

    def test_one_client_stack_scores_zero(self):
        assert spread([5000]) == 0.0

    def test_ordinary_traffic_sits_in_the_middle(self):
        # A handful of real client stacks, very unevenly split.
        assert 0.3 < spread([9000, 4000, 1500, 300, 80, 20]) < 0.8

    def test_fingerprint_rotation_saturates(self):
        """60 distinct fingerprints across 60 connections — the credential
        stuffing shape, where the variety itself is the signature."""
        assert spread([1] * 60) == pytest.approx(1.0)

    def test_rotation_outranks_ordinary_traffic(self):
        ordinary = spread([9000, 4000, 1500, 300, 80, 20])
        rotating = spread([1] * 60)
        assert rotating > ordinary


class TestTransportPrefix:
    """JA4's first character is the transport, and it is now the identity key.

    Hardcoding 't' would mean a QUIC hello from a client collides with its own
    TCP hello — an identity collision with no way out once JA4 is the primary
    key.
    """

    def test_defaults_to_tcp(self):
        assert fingerprint(CURL)["ja4"].startswith("t")

    def test_follows_the_hello(self):
        hello = parse_client_hello(CURL)
        hello.transport = "q"
        ja4, _ = compute_ja4(hello)
        assert ja4.startswith("q")

    def test_transports_do_not_collide(self):
        tcp = parse_client_hello(CURL)
        quic = parse_client_hello(CURL)
        quic.transport = "q"
        assert compute_ja4(tcp)[0] != compute_ja4(quic)[0]


class TestTruncationIsRefused:
    """A short hello parses into a smaller extension count and a clipped
    extension set — a confident, distinct, WRONG JA4. Under JA4-as-identity
    that mints a client that never existed, so ingest must refuse it."""

    def test_full_hello_is_accepted(self):
        assert fingerprint(CURL) is not None
        assert parse_client_hello(CURL).truncated is False

    def test_short_hello_is_flagged_and_refused(self):
        cut = CURL[: len(CURL) - 40]
        hello = parse_client_hello(cut)
        assert hello is not None and hello.truncated is True
        assert fingerprint(cut) is None

    def test_truncated_would_otherwise_have_produced_a_different_ja4(self):
        """The point of refusing: it does not merely lose data, it invents."""
        cut = CURL[: len(CURL) - 40]
        whole = parse_client_hello(CURL)
        short = parse_client_hello(cut)
        assert compute_ja4(short)[0] != compute_ja4(whole)[0]


class TestPermutationCollapsesToOneIdentity:
    """The bug this schema exists to fix: Chrome reshuffles extension order per
    connection, so JA3 changes every time while JA4 stays put."""

    @staticmethod
    def _permute(data: bytes, seed: int) -> bytes:
        import random
        import struct

        rng = random.Random(seed)
        body = bytearray(data)
        pos = 5 + 4 + 34
        pos += 1 + body[pos]
        ciphers_len = struct.unpack_from("!H", body, pos)[0]
        pos += 2 + ciphers_len
        pos += 1 + body[pos]
        ext_total = struct.unpack_from("!H", body, pos)[0]
        pos += 2
        block, end = body[pos : pos + ext_total], pos + ext_total

        exts, cursor = [], 0
        while cursor + 4 <= len(block):
            length = struct.unpack_from("!H", block, cursor + 2)[0]
            exts.append(bytes(block[cursor : cursor + 4 + length]))
            cursor += 4 + length
        rng.shuffle(exts)
        return bytes(body[:pos]) + b"".join(exts) + bytes(body[end:])

    def test_permuted_hellos_share_one_ja4(self):
        ja4s = {fingerprint(self._permute(CURL, i))["ja4"] for i in range(40)}
        assert len(ja4s) == 1

    def test_permuted_hellos_produce_many_ja3(self):
        ja3s = {fingerprint(self._permute(CURL, i))["ja3"] for i in range(40)}
        assert len(ja3s) > 20

    def test_permutation_changes_only_extension_order(self):
        base = parse_client_hello(CURL)
        other = parse_client_hello(self._permute(CURL, 7))
        assert base.ciphers == other.ciphers
        assert base.curves == other.curves
        assert base.point_formats == other.point_formats
        assert sorted(base.extensions) == sorted(other.extensions)
        assert base.extensions != other.extensions


class TestResumptionMarkers:
    """A resumed TLS 1.3 handshake carries pre_shared_key, which changes both
    the ja4_a extension count and the ja4_c hash — so the same client stack
    yields a different JA4 cold than resumed. Recorded so that is explainable."""

    def test_absent_on_a_cold_hello(self):
        hello = parse_client_hello(CURL)
        assert hello.has_psk is False
        assert hello.has_early_data is False

    def test_psk_changes_the_ja4(self):
        cold = parse_client_hello(CURL)
        resumed = parse_client_hello(CURL)
        resumed.extensions = sorted([*resumed.extensions, 0x0029])
        assert compute_ja4(cold)[0] != compute_ja4(resumed)[0]


class TestJa4SpecConformance:
    """Every worked ALPN example from FoxIO's technical_details/JA4.md.

    These were added after checking this implementation against FoxIO's own
    reference vectors and finding a real bug: `str.isalnum()` is Unicode-aware
    and answered True for bytes like 0xEF, so a non-ASCII ALPN took the
    alphanumeric branch and emitted raw bytes instead of the hex fallback.

    One divergence from the reference implementation is deliberate and is
    covered by `test_non_ascii_alpn_follows_the_spec_not_the_reference_tool`.
    """

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (b"\xab", "ab"),
            (b"\x20", "20"),
            (b"\xab\xcd", "ad"),
            (b"\x20\x61", "21"),
            (b"\x30\xab", "3b"),
            (b"\x61\x20", "60"),
            (b"\x30\x31\xab\xcd", "3d"),
            # And the ordinary alphanumeric path.
            (b"h2", "h2"),
            (b"http/1.1", "h1"),
            (b"h3", "h3"),
            # A single character is both the first and the last.
            (b"x", "xx"),
        ],
    )
    def test_alpn_code_matches_the_spec(self, raw, expected):
        assert _alpn_code([raw.decode("latin-1")]) == expected

    def test_no_alpn_is_double_zero(self):
        assert _alpn_code([]) == "00"
        assert _alpn_code([""]) == "00"

    def test_non_ascii_alpn_follows_the_spec_not_the_reference_tool(self):
        """FoxIO's own vector for tls-non-ascii-alpn.pcapng expects "99" here,
        and we deliberately produce "bd" instead.

        The reference implementation reads ALPN as a string out of tshark's
        `tls.handshake.extensions_alpn_str`, by which point every non-UTF-8
        byte has already become U+FFFD; it then maps that replacement character
        to '9' (see its own `test_first_last_non_ascii`). The original bytes are
        gone before it ever sees them, so it cannot apply the spec's hex rule.

        We parse the raw ClientHello off the wire, so we can — and the spec is
        explicit that 0xAB 0xCD prints as "ad". The captured bytes here are
        0xBA 0xAD, so the spec-conformant answer is "bd".
        """
        assert _alpn_code([b"\xba\xad".decode("latin-1")]) == "bd"

    def test_alpn_bytes_survive_parsing(self):
        """The bug underneath the bug: decoding ALPN with errors="replace"
        destroyed the bytes the hex fallback is computed from."""
        from tlsrep.tls.clienthello import _parse_alpn

        payload = b"\x00\x03\x02\xba\xad"  # list len 3, one 2-byte protocol
        assert _parse_alpn(payload)[0].encode("latin-1") == b"\xba\xad"
