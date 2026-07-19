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


# Below this many observations a fingerprint cannot be classified: two
# connections that happen to carry two JA3s look exactly like a permuting
# client, and are not.
_STABILITY_MIN_OBSERVATIONS = 16

# A client presenting a never-before-seen JA3 on more than half its connections
# is permuting its hello, not shipping a few builds.
_RANDOMIZING_THRESHOLD = 0.5


def _stability(row, dominant: int = 0) -> dict:
    """Does this client stack randomise its own fingerprint?

    The second axis of the site, orthogonal to spread. Spread says how widely a
    stack roams; this says whether the stack is deterministic. It is a claim
    about software, which is the only kind of claim this corpus can support —
    it stores no per-connection identity, so it can never distinguish one
    scraper visiting 500 domains from 500 people visiting one each.
    """
    observations = row["observations"] or 0
    variants = row["ja3_variants"] or 0
    novelty = float(row["ja3_novelty"] or 0.0)

    if observations < _STABILITY_MIN_OBSERVATIONS:
        klass = "unknown"
        explanation = (
            f"only {observations} observation(s) — too few to tell a permuting "
            "client from a coincidence."
        )
    elif variants <= 1:
        klass = "fixed"
        explanation = (
            f"one JA3 across {observations} connections: a deterministic stack. "
            "Libraries and command-line clients look like this."
        )
    elif novelty >= _RANDOMIZING_THRESHOLD:
        klass = "randomizing"
        explanation = (
            f"{round(novelty * 100)}% of connections presented a JA3 never seen "
            "before for this client — it reshuffles its own ClientHello. Chrome "
            "has permuted extension order since version 110."
        )
    else:
        klass = "multi_build"
        explanation = (
            f"{variants} JA3s over {observations} connections, but most repeat: "
            "a handful of stable builds sharing one JA4 rather than per-connection "
            "randomisation."
        )

    payload = {
        "class": klass,
        "novelty": round(novelty, 4),
        "variants": variants,
        # Past the cap the variant count is a floor, not a total, and must not
        # be rendered as though it were exact.
        "variants_capped": bool(row["ja3_variants_capped"]),
        "observations": observations,
        "explanation": explanation,
    }

    if dominant and observations:
        share = dominant / observations
        payload["dominant_variant_share"] = round(share, 4)
        # A JA4 that looks like a permuting browser, yet carries most of its
        # traffic on ONE JA3, is a deterministic client wearing that browser's
        # shape. curl-impersonate and uTLS reproduce Chrome's JA4 exactly and
        # do not implement the permutation behind it.
        if klass == "randomizing" and share >= 0.5:
            payload["note"] = (
                "most traffic sits on a single JA3 despite the randomising "
                "profile — consistent with a deterministic client imitating a "
                "browser's JA4."
            )

    return payload


def _summary(row) -> dict:
    """The compact shape used in list endpoints."""
    return {
        "ja4": row["ja4"],
        # Null unless exactly one JA3 has ever been seen. A representative JA3
        # for a permuting client is a value that will never match again.
        "ja3": row["ja3"],
        "tls_version": _TLS_VERSION_NAMES.get(row["tls_version"], "unknown"),
        "alpn": list(row["alpn"]),
        "observations": row["observations"],
        "unique_snis": row["unique_snis"],
        "spread": round(row["spread"], 4),
        "stability": _stability(row),
        "first_seen": _iso(row["first_seen"]),
        "last_seen": _iso(row["last_seen"]),
    }


async def _detail(row, matched_ja3: str | None = None) -> dict:
    snis = await db.top_snis(row["id"], settings.top_snis)
    embedded = 20
    variants, variant_total, dominant = await db.ja3_variants(row["id"], embedded, 0)
    total = row["observations"] or 1

    payload = {
        **_summary(row),
        "stability": _stability(row, dominant),
        "ja3_raw": row["ja3_raw"],
        "ja4_r": row["ja4_r"],
        "cipher_suites": decorate(row["ciphers"], CIPHERS),
        # Stored sorted, and labelled as such: under one JA4 the wire order
        # varies by construction, so presenting one arrival's order as "the"
        # order would be inventing a fact.
        "extensions": decorate(row["extensions"], EXTENSIONS),
        "extensions_sorted": True,
        "curves": decorate(row["curves"], CURVES),
        "sig_algs": decorate(row["sig_algs"], SIG_ALGOS),
        "point_formats": [f"0x{v:04x}" for v in row["point_formats"]],
        "ja3_variants": {
            "total": variant_total,
            # Two different facts, deliberately separate. `capped` means ingest
            # stopped growing the stored set, so `total` is a floor. `truncated`
            # means this response carries only the busiest slice of what IS
            # stored.
            "capped": bool(row["ja3_variants_capped"]),
            "truncated": variant_total > len(variants),
            "returned": len(variants),
            "items": [
                {
                    "ja3": v["ja3"],
                    "ja3_raw": v["ja3_raw"],
                    "observations": v["observations"],
                }
                for v in variants
            ],
        },
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

    if matched_ja3:
        others = await db.ja4s_for_ja3(matched_ja3, row["id"])
        payload["matched_ja3"] = {
            "ja3": matched_ja3,
            # The JA4 this JA3 resolved to. Non-null means the resolution was
            # unambiguous and the client may treat this page as canonical.
            "canonical": row["ja4"] if not others else None,
            "also_seen_under": [
                {"ja4": o["ja4"], "observations": o["observations"]} for o in others
            ],
        }

    return payload


@router.get("/ja3/{value}", summary="Look up a fingerprint by JA3 (MD5)")
async def get_ja3(value: str = Path(..., description="32-char JA3 MD5")) -> dict:
    if not _JA3_RE.match(value):
        raise HTTPException(400, "not a JA3 hash (expected 32 hex characters)")
    row = await db.fingerprint_by_ja3(value.lower())
    if row is None:
        raise HTTPException(
            404,
            "JA3 not observed. Note that a client which permutes its ClientHello "
            "emits a new JA3 per connection, so an unseen JA3 does not mean the "
            "client is unknown — look it up by JA4 instead.",
        )
    return await _detail(row, matched_ja3=value.lower())


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
                "stability": _stability(r),
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
        return {
            "kind": "ja3",
            "match": await _detail(row, matched_ja3=value) if row else None,
        }
    if _JA4_RE.match(value):
        row = await db.fingerprint_by_ja4(value)
        return {"kind": "ja4", "match": await _detail(row) if row else None}
    if _HOSTNAME_RE.match(value):
        return {
            "kind": "sni",
            "match": await _sni_payload(value, settings.top_snis, 0),
        }

    return {"kind": "unknown", "match": None}


@router.get("/alpn", summary="How the corpus splits across ALPN offers")
async def get_alpn() -> dict:
    """ALPN distribution, keyed on the offer list IN ORDER.

    The order is never normalised, because it is the signal. A browser offers
    `h2, http/1.1` in that order; a client listing them the other way round is
    not the browser it claims to be. JA4 cannot carry this — it keeps only the
    first and last character of the FIRST protocol, so `h2` and `h2, http/1.1`
    reduce to the same two characters.

    Reported both per distinct fingerprint and per observation: the two
    disagree, and the disagreement is informative. A handful of library
    fingerprints can account for a large share of connections.
    """
    rows = await db.alpn_distribution()
    total_fps = sum(r["fingerprints"] for r in rows) or 1
    total_obs = sum(int(r["observations"] or 0) for r in rows) or 1
    corpus_snis = await db.sni_count()

    return {
        "total_fingerprints": total_fps,
        "total_observations": total_obs,
        # The number of distinct domains in the whole corpus. Per-ALPN SNI
        # counts are measured against this, NOT against each other: a domain
        # reached by both a browser and a library appears under both, so the
        # per-ALPN counts sum past this total and are not a partition.
        "total_snis": corpus_snis,
        "sni_counts_overlap": True,
        "items": [
            {
                "alpn": list(r["alpn"]),
                "label": ", ".join(r["alpn"]) or None,
                "fingerprints": r["fingerprints"],
                "observations": int(r["observations"] or 0),
                "share_of_fingerprints": round(r["fingerprints"] / total_fps, 6),
                "share_of_observations": round(
                    int(r["observations"] or 0) / total_obs, 6
                ),
                "unique_snis": r["unique_snis"],
                # Of every domain in the corpus, the fraction this ALPN class
                # was seen reaching. Overlapping by construction — see
                # `sni_counts_overlap`.
                "share_of_snis": round(r["unique_snis"] / (corpus_snis or 1), 6),
            }
            for r in rows
        ],
    }


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
