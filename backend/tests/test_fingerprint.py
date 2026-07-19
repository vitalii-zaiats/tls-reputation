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
