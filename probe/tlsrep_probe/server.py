"""Reputation probe server.

A client connects over TLS; before the handshake is answered, the server peeks
the raw ClientHello off the socket with MSG_PEEK — reading it without consuming
it, so the bytes are still there for the real handshake that follows. Then it
terminates TLS, base64-encodes the peeked ClientHello, asks the reputation API
what it is, and writes the answer back over the now-established connection.

The peek is the whole trick. Python's ssl layer will not hand you the raw
ClientHello, and once the handshake has read it the bytes are gone. MSG_PEEK
leaves them in the kernel buffer, so the same record feeds both our fingerprint
engine and OpenSSL's handshake — one connection, no proxy, no reflection.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import socket
import ssl
import urllib.error
import urllib.request

log = logging.getLogger("tlsrep_probe")

_TLS_HANDSHAKE = 0x16
_RECORD_HEADER = 5
# A ClientHello lives in one or two TLS records; 32 KiB is well past any real
# one and caps how long we will sit peeking at a slow or hostile sender.
_MAX_HELLO = 32768


class ProbeServer:
    def __init__(
        self,
        reputation_url: str,
        ssl_context: ssl.SSLContext,
        *,
        peek_timeout: float = 5.0,
        request_timeout: float = 10.0,
        reputation_timeout: float = 10.0,
    ) -> None:
        self._url = reputation_url
        self._ssl = ssl_context
        self._peek_timeout = peek_timeout
        self._request_timeout = request_timeout
        self._reputation_timeout = reputation_timeout

    async def serve(self, host: str, port: int) -> None:
        loop = asyncio.get_running_loop()
        lsock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Dual-stack: one listener for v4 and v6.
        with _suppress():
            lsock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        lsock.bind((host, port))
        lsock.listen(256)
        lsock.setblocking(False)
        log.info("probe listening on [%s]:%d", host, port)
        try:
            while True:
                conn, addr = await loop.sock_accept(lsock)
                conn.setblocking(False)
                loop.create_task(self._guarded(conn, addr))
        finally:
            lsock.close()

    async def _guarded(self, conn: socket.socket, addr) -> None:
        try:
            await self._handle(conn, addr)
        except (OSError, ssl.SSLError, asyncio.TimeoutError) as exc:
            log.debug("connection from %s ended: %s", addr, exc)
        except Exception:  # noqa: BLE001 — one bad connection must not kill the loop
            log.exception("unexpected error handling %s", addr)

    async def _handle(self, conn: socket.socket, addr) -> None:
        loop = asyncio.get_running_loop()

        # 1) Peek the ClientHello without consuming it.
        hello = await asyncio.wait_for(
            self._peek_hello(conn, loop), timeout=self._peek_timeout
        )
        if not hello or hello[0] != _TLS_HANDSHAKE:
            conn.close()
            return

        # 2) Terminate TLS on the same socket. The peeked bytes are still in the
        #    kernel buffer, so OpenSSL reads the very ClientHello we just parsed.
        reader = asyncio.StreamReader(limit=2**16, loop=loop)
        protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
        transport, _ = await loop.connect_accepted_socket(
            lambda: protocol, conn, ssl=self._ssl, ssl_handshake_timeout=10.0
        )
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)

        try:
            # 3) Read (and discard) the HTTP request line + headers.
            await asyncio.wait_for(
                _drain_request(reader), timeout=self._request_timeout
            )

            # 4) Ask the reputation API about the ClientHello we peeked.
            body, status = await self._reputation(loop, hello)

            # 5) Answer.
            writer.write(_http_response(status, body))
            await writer.drain()
        finally:
            with _suppress():
                writer.close()
                await writer.wait_closed()

    async def _peek_hello(
        self, conn: socket.socket, loop: asyncio.AbstractEventLoop
    ) -> bytes:
        """MSG_PEEK until a whole first TLS record is buffered, or give up.

        Peeking is idempotent: each call returns everything the kernel holds
        from offset zero, so we re-peek as more arrives until the 5-byte record
        header's length field is satisfied.
        """
        while True:
            try:
                data = conn.recv(_MAX_HELLO, socket.MSG_PEEK)
            except (BlockingIOError, InterruptedError):
                await _wait_readable(conn, loop)
                continue
            if not data:
                return b""
            if data[0] != _TLS_HANDSHAKE:
                return data  # not TLS — caller drops it
            if len(data) >= _RECORD_HEADER:
                needed = _RECORD_HEADER + int.from_bytes(data[3:5], "big")
                if len(data) >= needed or len(data) >= _MAX_HELLO:
                    return data[:needed]
            await _wait_readable(conn, loop)

    async def _reputation(
        self, loop: asyncio.AbstractEventLoop, hello: bytes
    ) -> tuple[bytes, int]:
        b64 = base64.b64encode(hello).decode("ascii")
        try:
            return await loop.run_in_executor(None, self._post, b64)
        except Exception:  # noqa: BLE001
            log.exception("reputation call failed")
            return (
                json.dumps({"error": "reputation lookup unavailable"}).encode(),
                502,
            )

    def _post(self, b64: str) -> tuple[bytes, int]:
        payload = json.dumps({"client_hello": b64}).encode()
        req = urllib.request.Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._reputation_timeout) as resp:
                return resp.read(), resp.status
        except urllib.error.HTTPError as exc:
            return exc.read(), exc.code


async def _drain_request(reader: asyncio.StreamReader) -> None:
    """Read the HTTP request line and headers, discarding them. We answer the
    same way whatever the path — the fingerprint is the request."""
    first = await reader.readline()
    if not first:
        return
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            return


def _http_response(status: int, body: bytes) -> bytes:
    reason = {200: "OK", 400: "Bad Request", 422: "Unprocessable Entity",
              502: "Bad Gateway"}.get(status, "OK")
    headers = (
        f"HTTP/1.1 {status} {reason}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "\r\n"
    ).encode()
    return headers + body


async def _wait_readable(conn: socket.socket, loop: asyncio.AbstractEventLoop) -> None:
    fut = loop.create_future()
    loop.add_reader(conn.fileno(), fut.set_result, None)
    try:
        await fut
    finally:
        loop.remove_reader(conn.fileno())


class _suppress:
    """Tiny stdlib-free contextlib.suppress(Exception)."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc) -> bool:
        return True
