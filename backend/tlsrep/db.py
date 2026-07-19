"""Postgres access — connection pool, schema bootstrap, and every query.

Queries live here rather than in the routers so the SQL surface is auditable
in one file.
"""

from __future__ import annotations

import math
from pathlib import Path

import asyncpg

from .classify import AUTH_SQL_REGEX
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

# The known-variant set per fingerprint is bounded. Without a cap, a permuting
# client would write one variant row per connection — reintroducing, in a new
# table, exactly the fragmentation this schema exists to remove.
JA3_VARIANT_CAP = 128

_UPSERT_FINGERPRINT = """
INSERT INTO fingerprints (
    ja4, ja4_r, tls_version,
    alpn, ciphers, extensions, curves, sig_algs, point_formats,
    observations
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
ON CONFLICT (ja4) DO UPDATE
    SET observations = fingerprints.observations + EXCLUDED.observations,
        last_seen    = now()
RETURNING id
"""

# xmax = 0 is true only when this statement inserted the row rather than
# updating it. Deriving novelty from what the database actually did — instead
# of from a prior SELECT — is what stops two concurrent ingest workers both
# counting the same JA3 as new.
_ADD_VARIANT = """
INSERT INTO fingerprint_ja3 (fingerprint_id, ja3, ja3_raw, extensions, observations)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (fingerprint_id, ja3) DO UPDATE
    SET observations = fingerprint_ja3.observations + EXCLUDED.observations
RETURNING (xmax = 0) AS inserted
"""

_VARIANT_KNOWN = """
SELECT 1 FROM fingerprint_ja3 WHERE fingerprint_id = $1 AND ja3 = $2
"""

_VARIANT_COUNT = """
SELECT count(*) FROM fingerprint_ja3 WHERE fingerprint_id = $1
"""

# Roll the per-fingerprint variant summary back onto the parent. `ja3`/`ja3_raw`
# are set only while exactly one variant exists — a representative JA3 for a
# permuting client is a value that will never match anything again.
_SYNC_VARIANT_STATE = """
UPDATE fingerprints f
   SET ja3_variants        = v.n,
       ja3_variants_capped = (v.n >= $2),
       ja3_novel           = f.ja3_novel + $3,
       ja3                 = CASE WHEN v.n = 1 THEN v.only_ja3 ELSE NULL END,
       ja3_raw             = CASE WHEN v.n = 1 THEN v.only_raw ELSE NULL END
  FROM (
        SELECT count(*) AS n,
               min(ja3)     AS only_ja3,
               min(ja3_raw) AS only_raw
          FROM fingerprint_ja3 WHERE fingerprint_id = $1
       ) v
 WHERE f.id = $1
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

# The same entropy the other way round: over the distinct JA4s that reached
# each domain. Counting JA4s rather than (ja3, ja4) pairs is the whole point —
# the pair keying inflated this by two orders of magnitude wherever a permuting
# browser appeared, and pinned spread to 1.000 there.
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


async def _record_variants(conn, fp_id: int, ja3s: dict) -> int:
    """Record the JA3s seen for this fingerprint; return the novel connection count.

    Novel means "presented a JA3 not already in this fingerprint's known set".
    Once the set is full it is frozen, so a client that permutes its hello keeps
    missing it and stays scored as randomising however long it runs — which a
    plain variants/observations ratio would not, because that ratio decays to
    zero the moment the table saturates.
    """
    known = await conn.fetchval(_VARIANT_COUNT, fp_id)
    novel = 0

    for ja3, (ja3_raw, extensions, count) in sorted(ja3s.items()):
        if known < JA3_VARIANT_CAP:
            inserted = await conn.fetchval(
                _ADD_VARIANT, fp_id, ja3, ja3_raw, extensions, count
            )
            if inserted:
                known += 1
                # Exactly ONE connection introduced this JA3, however many
                # times the batch went on to repeat it. Counting the repeats as
                # novel would score a client that sends the same hello a
                # thousand times as though it had randomised a thousand times.
                novel += 1
        elif not await conn.fetchval(_VARIANT_KNOWN, fp_id, ja3):
            # Capped: still count the novelty, just stop growing the table.
            novel += count

    return novel


async def record_batch(records: list[dict]) -> int:
    """Fold a batch of parsed ClientHellos into the counters.

    Records are pre-aggregated by the caller so a batch of 500 identical hellos
    costs one UPDATE, not 500. Iteration is sorted by JA4 so concurrent workers
    touch the now-hot per-browser rows in the same order and cannot deadlock
    against one another.
    """
    written = 0
    touched: list[int] = []
    touched_snis: set[str] = set()

    async with pool().acquire() as conn, conn.transaction():
        for rec in sorted(records, key=lambda r: r["ja4"]):
            fp_id = await conn.fetchval(
                _UPSERT_FINGERPRINT,
                rec["ja4"],
                rec["ja4_r"],
                rec["tls_version"],
                rec["alpn"],
                rec["ciphers"],
                # Sorted: under one JA4 the wire order varies by construction,
                # so whichever arrived first is not "the" order.
                sorted(rec["extensions"]),
                rec["curves"],
                rec["sig_algs"],
                rec["point_formats"],
                rec["count"],
            )
            touched.append(fp_id)

            novel = await _record_variants(conn, fp_id, rec["ja3s"])
            await conn.execute(_SYNC_VARIANT_STATE, fp_id, JA3_VARIANT_CAP, novel)

            for sni, count in rec["snis"].items():
                await conn.execute(_UPSERT_OBSERVATION, fp_id, sni, count)
                touched_snis.add(sni)

            written += rec["count"]

        if touched:
            await conn.execute(_REFRESH_METRICS, sorted(touched))
        if touched_snis:
            await conn.execute(_REFRESH_SNI_METRICS, sorted(touched_snis))

    return written


# ── reads ─────────────────────────────────────────────────────────────────

_FP_COLUMNS = """
    f.id, f.ja4, f.ja4_r, f.ja3, f.ja3_raw,
    f.ja3_variants, f.ja3_variants_capped, f.ja3_novel, f.ja3_novelty,
    f.tls_version, f.alpn,
    f.ciphers, f.extensions, f.curves, f.sig_algs, f.point_formats,
    f.observations, f.unique_snis, f.spread, f.first_seen, f.last_seen
"""


async def fingerprint_by_ja4(ja4: str) -> asyncpg.Record | None:
    async with pool().acquire() as conn:
        return await conn.fetchrow(
            f"SELECT {_FP_COLUMNS} FROM fingerprints f WHERE f.ja4 = $1", ja4
        )


async def fingerprint_by_ja3(ja3: str) -> asyncpg.Record | None:
    """Resolve a JA3 to the fingerprint that emitted it.

    JA3 is no longer an identity: a permuting client emits a new one per
    connection, so this is a lookup through the variant table. One JA3 can in
    principle appear under more than one JA4 — two client stacks whose hellos
    differ only in something JA4 normalises away — so the busiest wins and the
    caller surfaces the ambiguity.
    """
    async with pool().acquire() as conn:
        return await conn.fetchrow(
            f"""
            SELECT {_FP_COLUMNS}
              FROM fingerprint_ja3 v
              JOIN fingerprints f ON f.id = v.fingerprint_id
             WHERE v.ja3 = $1
             ORDER BY f.observations DESC
             LIMIT 1
            """,
            ja3,
        )


async def ja4s_for_ja3(ja3: str, exclude_id: int) -> list[asyncpg.Record]:
    """Other fingerprints that have also emitted this JA3."""
    async with pool().acquire() as conn:
        return await conn.fetch(
            """
            SELECT f.ja4, f.observations
              FROM fingerprint_ja3 v
              JOIN fingerprints f ON f.id = v.fingerprint_id
             WHERE v.ja3 = $1 AND f.id <> $2
             ORDER BY f.observations DESC
             LIMIT 20
            """,
            ja3,
            exclude_id,
        )


async def ja3_variants(
    fingerprint_id: int, limit: int, offset: int
) -> tuple[list[asyncpg.Record], int, int]:
    """The JA3s this fingerprint has emitted, busiest first."""
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT ja3, ja3_raw, extensions, observations"
            "  FROM fingerprint_ja3 WHERE fingerprint_id = $1"
            " ORDER BY observations DESC, ja3 ASC LIMIT $2 OFFSET $3",
            fingerprint_id,
            limit,
            offset,
        )
        total = await conn.fetchval(
            "SELECT count(*) FROM fingerprint_ja3 WHERE fingerprint_id = $1",
            fingerprint_id,
        )
        # The share of connections carried by the single busiest variant. Under
        # a JA4 that otherwise looks like a permuting browser, a high value
        # means a deterministic client is wearing that browser's shape — which
        # is what curl-impersonate and uTLS do, faithfully reproducing the JA4
        # while never implementing the permutation behind it.
        dominant = await conn.fetchval(
            "SELECT max(observations) FROM fingerprint_ja3 WHERE fingerprint_id = $1",
            fingerprint_id,
        )
    return rows, total, dominant or 0


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
            "SELECT f.ja3, f.ja4, f.alpn, f.observations, f.ja3_variants,"
            "       f.ja3_variants_capped, f.ja3_novelty,"
            "       o.count, o.first_seen, o.last_seen"
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
    sort: str, limit: int, offset: int, alpn: list[str] | None = None
) -> tuple[list[asyncpg.Record], int]:
    """List fingerprints, optionally filtered to one exact ALPN offer list.

    `alpn` is matched in order and as a whole, not as a set: `['h2','http/1.1']`
    and `['http/1.1','h2']` are different filters, because the offer order is
    the signal. Passing `[]` selects clients that advertised no ALPN at all.
    Passing None applies no filter.
    """
    order = _SORTS.get(sort, _SORTS["observations"])
    # A parameterised array equality — never string-interpolated. The ORDER BY
    # is the only interpolated fragment and it comes from the _SORTS whitelist.
    # The filter sits at a different parameter index in each query, so each
    # spells its own: $3 after (limit, offset) in the page query, $1 in the
    # bare count.
    async with pool().acquire() as conn:
        if alpn is None:
            rows = await conn.fetch(
                f"SELECT {_FP_COLUMNS} FROM fingerprints f"
                f" ORDER BY {order} LIMIT $1 OFFSET $2",
                limit,
                offset,
            )
            total = await conn.fetchval("SELECT count(*) FROM fingerprints")
        else:
            rows = await conn.fetch(
                f"SELECT {_FP_COLUMNS} FROM fingerprints f"
                f" WHERE f.alpn = $3::text[]"
                f" ORDER BY {order} LIMIT $1 OFFSET $2",
                limit,
                offset,
                alpn,
            )
            total = await conn.fetchval(
                "SELECT count(*) FROM fingerprints f WHERE f.alpn = $1::text[]",
                alpn,
            )
    return rows, total


_SNI_SORTS = {
    "observations": "observations DESC",
    "unique_fingerprints": "unique_fingerprints DESC",
    "spread": "spread DESC, observations DESC",
    "last_seen": "last_seen DESC",
}
SNI_SORT_KEYS = tuple(_SNI_SORTS)


async def list_snis(
    sort: str, limit: int, offset: int, category: str | None = None
) -> tuple[list[asyncpg.Record], int]:
    """List domains, optionally filtered to a name-based category.

    `category="auth"` narrows to auth-looking server names. Crossed with a sort
    on unique_fingerprints or spread, that is the credential-stuffing lens: an
    auth endpoint reached by many distinct client stacks. The regex is derived
    from the same term list the Python classifier uses, so filter and label
    cannot drift apart.
    """
    order = _SNI_SORTS.get(sort, _SNI_SORTS["observations"])
    async with pool().acquire() as conn:
        if category == "auth":
            rows = await conn.fetch(
                "SELECT sni, observations, unique_fingerprints, spread,"
                "       first_seen, last_seen"
                f" FROM snis WHERE sni ~* $3 ORDER BY {order} LIMIT $1 OFFSET $2",
                limit,
                offset,
                AUTH_SQL_REGEX,
            )
            total = await conn.fetchval(
                "SELECT count(*) FROM snis WHERE sni ~* $1", AUTH_SQL_REGEX
            )
        else:
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

async def alpn_distribution() -> list[asyncpg.Record]:
    """How the corpus splits across ALPN offers, in offer order.

    The order is the signal and is never normalised: a browser offers
    `h2, http/1.1` in that order, and a client that lists them the other way
    round is not the browser it claims to be. JA4 cannot express this — it
    keeps only the first and last character of the FIRST protocol, so `h2` and
    `h2, http/1.1` collapse to the same two characters.

    Three measures, and they do not mean the same thing:

      fingerprints  how many distinct client stacks offer this list
      observations  how many connections they made
      unique_snis   how many distinct domains those stacks reached

    The first two partition the corpus and sum to the whole. The third does
    NOT: a domain reached by both a browser and a library is counted under
    both, so these sum past the total. Anything rendering this has to say so
    rather than drawing it as a share of a whole.
    """
    async with pool().acquire() as conn:
        return await conn.fetch(
            """
            WITH per_fp AS (
                SELECT alpn,
                       count(*)          AS fingerprints,
                       sum(observations) AS observations
                  FROM fingerprints
                 GROUP BY alpn
            ), per_sni AS (
                SELECT f.alpn, count(DISTINCT o.sni) AS unique_snis
                  FROM fingerprints f
                  JOIN observations o ON o.fingerprint_id = f.id
                 GROUP BY f.alpn
            )
            SELECT per_fp.alpn,
                   per_fp.fingerprints,
                   per_fp.observations,
                   coalesce(per_sni.unique_snis, 0) AS unique_snis
              FROM per_fp
              LEFT JOIN per_sni
                     ON per_sni.alpn IS NOT DISTINCT FROM per_fp.alpn
             ORDER BY per_fp.fingerprints DESC, per_fp.observations DESC
            """
        )


async def alpn_client_fingerprints() -> list[asyncpg.Record]:
    """Every fingerprint with its ALPN offer and weight, for the client split.

    The catalog that turns a ja4 into a client name lives in Python, not the
    database, so the join to it cannot happen in SQL. This returns the raw
    material — one row per fingerprint (ja4 is unique), carrying its ALPN offer
    and how much traffic it carries — and the router folds it into, per ALPN
    offer, how much is each known client versus still anonymous.
    """
    async with pool().acquire() as conn:
        return await conn.fetch("SELECT alpn, ja4, observations FROM fingerprints")


async def sni_count() -> int:
    """Distinct domains in the corpus — the denominator for per-ALPN SNI reach."""
    async with pool().acquire() as conn:
        return await conn.fetchval("SELECT count(*) FROM snis") or 0
