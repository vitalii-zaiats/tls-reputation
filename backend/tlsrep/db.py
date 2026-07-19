"""Postgres access — connection pool, schema bootstrap, and every query.

Queries live here rather than in the routers so the SQL surface is auditable
in one file.
"""

from __future__ import annotations

import math
from pathlib import Path

import asyncpg

from .config import settings

_SCHEMA = Path(__file__).with_name("schema.sql")

_pool: asyncpg.Pool | None = None


async def connect() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.dsn, min_size=settings.pool_min, max_size=settings.pool_max
        )
    return _pool


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("database pool not initialised")
    return _pool


async def apply_schema() -> None:
    """Run schema.sql. Idempotent — every statement is IF NOT EXISTS."""
    async with pool().acquire() as conn:
        await conn.execute(_SCHEMA.read_text())


# ── writes ────────────────────────────────────────────────────────────────

_UPSERT_FINGERPRINT = """
INSERT INTO fingerprints (
    ja3, ja3_raw, ja4, ja4_r, tls_version,
    alpn, ciphers, extensions, curves, sig_algs, point_formats,
    observations
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
ON CONFLICT (ja3, ja4) DO UPDATE
    SET observations = fingerprints.observations + EXCLUDED.observations,
        last_seen    = now()
RETURNING id
"""

_UPSERT_OBSERVATION = """
INSERT INTO observations (fingerprint_id, sni, count)
VALUES ($1, $2, $3)
ON CONFLICT (fingerprint_id, sni) DO UPDATE
    SET count     = observations.count + EXCLUDED.count,
        last_seen = now()
"""


# Recompute the materialised reputation metrics for the fingerprints a batch
# touched. Normalised Shannon entropy: -sum(p*ln(p)) over the SNI distribution,
# divided by ln(n) so a 5-domain and a 500-domain fingerprint stay comparable.
# Fewer than two domains has no entropy to measure and scores 0.
_REFRESH_METRICS = """
WITH d AS (
    SELECT fingerprint_id,
           count::float AS c,
           sum(count) OVER (PARTITION BY fingerprint_id)::float AS total
      FROM observations
     WHERE fingerprint_id = ANY($1::bigint[])
), e AS (
    SELECT fingerprint_id,
           count(*) AS n,
           -sum((c / total) * ln(c / total)) AS entropy
      FROM d
     WHERE c > 0 AND total > 0
     GROUP BY fingerprint_id
)
UPDATE fingerprints f
   SET unique_snis = e.n,
       spread = CASE WHEN e.n < 2 THEN 0
                     ELSE (e.entropy / ln(e.n))::real END
  FROM e
 WHERE f.id = e.fingerprint_id
"""


# The same entropy, computed the other way round: over the distribution of
# fingerprints that reached each domain, rather than domains reached by each
# fingerprint.
_REFRESH_SNI_METRICS = """
WITH d AS (
    SELECT sni,
           count::float AS c,
           sum(count) OVER (PARTITION BY sni)::float AS total
      FROM observations
     WHERE sni = ANY($1::text[])
), e AS (
    SELECT sni,
           count(*) AS n,
           sum(c) AS observations,
           -sum((c / total) * ln(c / total)) AS entropy
      FROM d
     WHERE c > 0 AND total > 0
     GROUP BY sni
)
INSERT INTO snis (sni, observations, unique_fingerprints, spread)
SELECT e.sni,
       e.observations::bigint,
       e.n,
       CASE WHEN e.n < 2 THEN 0 ELSE (e.entropy / ln(e.n))::real END
  FROM e
ON CONFLICT (sni) DO UPDATE
    SET observations        = EXCLUDED.observations,
        unique_fingerprints = EXCLUDED.unique_fingerprints,
        spread              = EXCLUDED.spread,
        last_seen           = now()
"""


async def record_batch(records: list[dict]) -> int:
    """Fold a batch of parsed ClientHellos into the counters.

    Records are pre-aggregated by the caller so a batch of 500 identical
    hellos costs one UPDATE, not 500.
    """
    written = 0
    touched: list[int] = []
    touched_snis: set[str] = set()
    async with pool().acquire() as conn, conn.transaction():
        for rec in records:
            fp_id = await conn.fetchval(
                _UPSERT_FINGERPRINT,
                rec["ja3"],
                rec["ja3_raw"],
                rec["ja4"],
                rec["ja4_r"],
                rec["tls_version"],
                rec["alpn"],
                rec["ciphers"],
                rec["extensions"],
                rec["curves"],
                rec["sig_algs"],
                rec["point_formats"],
                rec["count"],
            )
            touched.append(fp_id)
            for sni, count in rec["snis"].items():
                await conn.execute(_UPSERT_OBSERVATION, fp_id, sni, count)
                touched_snis.add(sni)
            written += rec["count"]

        if touched:
            await conn.execute(_REFRESH_METRICS, touched)
        if touched_snis:
            await conn.execute(_REFRESH_SNI_METRICS, list(touched_snis))
    return written


# ── reads ─────────────────────────────────────────────────────────────────

_FP_COLUMNS = """
    f.id, f.ja3, f.ja3_raw, f.ja4, f.ja4_r, f.tls_version, f.alpn,
    f.ciphers, f.extensions, f.curves, f.sig_algs, f.point_formats,
    f.observations, f.unique_snis, f.spread, f.first_seen, f.last_seen
"""


async def fingerprint_by_ja3(ja3: str) -> asyncpg.Record | None:
    """Most-observed fingerprint carrying this JA3.

    A JA3 can map to several JA4s (JA4 keeps ALPN and version detail JA3
    discards), so this picks the dominant one and the caller surfaces the rest.
    """
    async with pool().acquire() as conn:
        return await conn.fetchrow(
            f"SELECT {_FP_COLUMNS} FROM fingerprints f WHERE f.ja3 = $1"
            " ORDER BY f.observations DESC LIMIT 1",
            ja3,
        )


async def fingerprint_by_ja4(ja4: str) -> asyncpg.Record | None:
    async with pool().acquire() as conn:
        return await conn.fetchrow(
            f"SELECT {_FP_COLUMNS} FROM fingerprints f WHERE f.ja4 = $1"
            " ORDER BY f.observations DESC LIMIT 1",
            ja4,
        )


async def siblings_for_ja3(ja3: str, exclude_id: int) -> list[asyncpg.Record]:
    """Other JA4s sharing this JA3 — the detail page links them."""
    async with pool().acquire() as conn:
        return await conn.fetch(
            "SELECT ja4, observations FROM fingerprints"
            " WHERE ja3 = $1 AND id <> $2 ORDER BY observations DESC LIMIT 20",
            ja3,
            exclude_id,
        )


async def top_snis(
    fingerprint_id: int, limit: int, offset: int = 0
) -> list[asyncpg.Record]:
    async with pool().acquire() as conn:
        return await conn.fetch(
            "SELECT sni, count, first_seen, last_seen FROM observations"
            " WHERE fingerprint_id = $1"
            " ORDER BY count DESC, sni ASC LIMIT $2 OFFSET $3",
            fingerprint_id,
            limit,
            offset,
        )


async def sni_detail(sni: str, limit: int, offset: int) -> dict:
    async with pool().acquire() as conn:
        totals = await conn.fetchrow(
            "SELECT observations, unique_fingerprints, spread,"
            "       first_seen, last_seen"
            " FROM snis WHERE sni = $1",
            sni,
        )
        rows = await conn.fetch(
            "SELECT f.ja3, f.ja4, o.count, o.first_seen, o.last_seen"
            " FROM observations o JOIN fingerprints f ON f.id = o.fingerprint_id"
            " WHERE o.sni = $1 ORDER BY o.count DESC LIMIT $2 OFFSET $3",
            sni,
            limit,
            offset,
        )
    return {"totals": totals, "rows": rows}


# Whitelist, not interpolation: `sort` reaches SQL as an ORDER BY clause, so
# it must never be caller-controlled text.
_SORTS = {
    "observations": "f.observations DESC",
    "unique_snis": "f.unique_snis DESC",
    "spread": "f.spread DESC, f.observations DESC",
    "last_seen": "f.last_seen DESC",
}
SORT_KEYS = tuple(_SORTS)


async def list_fingerprints(
    sort: str, limit: int, offset: int
) -> tuple[list[asyncpg.Record], int]:
    order = _SORTS.get(sort, _SORTS["observations"])
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            f"SELECT {_FP_COLUMNS} FROM fingerprints f"
            f" ORDER BY {order} LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
        total = await conn.fetchval("SELECT count(*) FROM fingerprints")
    return rows, total


_SNI_SORTS = {
    "observations": "observations DESC",
    "unique_fingerprints": "unique_fingerprints DESC",
    "spread": "spread DESC, observations DESC",
    "last_seen": "last_seen DESC",
}
SNI_SORT_KEYS = tuple(_SNI_SORTS)


async def list_snis(
    sort: str, limit: int, offset: int
) -> tuple[list[asyncpg.Record], int]:
    order = _SNI_SORTS.get(sort, _SNI_SORTS["observations"])
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT sni, observations, unique_fingerprints, spread,"
            "       first_seen, last_seen"
            f" FROM snis ORDER BY {order} LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
        total = await conn.fetchval("SELECT count(*) FROM snis")
    return rows, total


async def stats() -> dict:
    async with pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT count(*) AS fingerprints,"
            "       coalesce(sum(observations), 0) AS observations,"
            "       min(first_seen) AS first_seen,"
            "       max(last_seen)  AS last_seen"
            " FROM fingerprints"
        )
        snis = await conn.fetchval("SELECT count(*) FROM snis")
    return {**dict(row), "snis": snis}


# ── derived metrics ───────────────────────────────────────────────────────


def spread(counts: list[int]) -> float:
    """Reference implementation of the spread score, mirroring _REFRESH_METRICS.

    Production reads the materialised `fingerprints.spread` column; this exists
    so the SQL can be checked against a readable definition in the tests.

    Normalised Shannon entropy of a fingerprint's SNI distribution, 0..1.

    0 means every connection went to the same domain. 1 means the connections
    were spread evenly across many domains. A browser sits low; a scraper
    pointed at target after target sits high. Normalising by log(n) is what
    makes a 5-domain and a 500-domain fingerprint comparable — without it the
    score would just re-measure how many domains there are.

    A single-domain fingerprint has no entropy to measure, so it scores 0.
    """
    total = sum(counts)
    if total <= 0 or len(counts) < 2:
        return 0.0
    entropy = -sum(
        (c / total) * math.log(c / total) for c in counts if c > 0
    )
    return round(entropy / math.log(len(counts)), 4)
