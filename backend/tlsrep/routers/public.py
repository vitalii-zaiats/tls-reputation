"""The public read API. No authentication, no keys, no quota.

Everything here is an aggregate over observed TLS handshakes. Nothing in a
response identifies a person: there is no client IP in the database to leak.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from .. import db
from ..classify import sni_category
from ..config import settings
from ..known import known_client
from ..tls import fingerprint
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
        # Curated label if this JA4 matches a known client build. None otherwise.
        # ALPN gates the browser cipher-list match: a Chrome cipher list with a
        # non-browser ALPN is an impersonator, not Chrome.
        "known": known_client(row["ja4"], row["alpn"]),
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


class ClientHelloIn(BaseModel):
    # A single TLS record maxes at 16 KiB of payload plus the 5-byte header; a
    # base64 body a few times that is already generous and caps abuse.
    client_hello: str = Field(
        ..., max_length=65536, description="base64-encoded raw TLS ClientHello record"
    )


@router.post("/reputation", summary="Reputation for a raw ClientHello")
async def reputation(body: ClientHelloIn) -> dict:
    """Fingerprint a raw ClientHello with this project's own engine, then look
    the result up in the corpus.

    Unlike the /ja3 and /ja4 routes, the caller doesn't compute the fingerprint —
    it hands over the bytes and we do, so the JA3/JA4 are guaranteed to be ours.
    The probe server at probe.tls-reputation.com peeks a connecting client's
    ClientHello and posts it here, but anything can: base64 a ClientHello record
    and ask what it is and whether we've seen it.

    Always returns the computed fingerprint and whether the catalog can name the
    client. `observed` says whether this exact JA4 is in the corpus; when it is,
    `reputation` carries the full reach (domains, spread, stability). An unseen
    fingerprint is a legitimate answer, and a useful one: a stable client that
    has never appeared is itself worth a second look.
    """
    try:
        raw = base64.b64decode(body.client_hello, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "client_hello is not valid base64") from None

    fp = fingerprint(raw)
    if fp is None:
        raise HTTPException(
            422, "not a parseable TLS ClientHello (malformed, or arrived truncated)"
        )

    row = await db.fingerprint_by_ja4(fp["ja4"])
    result = {
        "ja4": fp["ja4"],
        "ja3": fp["ja3"],
        "sni": fp["sni"],
        "tls_version": _TLS_VERSION_NAMES.get(fp["tls_version"], "unknown"),
        "alpn": fp["alpn"],
        # Named client build, if the ground-truth catalog recognises this JA4.
        "known": known_client(fp["ja4"], fp["alpn"]),
        # Is this exact JA4 in the corpus? The signal the negative-exclusion
        # strategy leans on: a well-formed, stable fingerprint we've never seen.
        "observed": row is not None,
        "reputation": await _detail(row) if row is not None else None,
    }
    return result


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
        # A name-based hint, not a verdict. Auth-like + many distinct
        # fingerprints is the credential-stuffing shape.
        "category": sni_category(value),
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
                "known": known_client(r["ja4"], r["alpn"]),
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
    alpn: str | None = Query(
        None,
        description=(
            "Filter to one exact ALPN offer list, comma-joined and IN ORDER "
            "(e.g. 'h2,http/1.1'). Order matters: 'http/1.1,h2' is a different "
            "filter and a genuine anomaly. Pass an empty value to select "
            "clients that offered no ALPN. Omit for no filter."
        ),
    ),
) -> dict:
    limit = min(limit, settings.max_limit)

    alpn_filter: list[str] | None = None
    if alpn is not None:
        # Present-but-empty ("?alpn=") selects the no-ALPN population; a
        # non-empty value is split on comma into the offer list, order kept.
        # Whitespace is stripped because the human-readable label from
        # /api/v1/alpn joins with ", " (comma-space), and that label is exactly
        # what the browse UI sends back as the filter — without the strip, the
        # " http/1.1" element would never match the stored "http/1.1".
        alpn_filter = (
            [p.strip() for p in alpn.split(",") if p.strip()] if alpn else []
        )

    rows, total = await db.list_fingerprints(sort, limit, offset, alpn_filter)
    return {"items": [_summary(r) for r in rows], "total": total}


@router.get("/snis", summary="Browse observed domains")
async def list_snis(
    sort: str = Query("observations", pattern="|".join(db.SNI_SORT_KEYS)),
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    category: str | None = Query(
        None,
        pattern="^auth$",
        description=(
            "Filter to a name-based category. 'auth' narrows to auth-looking "
            "server names; crossed with sort=unique_fingerprints this is the "
            "credential-stuffing lens. A hostname heuristic, not a verdict — "
            "high precision, low recall."
        ),
    ),
) -> dict:
    """Domains, sortable by how varied the fingerprints reaching them are.

    `sort=spread` is the interesting one: it ranks domains by how evenly the
    traffic to them is split across distinct client stacks.
    """
    limit = min(limit, settings.max_limit)
    rows, total = await db.list_snis(sort, limit, offset, category)
    return {
        "items": [
            {
                "sni": r["sni"],
                "observations": int(r["observations"]),
                "unique_fingerprints": r["unique_fingerprints"],
                "spread": round(r["spread"], 4),
                # A name-based hint, not a verdict. Auth-like plus many distinct
                # fingerprints is the credential-stuffing shape.
                "category": sni_category(r["sni"]),
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

    # Per-ALPN client split. The catalog names a build, but here we care only
    # about the client, so every environment of "Python requests" collapses to
    # one segment; anything the catalog does not recognise falls into a single
    # anonymous bucket keyed on None. Built once from every fingerprint, then
    # looked up per ALPN offer.
    breakdown: dict[tuple, dict[str | None, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"fingerprints": 0, "observations": 0})
    )
    for fp in await db.alpn_client_fingerprints():
        hit = known_client(fp["ja4"], fp["alpn"])
        name = hit["name"] if hit else None
        seg = breakdown[tuple(fp["alpn"])][name]
        seg["fingerprints"] += 1
        seg["observations"] += int(fp["observations"] or 0)

    def clients_of(alpn: list) -> tuple[list[dict], int, int]:
        """One ALPN offer's split by client: named segments biggest-first, then
        the anonymous remainder. Also returns the named totals, so a row can
        state how much of itself it can put a name to."""
        buckets = breakdown.get(tuple(alpn), {})
        named = [
            {"name": n, "known": True, **w} for n, w in buckets.items() if n is not None
        ]
        named.sort(key=lambda s: (s["fingerprints"], s["observations"]), reverse=True)
        anon = buckets.get(None)
        segments = named + (
            [{"name": None, "known": False, **anon}] if anon else []
        )
        return (
            segments,
            sum(s["fingerprints"] for s in named),
            sum(s["observations"] for s in named),
        )

    items = []
    known_fps_total = known_obs_total = 0
    for r in rows:
        segments, known_fps, known_obs = clients_of(r["alpn"])
        known_fps_total += known_fps
        known_obs_total += known_obs
        obs = int(r["observations"] or 0)
        items.append(
            {
                "alpn": list(r["alpn"]),
                "label": ", ".join(r["alpn"]) or None,
                "fingerprints": r["fingerprints"],
                "observations": obs,
                "share_of_fingerprints": round(r["fingerprints"] / total_fps, 6),
                "share_of_observations": round(obs / total_obs, 6),
                "unique_snis": r["unique_snis"],
                # Of every domain in the corpus, the fraction this ALPN class
                # was seen reaching. Overlapping by construction — see
                # `sni_counts_overlap`.
                "share_of_snis": round(r["unique_snis"] / (corpus_snis or 1), 6),
                # How this ALPN offer breaks down by client, and how much of it
                # the catalog can name at all.
                "clients": segments,
                "known_fingerprints": known_fps,
                "known_observations": known_obs,
            }
        )

    return {
        "total_fingerprints": total_fps,
        "total_observations": total_obs,
        # The number of distinct domains in the whole corpus. Per-ALPN SNI
        # counts are measured against this, NOT against each other: a domain
        # reached by both a browser and a library appears under both, so the
        # per-ALPN counts sum past this total and are not a partition.
        "total_snis": corpus_snis,
        "sni_counts_overlap": True,
        # Corpus-wide, how much of it the catalog can name. Everything else is
        # a fingerprint no ground-truth run has reproduced yet.
        "known_fingerprints": known_fps_total,
        "known_observations": known_obs_total,
        "items": items,
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
