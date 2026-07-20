-- Drop every fingerprint whose ONLY observed SNI is :sni.
--
-- A single-target spray — a bot randomizing its ClientHello against one
-- endpoint — leaves hundreds of one-off fingerprints that all reach just that
-- one host and nothing else. This removes them and the now-empty SNI row, in
-- one transaction. A fingerprint that also reaches any other domain is left
-- untouched, so a real client that merely visited the target survives.
--
-- Run:  psql "$DSN" -v ON_ERROR_STOP=1 -f tools/prune-sni.sql
--       (edit :sni below, or pass -v sni=host.example.com)

\if :{?sni}
\else
  \set sni 'h5.moutai519.com.cn'
\endif

\echo === target ===
\echo :sni

\echo === before ===
SELECT (SELECT count(*) FROM fingerprints) AS fingerprints,
       (SELECT count(*) FROM snis)         AS snis;

BEGIN;

-- Fingerprints reaching :sni and nothing else. ON DELETE CASCADE clears their
-- observation and ja3-variant rows.
DELETE FROM fingerprints f
WHERE EXISTS (
        SELECT 1 FROM observations o
        WHERE o.fingerprint_id = f.id AND o.sni = :'sni'
      )
  AND NOT EXISTS (
        SELECT 1 FROM observations o
        WHERE o.fingerprint_id = f.id AND o.sni <> :'sni'
      );

-- The target had only those fingerprints, so its aggregate row is now stale
-- and empty — drop it if nothing reaches it any more.
DELETE FROM snis
WHERE sni = :'sni'
  AND sni NOT IN (SELECT sni FROM observations);

COMMIT;

\echo === after ===
SELECT (SELECT count(*) FROM fingerprints) AS fingerprints,
       (SELECT count(*) FROM snis)         AS snis;
