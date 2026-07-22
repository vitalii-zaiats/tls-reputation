"""WebRTC forgery-probe API.

Flow:
  1. POST /init            -> { request_id, stun_host, stun_port, ttl }
     Allocates a dedicated UDP port on our STUN server and opens a listener on
     it. The browser is told to use stun:<stun_host>:<stun_port>.
  2. The browser runs WebRTC ICE gathering against that address.
  3. POST /request/<id>/consume  -> atomically returns whether a STUN request
     actually arrived on that port (and the source address we saw), then frees
     the port. Single-use.

Correlation is by PORT, not by transaction id: WebRTC generates the STUN
transaction id itself and never exposes it to JS, so a per-session port is the
only thing the page can steer a packet at that we can tie back to the session.

Verdict (the caller combines the JS view with our server-side truth):
  * JS reported an srflx candidate, but nothing arrived here  -> the candidate
    was FORGED. The browser fabricated a reflexive address it never obtained.
    That is an anti-detect browser spoofing WebRTC.
  * JS reported no srflx and nothing arrived                  -> WebRTC UDP is
    simply blocked (a privacy setting, a firewall, mDNS-only). Not deception —
    the browser isn't claiming something it doesn't have.
  * Something arrived                                         -> genuine path;
    src_ip is the real UDP exit. If it differs from the TCP exit, the UDP went
    around the proxy.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .stun import build_binding_response, is_binding_request, transaction_id

_PORT_START = int(os.getenv("STUNPROBE_PORT_START", "41000"))
_PORT_COUNT = int(os.getenv("STUNPROBE_PORT_COUNT", "200"))
_STUN_HOST = os.getenv("STUNPROBE_STUN_HOST", "")
_TTL = float(os.getenv("STUNPROBE_TTL", "8"))
_BIND = os.getenv("STUNPROBE_UDP_BIND", "0.0.0.0")
# Comma-separated origin allowlist; "*" (default) accepts any origin.
_CORS_ORIGINS = [
    o.strip() for o in os.getenv("STUNPROBE_CORS_ORIGINS", "*").split(",") if o.strip()
] or ["*"]

# The embeddable widget — a "Run the probe" button + result. Served from this
# same origin so its fetch() to /init and /consume needs no CORS at all.
_WIDGET_HTML = pathlib.Path(__file__).with_name("widget.html").read_text(encoding="utf-8")


class Session:
    __slots__ = ("rid", "port", "created", "arrived", "src_ip", "src_port",
                 "recv_at", "transport")

    def __init__(self, rid: str, port: int) -> None:
        self.rid = rid
        self.port = port
        self.created = time.monotonic()
        self.arrived = False
        self.src_ip: str | None = None
        self.src_port: int | None = None
        self.recv_at: float | None = None
        self.transport: asyncio.DatagramTransport | None = None

    def mark(self, ip: str, port: int) -> None:
        # First arrival wins — a retransmit shouldn't move the timestamp.
        if not self.arrived:
            self.arrived = True
            self.src_ip = ip
            self.src_port = port
            self.recv_at = time.monotonic()


class _StunProtocol(asyncio.DatagramProtocol):
    def __init__(self, session: Session) -> None:
        self._session = session
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:
        self._transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        if not is_binding_request(data):
            return
        self._session.mark(addr[0], addr[1])
        # Answer so a genuine client still gets its srflx candidate.
        try:
            self._transport.sendto(
                build_binding_response(transaction_id(data), addr[0], addr[1]), addr
            )
        except OSError:
            pass


class Store:
    def __init__(self) -> None:
        self._free = list(range(_PORT_START, _PORT_START + _PORT_COUNT))
        self._by_id: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create(self) -> Session:
        loop = asyncio.get_running_loop()
        async with self._lock:
            if not self._free:
                raise HTTPException(503, "no free probe ports, retry shortly")
            port = self._free.pop()
        session = Session(secrets.token_urlsafe(16), port)
        try:
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _StunProtocol(session), local_addr=(_BIND, port)
            )
        except OSError as exc:
            async with self._lock:
                self._free.append(port)
            raise HTTPException(503, "could not open probe port") from exc
        session.transport = transport
        async with self._lock:
            self._by_id[session.rid] = session
        return session

    async def consume(self, rid: str) -> Session | None:
        async with self._lock:
            session = self._by_id.pop(rid, None)
        if session is not None:
            await self._release(session)
        return session

    async def _release(self, session: Session) -> None:
        if session.transport is not None:
            session.transport.close()
        async with self._lock:
            self._free.append(session.port)

    async def reap(self) -> None:
        """Free ports whose sessions were never consumed. Grace beyond the TTL so
        a slow /consume still finds its result."""
        while True:
            await asyncio.sleep(1.0)
            now = time.monotonic()
            async with self._lock:
                dead = [
                    s for s in self._by_id.values() if now - s.created > _TTL + 5
                ]
                for s in dead:
                    self._by_id.pop(s.rid, None)
            for s in dead:
                await self._release(s)


store = Store()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    reaper = asyncio.create_task(store.reap())
    try:
        yield
    finally:
        reaper.cancel()


app = FastAPI(title="tls-reputation WebRTC probe", lifespan=_lifespan)

# The probe is always called cross-origin from the page under test, so the
# preflight for POST /init and POST /request/{id}/consume must succeed — including
# when the caller sends credentials (a session cookie in the attestation flow).
# A literal "*" origin cannot carry credentials: browsers reject
# `Access-Control-Allow-Origin: *` on a credentialed request. So for the open
# default we match any origin with a regex, which makes Starlette echo the
# caller's Origin and emit `Access-Control-Allow-Credentials`. Set
# STUNPROBE_CORS_ORIGINS to a comma-separated allowlist to lock it down.
_cors = dict(
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    max_age=600,
)
if _CORS_ORIGINS == ["*"]:
    app.add_middleware(CORSMiddleware, allow_origin_regex=".*", **_cors)
else:
    app.add_middleware(CORSMiddleware, allow_origins=_CORS_ORIGINS, **_cors)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/embed", response_class=HTMLResponse, include_in_schema=False)
async def widget() -> HTMLResponse:
    # `frame-ancestors *` so any blog can embed this in an <iframe>. (nginx must
    # not add X-Frame-Options for this vhost, or it would override this.)
    return HTMLResponse(
        _WIDGET_HTML, headers={"Content-Security-Policy": "frame-ancestors *"}
    )


@app.post("/init", summary="Allocate a probe session + STUN port")
async def init() -> dict:
    session = await store.create()
    return {
        "request_id": session.rid,
        "stun_host": _STUN_HOST,
        "stun_port": session.port,
        "ttl": _TTL,
    }


@app.post("/request/{request_id}/consume", summary="Read the result, once")
async def consume(request_id: str = Path(..., min_length=8, max_length=64)) -> dict:
    session = await store.consume(request_id)
    if session is None:
        raise HTTPException(404, "unknown or already-consumed request_id")
    waited = None
    if session.recv_at is not None:
        waited = round((session.recv_at - session.created) * 1000, 1)
    return {
        "request_id": request_id,
        # The one fact the browser cannot fake: did a STUN packet reach us?
        "arrived": session.arrived,
        "src_ip": session.src_ip,
        "src_port": session.src_port,
        # Server-side time from /init to the packet landing.
        "server_wait_ms": waited,
    }
