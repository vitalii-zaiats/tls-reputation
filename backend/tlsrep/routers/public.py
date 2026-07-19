"""The public read API. No authentication, no keys, no quota.

Everything here is an aggregate over observed TLS handshakes. Nothing in a
response identifies a person: there is no client IP in the database to leak.
"""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, HTTPException, Path, Query

from .. import db
from ..config import settings
from ..tls.names import CIPHERS, CURVES, EXTENSIONS, SIG_ALGOS, decorate

router = APIRouter(prefix="/api/v1", tags=["public"])

_JA3_RE = re.compile(r"^[0-9a-f]{32}$", re.I)
_JA4_RE = re.compile(r"^[a-z0-9]{10}_[0-9a-f]{12}_[0-9a-f]{12}$", re.I)
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$",
    re.I,
)

_TLS_VERSION_NAMES = {
    0x0304: "TLS 1.3",
    0x0303: "TLS 1.2",
    0x0302: "TLS 1.1",
    0x0301: "TLS 1.0",
    0x0300: "SSL 3.0",
    0x0200: "SSL 2.0",
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _summary(row) -> dict:
    """The compact shape used in list endpoints."""
    return {
        "ja3": row["ja3"],
        "ja4": row["ja4"],
        "tls_version": _TLS_VERSION_NAMES.get(row["tls_version"], "unknown"),
        "observations": row["observations"],
        "unique_snis": row["unique_snis"],
        "spread": round(row["spread"], 4),
        "first_seen": _iso(row["first_seen"]),
        "last_seen": _iso(row["last_seen"]),
    }


async def _detail(row) -> dict:
    snis = await db.top_snis(row["id"], settings.top_snis)
    total = row["observations"] or 1
    siblings = await db.siblings_for_ja3(row["ja3"], row["id"])

    return {
        **_summary(row),
        "ja3_raw": row["ja3_raw"],
        "ja4_r": row["ja4_r"],
        "alpn": list(row["alpn"]),
        "cipher_suites": decorate(row["ciphers"], CIPHERS),
        "extensions": decorate(row["extensions"], EXTENSIONS),
        "curves": decorate(row["curves"], CURVES),
        "sig_algs": decorate(row["sig_algs"], SIG_ALGOS),
        "point_formats": [f"0x{v:04x}" for v in row["point_formats"]],
        # A JA3 discards ALPN and the real version, so one JA3 can front
        # several JA4s. Surfacing them stops the detail page from quietly
        # showing one variant as if it were the whole story.
        "also_seen_as": [
            {"ja4": s["ja4"], "observations": s["observations"]} for s in siblings
        ],
        "top_snis": [
            {
                "sni": s["sni"],
                "count": s["count"],
                "share": round(s["count"] / total, 6),
                "first_seen": _iso(s["first_seen"]),
                "last_seen": _iso(s["last_seen"]),
            }
            for s in snis
        ],
    }


@router.get("/ja3/{value}", summary="Look up a fingerprint by JA3 (MD5)")
async def get_ja3(value: str = Path(..., description="32-char JA3 MD5")) -> dict:
    if not _JA3_RE.match(value):
        raise HTTPException(400, "not a JA3 hash (expected 32 hex characters)")
    row = await db.fingerprint_by_ja3(value.lower())
    if row is None:
        raise HTTPException(404, "fingerprint not observed")
    return await _detail(row)


@router.get("/ja4/{value}", summary="Look up a fingerprint by JA4")
async def get_ja4(value: str = Path(..., description="JA4 string, a_b_c")) -> dict:
    if not _JA4_RE.match(value):
        raise HTTPException(400, "not a JA4 string (expected a_b_c)")
    row = await db.fingerprint_by_ja4(value.lower())
    if row is None:
        raise HTTPException(404, "fingerprint not observed")
    return await _detail(row)


async def _sni_payload(value: str, limit: int, offset: int) -> dict | None:
    """Shared by the /sni route and /search. Returns None when unobserved.

    Kept separate from the route function on purpose: calling a FastAPI route
    directly hands you its `Query` defaults instead of real values.
    """
    result = await db.sni_detail(value, limit, offset)
    totals = result["totals"]
    if totals is None or totals["unique_fingerprints"] == 0:
        return None

    observations = int(totals["observations"])
    divisor = observations or 1

    return {
        "sni": value,
        "observations": observations,
        "unique_fingerprints": totals["unique_fingerprints"],
        # Entropy over the fingerprints reaching this domain, not over the
        # domains a fingerprint reaches. High spread means the callers are
        # many and evenly distributed — normal for a busy site, and the
        # signature of fingerprint rotation on an endpoint that should see
        # few distinct client stacks.
        "spread": round(totals["spread"], 4),
        "first_seen": _iso(totals["first_seen"]),
        "last_seen": _iso(totals["last_seen"]),
        "top_fingerprints": [
            {
                "ja3": r["ja3"],
                "ja4": r["ja4"],
                "count": r["count"],
                "share": round(r["count"] / divisor, 6),
                "first_seen": _iso(r["first_seen"]),
                "last_seen": _iso(r["last_seen"]),
            }
            for r in result["rows"]
        ],
    }


@router.get(
    "/fingerprint/{value}/snis",
    summary="Page through every domain a fingerprint reached",
)
async def get_fingerprint_snis(
    value: str,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
) -> dict:
    """The full SNI list, paginated.

    The fingerprint detail response embeds only the top slice. A promiscuous
    fingerprint — the interesting kind — can reach hundreds of domains, and
    that tail is the evidence for its score, so it has to be reachable.

    Accepts either a JA3 or a JA4 in the path.
    """
    if _JA3_RE.match(value):
        row = await db.fingerprint_by_ja3(value.lower())
    elif _JA4_RE.match(value):
        row = await db.fingerprint_by_ja4(value.lower())
    else:
        raise HTTPException(400, "not a JA3 or JA4 fingerprint")

    if row is None:
        raise HTTPException(404, "fingerprint not observed")

    rows = await db.top_snis(row["id"], min(limit, settings.max_limit), offset)
    divisor = row["observations"] or 1
    return {
        "ja3": row["ja3"],
        "ja4": row["ja4"],
        "total": row["unique_snis"],
        "items": [
            {
                "sni": r["sni"],
                "count": r["count"],
                "share": round(r["count"] / divisor, 6),
                "first_seen": _iso(r["first_seen"]),
                "last_seen": _iso(r["last_seen"]),
            }
            for r in rows
        ],
    }


@router.get("/sni/{value}", summary="Which fingerprints reached this domain")
async def get_sni(
    value: str,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
) -> dict:
    if not _HOSTNAME_RE.match(value):
        raise HTTPException(400, "not a hostname")

    payload = await _sni_payload(
        value.lower(), min(limit, settings.max_limit), offset
    )
    if payload is None:
        raise HTTPException(404, "domain not observed")
    return payload


@router.get("/fingerprints", summary="Browse fingerprints")
async def list_fingerprints(
    sort: str = Query("observations", pattern="|".join(db.SORT_KEYS)),
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
) -> dict:
    limit = min(limit, settings.max_limit)
    rows, total = await db.list_fingerprints(sort, limit, offset)
    return {"items": [_summary(r) for r in rows], "total": total}


@router.get("/snis", summary="Browse observed domains")
async def list_snis(
    sort: str = Query("observations", pattern="|".join(db.SNI_SORT_KEYS)),
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
) -> dict:
    """Domains, sortable by how varied the fingerprints reaching them are.

    `sort=spread` is the interesting one: it ranks domains by how evenly the
    traffic to them is split across distinct client stacks.
    """
    limit = min(limit, settings.max_limit)
    rows, total = await db.list_snis(sort, limit, offset)
    return {
        "items": [
            {
                "sni": r["sni"],
                "observations": int(r["observations"]),
                "unique_fingerprints": r["unique_fingerprints"],
                "spread": round(r["spread"], 4),
                "first_seen": _iso(r["first_seen"]),
                "last_seen": _iso(r["last_seen"]),
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/search", summary="Detect input type and resolve it")
async def search(q: str = Query(..., min_length=3)) -> dict:
    """One box for all three input kinds — the site's front door.

    Reports the detected kind even when nothing matched, so the UI can say
    "that's a valid JA4, we've just never seen it" rather than "not found".
    """
    value = q.strip().lower()

    if _JA3_RE.match(value):
        row = await db.fingerprint_by_ja3(value)
        return {"kind": "ja3", "match": await _detail(row) if row else None}
    if _JA4_RE.match(value):
        row = await db.fingerprint_by_ja4(value)
        return {"kind": "ja4", "match": await _detail(row) if row else None}
    if _HOSTNAME_RE.match(value):
        return {
            "kind": "sni",
            "match": await _sni_payload(value, settings.top_snis, 0),
        }

    return {"kind": "unknown", "match": None}


@router.get("/stats", summary="Corpus size")
async def get_stats() -> dict:
    row = await db.stats()
    return {
        "fingerprints": row["fingerprints"],
        "snis": row["snis"],
        "observations": int(row["observations"]),
        "first_seen": _iso(row["first_seen"]),
        "last_seen": _iso(row["last_seen"]),
    }
