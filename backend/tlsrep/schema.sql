-- tls-reputation schema.
--
-- Two tables and nothing else. The design constraint that shapes both: we
-- store a fingerprint and the domain it reached for, and NOTHING that
-- identifies who made the connection. No client IP, no timestamps per
-- connection, no raw ClientHello. A fingerprint is a property of a software
-- stack shared by millions of installs; the pair (fingerprint, SNI) with a
-- counter is an aggregate, not a browsing history. Keeping it that way is
-- what makes this corpus publishable.
--
-- Idempotent: safe to re-run on every deploy.

CREATE TABLE IF NOT EXISTS fingerprints (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ja3             CHAR(32)     NOT NULL,
    ja3_raw         TEXT         NOT NULL,
    ja4             VARCHAR(64)  NOT NULL,
    ja4_r           TEXT         NOT NULL,

    -- Decoded ClientHello, kept so the detail page needs no re-parse.
    tls_version     INTEGER      NOT NULL,
    alpn            TEXT[]       NOT NULL DEFAULT '{}',
    ciphers         INTEGER[]    NOT NULL DEFAULT '{}',
    extensions      INTEGER[]    NOT NULL DEFAULT '{}',
    curves          INTEGER[]    NOT NULL DEFAULT '{}',
    sig_algs        INTEGER[]    NOT NULL DEFAULT '{}',
    point_formats   INTEGER[]    NOT NULL DEFAULT '{}',

    observations    BIGINT       NOT NULL DEFAULT 0,

    -- Materialised from `observations` after each ingest batch. Kept as real
    -- columns so the browse/sort endpoints are an index scan rather than an
    -- entropy calculation over every row on every request.
    unique_snis     INTEGER      NOT NULL DEFAULT 0,
    spread          REAL         NOT NULL DEFAULT 0,

    first_seen      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT fingerprints_ja3_ja4_key UNIQUE (ja3, ja4)
);

-- One row per (fingerprint, domain) pair. `count` is what makes a reputation:
-- a fingerprint with 4 rows is somebody's browser, one with 900 rows spread
-- evenly is a tool being pointed at target after target.
CREATE TABLE IF NOT EXISTS observations (
    fingerprint_id  BIGINT       NOT NULL
                    REFERENCES fingerprints(id) ON DELETE CASCADE,
    sni             TEXT         NOT NULL,
    count           BIGINT       NOT NULL DEFAULT 0,
    first_seen      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ  NOT NULL DEFAULT now(),

    PRIMARY KEY (fingerprint_id, sni)
);

-- The mirror of `fingerprints`, keyed the other way. Same reason for existing:
-- browsing and sorting domains by how varied their callers are must be an
-- index scan, not an entropy calculation over every observation.
--
-- The metric reads inversely to a fingerprint's. There, high spread means one
-- client stack reaching for many unrelated domains — tooling. Here, high
-- spread means one domain being reached by many different client stacks in
-- similar proportions. A popular site legitimately sees a wide mix, so this is
-- only interesting against volume and against what the endpoint is: a login
-- form hit by hundreds of evenly-distributed fingerprints is the shape of an
-- attacker rotating fingerprints, not of a crowd.
CREATE TABLE IF NOT EXISTS snis (
    sni                 TEXT         PRIMARY KEY,
    observations        BIGINT       NOT NULL DEFAULT 0,
    unique_fingerprints INTEGER      NOT NULL DEFAULT 0,
    spread              REAL         NOT NULL DEFAULT 0,
    first_seen          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen           TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_snis_obs    ON snis (observations DESC);
CREATE INDEX IF NOT EXISTS idx_snis_uniq   ON snis (unique_fingerprints DESC);
CREATE INDEX IF NOT EXISTS idx_snis_spread ON snis (spread DESC);

-- Backfill for databases that were collecting before this table existed.
-- Guarded on the table being empty, so it runs once rather than re-scanning
-- every observation on every startup. Ingest maintains it from then on.
INSERT INTO snis (sni, observations, unique_fingerprints, spread)
WITH d AS (
    SELECT sni,
           count::float AS c,
           sum(count) OVER (PARTITION BY sni)::float AS total
      FROM observations
     WHERE NOT EXISTS (SELECT 1 FROM snis)
), e AS (
    SELECT sni,
           count(*) AS n,
           sum(c) AS observations,
           -sum((c / total) * ln(c / total)) AS entropy
      FROM d
     WHERE c > 0 AND total > 0
     GROUP BY sni
)
SELECT e.sni,
       e.observations::bigint,
       e.n,
       CASE WHEN e.n < 2 THEN 0 ELSE (e.entropy / ln(e.n))::real END
  FROM e
ON CONFLICT (sni) DO NOTHING;

-- Lookup by either fingerprint form. ja3 is not unique on its own (two JA4s
-- can share a JA3), so this is a plain index, not a constraint.
CREATE INDEX IF NOT EXISTS idx_fingerprints_ja3  ON fingerprints (ja3);
CREATE INDEX IF NOT EXISTS idx_fingerprints_ja4  ON fingerprints (ja4);

-- Ordering for /fingerprints?sort=
CREATE INDEX IF NOT EXISTS idx_fingerprints_obs    ON fingerprints (observations DESC);
CREATE INDEX IF NOT EXISTS idx_fingerprints_uniq   ON fingerprints (unique_snis DESC);
CREATE INDEX IF NOT EXISTS idx_fingerprints_spread ON fingerprints (spread DESC);
CREATE INDEX IF NOT EXISTS idx_fingerprints_seen   ON fingerprints (last_seen DESC);

-- The reverse direction: domain -> which fingerprints reached it.
CREATE INDEX IF NOT EXISTS idx_observations_sni  ON observations (sni);

-- There is deliberately NO index on (fingerprint_id, count DESC), even though
-- top-SNI-per-fingerprint is the hottest read on the site.
--
-- Indexing `count` would index the one column every ingest writes. Measured on
-- 5M observations: with that index, 0 of 4,000,000 counter updates were
-- heap-only (HOT) — each one also rewrote an index entry — and the table grew
-- 45% over 3M updates. Dropping it took HOT to 43% and growth to 30%, and the
-- index itself was 309 MB of the 1.3 GB total.
--
-- The read stays fast without it: the primary key already leads with
-- fingerprint_id, so the top-N is a PK range scan plus an in-memory sort of
-- one fingerprint's rows — 0.78 ms against 0.27 ms with the index. Paying 0.5 ms
-- on reads to halve the write amplification on a counter table is the right
-- side of that trade.
--
-- Revisit if a single fingerprint ever accumulates enough SNIs that sorting
-- them stops being cheap.
DROP INDEX IF EXISTS idx_observations_fp_count;

-- Leave 20% of each page free so counter updates can stay on-page (HOT) rather
-- than allocating a new tuple elsewhere and touching every index.
ALTER TABLE observations SET (fillfactor = 80);

-- This table is written far more than it is read, and every write is an UPDATE
-- of a counter. The stock autovacuum thresholds (20% of the table) let dead
-- tuples pile into the millions before a run; at that size a vacuum is long and
-- the bloat between runs is what shows up as disk growth. Vacuum earlier and
-- more often instead.
ALTER TABLE observations SET (
    autovacuum_vacuum_scale_factor  = 0.02,
    autovacuum_vacuum_threshold     = 1000,
    autovacuum_analyze_scale_factor = 0.05,
    autovacuum_vacuum_cost_delay    = 2
);
