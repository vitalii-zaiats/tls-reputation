# tls-reputation

An open reputation database for TLS client fingerprints.

Look up a **JA3** or **JA4** and see which domains that fingerprint has been
observed reaching, and how often. Or go the other way: give a domain, get the
fingerprints that connect to it.

Live at **[tls-reputation.com](https://tls-reputation.com)**. No key, no
signup, no rate limit beyond fair use.

## The idea

A single TLS handshake tells you less than you'd hope. Checking a fingerprint
against the User-Agent — "Chrome's JA3 should look like Chrome's" — works, but
there's a better question that doesn't need the User-Agent at all:

> How many times have I seen this fingerprint, and reaching for what?

That's where the tell lives. Not the *shape* of the fingerprint — its
**promiscuity**. A real browser's fingerprint touches the handful of domains
its human actually visits. Some fingerprints come through reaching for
hundreds of unrelated domains in a row: a bank, a sneaker drop, a social API,
an airline, another bank. Nobody browses like that. That spread is a tool being
pointed at one target after another, and the fingerprint is just the barrel it
fires through.

So TLS stops being a per-connection resemblance check and becomes a reputation
layer: you don't judge one handshake, you judge how lit-up it is across
everything the corpus has watched it do.

### The spread score

Every fingerprint carries a `spread` between 0 and 1 — the normalised Shannon
entropy of its SNI distribution.

| spread | shape | reading |
|---|---|---|
| 0.0 | one domain, always | a bot pointed at a single target, or a pinned client |
| ~0.3–0.7 | a few domains, unevenly | what a person's browser looks like |
| ~1.0 | many domains, evenly | tooling sweeping targets |

Normalising by `ln(n)` is the part that matters: without it the score would
just re-measure how many domains a fingerprint touched. With it, five domains
hit evenly and five hundred hit evenly both read as "evenly spread", and
`spread` stays comparable across fingerprints of wildly different volume.

Read it alongside `observations`. High spread on two connections is noise;
high spread on two hundred thousand is a tool.

### An honest caveat

A reputation layer is only as good as the baseline you measure against. This
corpus is collected from residential-proxy exit traffic, which shows you what
abusive traffic looks like — it does not tell you what a normal population's
handshakes look like. Without that second pole you are grading against a curve
drawn from one side. Treat a high spread as a reason to look closer, never as
a verdict.

## Privacy

**The corpus stores a fingerprint, a domain, and a counter. Nothing else.**

There is no client IP address in the database, and there never has been — the
collector is written so that the address is not merely discarded but never
leaves the socket. That is a deliberate design constraint, not an oversight:

- A TLS fingerprint is a property of a *software stack*, shared by millions of
  installs. It does not identify a person.
- The pair `(fingerprint, domain, count)` is an aggregate over many unrelated
  clients. It cannot be inverted into anybody's browsing history.
- Consequently there is no lookup this API could offer — now or later — that
  would reveal what a given person visited, because that information was never
  recorded.

If you are extending this, the constraint travels with the schema. Adding a
client address, a per-connection timestamp, or a raw ClientHello column would
turn an aggregate into a surveillance log.

## Components

| Directory | What it is |
|---|---|
| `backend/` | FastAPI. Public reads on `/api/v1`, internal writes on `/internal/v1`. Computes JA3/JA4 from submitted ClientHellos. Postgres. |
| `frontend/` | Vue 3 + Vite. The public site. |
| `proxy/` | HTTP CONNECT proxy that observes ClientHellos and ships them to the ingest endpoint. Standard library only. |
| `ansible/` | Deployment for all three, independently. |

### How data flows

```
   TLS client
       │  CONNECT host:443
       ▼
   proxy/            peeks the ClientHello, forwards it untouched
       │             {"data": ["<base64 ClientHello>", ...]}
       ▼
   backend/          parses, computes JA3 + JA4, folds into counters
       │
       ▼
   Postgres          fingerprints ↔ observations
       │
       ▼
   frontend/         public lookup
```

The proxy computes nothing. It ships bytes. Fingerprint definitions change —
JA4 is younger than JA3, and something will follow it — and exit nodes on
hardware you don't own are the last thing you want to redeploy when that
happens. Parsing lives in exactly one place: `backend/tlsrep/tls/`.

## Fingerprints implemented

- **JA3** (Salesforce) — BSD-3-Clause
- **JA4** (FoxIO) — BSD-3-Clause

The wider **JA4+** suite (JA4S, JA4H, JA4X, JA4T, JA4L, JA4SSH) is under the
FoxIO License 1.1, which permits academic and internal use but restricts
monetisation without an OEM licence. It is deliberately not implemented here,
so that nothing in this repository constrains what the project can become.

## Quick start

```sh
# Postgres
docker run -d --name tlsrep-pg -e POSTGRES_PASSWORD=tlsrep \
  -e POSTGRES_USER=tlsrep -e POSTGRES_DB=tlsrep -p 5432:5432 postgres:16-alpine

# Backend — applies the schema on startup
cd backend
uv sync
export TLSREP_DSN=postgresql://tlsrep:tlsrep@localhost:5432/tlsrep
export TLSREP_INGEST_KEY=dev-key
uv run uvicorn tlsrep.main:app --reload

# Collector proxy
cd proxy
uv run python -m tlsrep_proxy.main --port 24761 \
  --ingest-url http://localhost:8000/internal/v1/ingest --ingest-key dev-key

# Frontend
cd frontend && npm install && npm run dev
```

Then push a handshake through it:

```sh
curl -x http://127.0.0.1:24761 https://example.com/
curl http://localhost:8000/api/v1/snis
```

## API

Interactive docs at `/api/docs`, schema at `/api/openapi.json`.

| Endpoint | Returns |
|---|---|
| `GET /api/v1/ja3/{md5}` | fingerprint detail |
| `GET /api/v1/ja4/{ja4}` | fingerprint detail |
| `GET /api/v1/fingerprint/{ja3\|ja4}/snis` | every domain it reached, paginated |
| `GET /api/v1/sni/{domain}` | fingerprints that reached this domain |
| `GET /api/v1/fingerprints?sort=` | browse — `observations`, `unique_snis`, `spread`, `last_seen` |
| `GET /api/v1/snis` | browse domains |
| `GET /api/v1/search?q=` | detects JA3 / JA4 / domain and resolves it |
| `GET /api/v1/stats` | corpus size |

Writes require `X-Ingest-Key` and must never be exposed publicly.

## Tests

```sh
cd backend && uv run pytest
```

The fingerprint fixtures are real captures — curl, OpenSSL, and Python's `ssl`
connecting to a local socket — and their JA3 hashes were cross-checked against
an independent parser before being frozen, so a parser regression surfaces as a
changed hash rather than a silently different fingerprint.

## Licence

Apache-2.0. The corpus data is CC BY 4.0.
