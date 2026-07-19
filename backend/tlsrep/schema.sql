-- tls-reputation schema.
--
-- The design constraint that shapes all of it: we store a fingerprint and the
-- domain it reached for, and NOTHING that identifies who made the connection.
-- No client IP, no per-connection timestamp, no raw ClientHello. A fingerprint
-- is a property of a software stack shared by millions of installs; the triple
-- (fingerprint, domain, counter) is an aggregate, not a browsing history.
-- Keeping it that way is what makes this corpus publishable.
--
-- IDENTITY IS JA4, NOT (JA3, JA4).
--
-- Chrome 110 shipped ClientHello extension permutation: the extension order is
-- reshuffled on every connection, deliberately, to stop middleboxes ossifying
-- on it. JA3 hashes the extension list IN ORDER, so such a client emits a
-- different JA3 every single time. JA4 sorts extensions before hashing, so it
-- stays put — that is precisely why JA4 exists.
--
-- Keying on (ja3, ja4) fragmented one Chrome build into one row per
-- connection. Measured on the live corpus before this change: 162 observations
-- of tmx.bestbuy.com produced 162 distinct JA3 and 2 distinct JA4, and three
-- of those JA3s differed only in extension ORDER — same set, same ciphers,
-- same curves, same point formats.
--
-- So JA3 is not an identity here. It is demoted to `fingerprint_ja3`, where
-- the multiplicity is itself the signal: many JA3s under one JA4 means the
-- client permutes its own hello; exactly one over high volume means a
-- deterministic stack. That second case is the interesting one — curl-impersonate
-- and uTLS reproduce Chrome's JA4 faithfully but do NOT implement permutation,
-- so a stable JA3 under a Chrome-shaped JA4 is a tool wearing a browser's coat.
--
-- Idempotent: safe to re-run on every deploy.

-- ── fingerprints ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fingerprints (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    ja4             VARCHAR(64)  NOT NULL UNIQUE,
    ja4_r           TEXT         NOT NULL,

    -- Populated ONLY while exactly one JA3 has been seen. A "representative"
    -- JA3 for a permuting client is a lie with a copy button next to it: paste
    -- it into a matcher and it never fires again. NULL is the honest value,
    -- and its absence is itself informative.
    ja3             CHAR(32),
    ja3_raw         TEXT,

    -- How many distinct JA3s this JA4 has produced, and whether we stopped
    -- counting. The known-variant set is capped (see fingerprint_ja3), so past
    -- the cap `ja3_variants` is a floor, not a total.
    ja3_variants        INTEGER  NOT NULL DEFAULT 0,
    ja3_variants_capped BOOLEAN  NOT NULL DEFAULT false,

    -- Connections that presented a JA3 not already in the known set.
    ja3_novel       BIGINT       NOT NULL DEFAULT 0,

    -- Does this client randomise its own fingerprint? Deliberately NOT
    -- (variants-1)/(observations-1): that ratio decays toward 0 once the
    -- variant table saturates, so a very high-volume Chrome would read as
    -- "fixed" — backwards. Because the known set is capped and then frozen, a
    -- permuting client keeps missing it and stays pinned near 1.0, while a
    -- deterministic one registers a single novel sighting and decays to 0.
    ja3_novelty     REAL GENERATED ALWAYS AS (
        CASE WHEN observations > 0
             THEN LEAST(ja3_novel::real / observations::real, 1.0)
             ELSE 0 END
    ) STORED,

    -- Decoded ClientHello, kept so the detail page needs no re-parse.
    -- `extensions` is stored SORTED: under one JA4 the wire order varies by
    -- construction, so storing whichever arrived first would present one
    -- random permutation as though it were the client's true order.
    tls_version     INTEGER      NOT NULL,
    alpn            TEXT[]       NOT NULL DEFAULT '{}',
    ciphers         INTEGER[]    NOT NULL DEFAULT '{}',
    extensions      INTEGER[]    NOT NULL DEFAULT '{}',
    curves          INTEGER[]    NOT NULL DEFAULT '{}',
    sig_algs        INTEGER[]    NOT NULL DEFAULT '{}',
    point_formats   INTEGER[]    NOT NULL DEFAULT '{}',

    observations    BIGINT       NOT NULL DEFAULT 0,

    -- Materialised after each ingest batch so browse and sort are index scans
    -- rather than an entropy calculation over every observation.
    unique_snis     INTEGER      NOT NULL DEFAULT 0,
    spread          REAL         NOT NULL DEFAULT 0,

    first_seen      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- The JA3s observed under a JA4, bounded.
--
-- No first_seen/last_seen here on purpose. For a permuting client every row
-- has observations = 1, so a timestamp would be the wall-clock moment of ONE
-- connection at microsecond precision — a per-connection record, which is
-- exactly what this corpus refuses to keep.
CREATE TABLE IF NOT EXISTS fingerprint_ja3 (
    fingerprint_id  BIGINT       NOT NULL
                    REFERENCES fingerprints(id) ON DELETE CASCADE,
    ja3             CHAR(32)     NOT NULL,
    ja3_raw         TEXT         NOT NULL,
    -- The wire order this variant arrived in. Comparing it against the parent's
    -- sorted list is what distinguishes "permutes extension order" from
    -- "varies by curves or legacy version" — different causes, different
    -- clients.
    extensions      INTEGER[]    NOT NULL DEFAULT '{}',
    observations    BIGINT       NOT NULL DEFAULT 0,

    PRIMARY KEY (fingerprint_id, ja3)
);

-- ── observations ─────────────────────────────────────────────────────────

-- One row per (fingerprint, domain). `count` is what makes a reputation: a
-- fingerprint with 4 rows is somebody's browser, one with 900 spread evenly is
-- a tool pointed at target after target.
CREATE TABLE IF NOT EXISTS observations (
    fingerprint_id  BIGINT       NOT NULL
                    REFERENCES fingerprints(id) ON DELETE CASCADE,
    sni             TEXT         NOT NULL,
    count           BIGINT       NOT NULL DEFAULT 0,
    first_seen      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ  NOT NULL DEFAULT now(),

    PRIMARY KEY (fingerprint_id, sni)
);

-- ── domains ──────────────────────────────────────────────────────────────

-- The mirror of `fingerprints`, keyed the other way. `unique_fingerprints`
-- counts distinct JA4s — under the old (ja3, ja4) keying it counted
-- fragments, which inflated it by two orders of magnitude on any domain with
-- browser traffic and pinned `spread` to 1.000 there.
CREATE TABLE IF NOT EXISTS snis (
    sni                 TEXT         PRIMARY KEY,
    observations        BIGINT       NOT NULL DEFAULT 0,
    unique_fingerprints INTEGER      NOT NULL DEFAULT 0,
    spread              REAL         NOT NULL DEFAULT 0,
    first_seen          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen           TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ── indexes ──────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_fingerprints_ja3    ON fingerprints (ja3)
    WHERE ja3 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fingerprints_obs    ON fingerprints (observations DESC);
CREATE INDEX IF NOT EXISTS idx_fingerprints_uniq   ON fingerprints (unique_snis DESC);
CREATE INDEX IF NOT EXISTS idx_fingerprints_spread ON fingerprints (spread DESC);
CREATE INDEX IF NOT EXISTS idx_fingerprints_seen   ON fingerprints (last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_fingerprints_rand   ON fingerprints (ja3_novelty DESC);

-- Resolving a public /api/v1/ja3/{md5} lookup to its JA4.
CREATE INDEX IF NOT EXISTS idx_fp_ja3_hash ON fingerprint_ja3 (ja3);

CREATE INDEX IF NOT EXISTS idx_observations_sni ON observations (sni);

CREATE INDEX IF NOT EXISTS idx_snis_obs    ON snis (observations DESC);
CREATE INDEX IF NOT EXISTS idx_snis_uniq   ON snis (unique_fingerprints DESC);
CREATE INDEX IF NOT EXISTS idx_snis_spread ON snis (spread DESC);

-- ── storage tuning ───────────────────────────────────────────────────────

-- `observations` is written far more than it is read, and every write is a
-- counter UPDATE. Postgres writes a new tuple version per update, so leave
-- page headroom for heap-only updates and vacuum earlier than the stock 20%.
--
-- There is deliberately NO index on (fingerprint_id, count): it would index
-- the one column every ingest writes, which took heap-only updates to 0% and
-- grew the table 45% over 3M updates. The primary key already leads with
-- fingerprint_id, so top-N-per-fingerprint is a range scan plus a small sort.
ALTER TABLE observations SET (fillfactor = 80);
ALTER TABLE observations SET (
    autovacuum_vacuum_scale_factor  = 0.02,
    autovacuum_vacuum_threshold     = 1000,
    autovacuum_analyze_scale_factor = 0.05,
    autovacuum_vacuum_cost_delay    = 2
);

-- Same reasoning: variant rows are counter-updated on every repeat sighting.
ALTER TABLE fingerprint_ja3 SET (fillfactor = 85);
