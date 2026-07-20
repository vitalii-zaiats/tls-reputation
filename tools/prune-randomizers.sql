-- Prune cipher-randomizer noise.
--
-- A bot that randomizes its ClientHello cipher suites every connection mints a
-- fresh JA4 each time, so it manufactures hundreds of one-off fingerprints that
-- carry no signal and poison the "unseen fingerprint = suspicious" heuristic.
-- The tell is the INVARIANT it forgets to randomize: one ja4_c (extensions +
-- sigalgs) shared by a whole spray of distinct ja4_b (cipher lists).
--
-- This removes the Moutai scalping bot's spray (ja4_c fb48f8b98a29 — 734
-- fingerprints across 733 cipher lists, ~2.9k obs, one target, reversed ALPN,
-- no legitimate anchor). It runs in one transaction and repairs the aggregate
-- counts on every SNI those fingerprints touched, deleting any SNI that is left
-- with no observations of its own. Verified read-only before writing.
--
-- Run:  psql "$DSN" -v ON_ERROR_STOP=1 -f tools/prune-randomizers.sql

\set inv 'fb48f8b98a29'

\echo === before ===
SELECT (SELECT count(*) FROM fingerprints) AS fingerprints,
       (SELECT count(*) FROM snis)         AS snis;

BEGIN;

-- The SNIs these fingerprints reach, captured before the cascade removes the
-- observation rows, so their aggregates can be rebuilt from what remains.
CREATE TEMP TABLE aff AS
  SELECT DISTINCT o.sni
  FROM observations o
  JOIN fingerprints f ON f.id = o.fingerprint_id
  WHERE split_part(f.ja4, '_', 3) = :'inv';

-- ON DELETE CASCADE on observations + fingerprint_ja3 clears the child rows.
DELETE FROM fingerprints WHERE split_part(ja4, '_', 3) = :'inv';

-- Rebuild the denormalised per-SNI counts (not FK-maintained) from the survivors.
UPDATE snis s
SET observations        = COALESCE(a.obs, 0),
    unique_fingerprints = COALESCE(a.uf, 0)
FROM (
  SELECT sni, sum(count) AS obs, count(DISTINCT fingerprint_id) AS uf
  FROM observations
  WHERE sni IN (SELECT sni FROM aff)
  GROUP BY sni
) a
WHERE s.sni = a.sni;

-- Drop SNIs whose only traffic was this bot.
DELETE FROM snis
WHERE sni IN (SELECT sni FROM aff)
  AND sni NOT IN (SELECT sni FROM observations);

COMMIT;

\echo === after ===
SELECT (SELECT count(*) FROM fingerprints) AS fingerprints,
       (SELECT count(*) FROM snis)         AS snis;
