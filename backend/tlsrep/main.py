"""tls-reputation API.

Public reads under /api/v1, internal writes under /internal/v1.
"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db
from .config import settings
from .routers import internal, public

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

DESCRIPTION = """
A free, open reputation database for TLS client fingerprints.

Look up a **JA3** or **JA4** fingerprint and see which domains it has been
observed reaching, and how often. Or go the other way: give a domain, get the
fingerprints that connect to it.

The signal is not what a fingerprint *looks* like — it's how widely it roams.
A real browser's fingerprint touches the handful of domains its human visits.
Some fingerprints reach for hundreds of unrelated domains in a row: a bank, a
sneaker drop, a social API, an airline. Nobody browses like that. The `spread`
score measures exactly that, as normalised entropy from 0 to 1.

**No key, no signup, no rate limit beyond fair use.** The data is CC BY 4.0.

### Privacy

The corpus stores a fingerprint, a domain, and a counter. It has never stored
a client IP address, so there is nothing here that links a person to a browsing
history — and no lookup that could reveal one.

### Fingerprints

JA3 (Salesforce) and JA4 (FoxIO) are both BSD-3-Clause. The rest of the JA4+
suite is under a licence restricting commercial use and is not implemented.
""".strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await db.apply_schema()
    yield
    await db.disconnect()


app = FastAPI(
    title="tls-reputation",
    description=DESCRIPTION,
    version="0.1.0",
    license_info={"name": "Apache-2.0"},
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.middleware("http")
async def guard_internal_routes(request: Request, call_next):
    """Reject unauthenticated writes before the body is read.

    The route handler checks the key too, but by the time a handler runs
    FastAPI has already deserialised the request body — so an unauthenticated
    caller could make the server parse a 5000-element batch before being told
    no. Checking here costs an attacker a header comparison instead.
    """
    if request.url.path.startswith("/internal/"):
        if not settings.ingest_key:
            return JSONResponse(
                {"detail": "ingest disabled: no key configured"}, status_code=503
            )
        if not secrets.compare_digest(
            request.headers.get("X-Ingest-Key", ""), settings.ingest_key
        ):
            return JSONResponse({"detail": "bad ingest key"}, status_code=401)
    return await call_next(request)


app.include_router(public.router)
app.include_router(internal.router)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    async with db.pool().acquire() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}
