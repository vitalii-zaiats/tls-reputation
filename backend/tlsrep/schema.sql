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

-- Top-SNI-per-fingerprint, the hottest query on the site.
CREATE INDEX IF NOT EXISTS idx_observations_fp_count
    ON observations (fingerprint_id, count DESC);
