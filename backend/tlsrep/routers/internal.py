"""The internal write API.

Collectors (see ../../proxy/) POST batches of base64 ClientHellos here. All
fingerprint computation happens on this side, so a collector stays a dumb pipe
that never needs updating when the fingerprint definitions change.

Request body:

    {"data": ["<base64 ClientHello>", ...]}

This endpoint is internet-facing by necessity: collectors run on residential
exit nodes whose addresses cannot be allowlisted. It is guarded by a shared
key, checked in middleware before the body is parsed, and rate-limited by
nginx well below what a collector needs.
"""

from __future__ import annotations

import base64
import binascii
import logging
import secrets
from collections import defaultdict

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..config import settings
from ..tls import fingerprint

log = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/v1", tags=["internal"])

# A ClientHello above this is not a ClientHello. The record layer caps a single
# record at 16 KiB and reassembly of a few records covers every real client.
_MAX_HELLO_BYTES = 65536
_MAX_BATCH = 5000


class IngestBatch(BaseModel):
    data: list[str] = Field(..., max_length=_MAX_BATCH)


def _authorise(key: str | None) -> None:
    """Second line. The middleware in main.py rejects these before the body is
    parsed; this keeps the route correct if it is ever mounted without it."""
    if not settings.ingest_key:
        raise HTTPException(503, "ingest disabled: no key configured")
    if not secrets.compare_digest(key or "", settings.ingest_key):
        raise HTTPException(401, "bad ingest key")


def _aggregate(hellos: list[bytes]) -> tuple[list[dict], int]:
    """Collapse a batch into one record per distinct JA4.

    Grouping is by JA4 alone. Grouping by (ja3, ja4) — which is what the schema
    used to key on — puts a permuting client in a group of one per connection,
    so a batch of 200 Chrome hellos became 200 records and 200 rows.

    Each record carries the JA3s it saw underneath it. That multiplicity is the
    signal the site reports as `stability`.
    """
    grouped: dict[str, dict] = {}
    skipped = 0

    for raw in hellos:
        parsed = fingerprint(raw)
        if parsed is None:
            skipped += 1
            continue

        # No SNI means no domain to attribute; the fingerprint still counts.
        sni = parsed.pop("sni", None)
        ja3 = parsed.pop("ja3")
        ja3_raw = parsed.pop("ja3_raw")
        extensions = parsed["extensions"]
        key = parsed["ja4"]

        record = grouped.get(key)
        if record is None:
            record = grouped[key] = {
                **parsed,
                "count": 0,
                "snis": defaultdict(int),
                "ja3s": {},
            }

        record["count"] += 1
        if sni:
            record["snis"][sni.lower()] += 1

        # (raw string, wire extension order, how many times seen this batch)
        seen = record["ja3s"].get(ja3)
        record["ja3s"][ja3] = (
            ja3_raw,
            extensions,
            (seen[2] if seen else 0) + 1,
        )

    return list(grouped.values()), skipped


@router.post("/ingest", summary="Submit a batch of ClientHellos")
async def ingest(
    batch: IngestBatch,
    x_ingest_key: str | None = Header(None, alias="X-Ingest-Key"),
) -> dict:
    _authorise(x_ingest_key)

    decoded: list[bytes] = []
    malformed = 0
    for item in batch.data:
        try:
            raw = base64.b64decode(item, validate=True)
        except (binascii.Error, ValueError):
            malformed += 1
            continue
        if 0 < len(raw) <= _MAX_HELLO_BYTES:
            decoded.append(raw)
        else:
            malformed += 1

    records, skipped = _aggregate(decoded)
    written = await db.record_batch(records) if records else 0

    if malformed or skipped:
        log.info(
            "ingest: %d accepted, %d malformed, %d unparseable",
            written,
            malformed,
            skipped,
        )

    return {
        "accepted": written,
        "fingerprints": len(records),
        "malformed": malformed,
        "unparseable": skipped,
    }
