"""HTTP CONNECT proxy that observes TLS ClientHellos in passing.

Ported from the LayerID intel-service proxy, stripped of gRPC and of every
field that identified a client. This version records exactly one thing: the
ClientHello bytes. Not the peer address, not the resolved IP, not byte counts,
not durations. Those were useful for the internal pipeline and are precisely
what must not exist in a public corpus.

The proxy is otherwise a faithful, transparent tunnel — it forwards the bytes
it peeked, so observing costs the client nothing.
"""

from __future__ import annotations

import asyncio
import logging
import re
import struct

log = logging.getLogger(__name__)

_HTTP_REQUEST_RE = re.compile(r"^[A-Z]{3,10} \S+ HTTP/\d\.\d\r?\n?$")

_TLS_HANDSHAKE = 0x16

# Ports where the server speaks first — peeking would deadlock the connection.
_SERVER_FIRST_PORTS = frozenset({21, 22, 23, 25, 110, 143, 220, 993, 995})


class ProxyServer:
    def __init__(self, sink, connect_timeout: float = 10.0) -> None:
        self._sink = sink
        self._connect_timeout = connect_timeout

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await self._dispatch(reader, writer)
        except Exception:
            log.exception("connection handler error")
        finally:
            with_suppressed(writer.close)

    async def _dispatch(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
        except TimeoutError:
            return
        if not request_line or not self._is_http_request_line(request_line):
            return

        await self._read_headers(reader)

        parts = request_line.decode("ascii").strip().split()
        if len(parts) < 3:
            writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await writer.drain()
            return

        if parts[0] != "CONNECT":
            # This proxy exists to watch TLS handshakes. Plaintext HTTP has no
            # ClientHello, so there is nothing here worth relaying.
            writer.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            await writer.drain()
            return

        host, port = self._parse_connect_target(parts[1])
        await self._handle_connect(reader, writer, host, port)

    async def _handle_connect(
        self,
        client_r: asyncio.StreamReader,
        client_w: asyncio.StreamWriter,
        host: str,
        port: int,
    ) -> None:
        try:
            remote_r, remote_w = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=self._connect_timeout
            )
        except (OSError, TimeoutError) as exc:
            log.warning("connect failed %s:%d -> %s", host, port, exc)
            client_w.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            with_suppressed(client_w.drain)
            return

        client_w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_w.drain()

        if port not in _SERVER_FIRST_PORTS:
            first_bytes = await self._peek_client_hello(client_r)
            if not first_bytes:
                remote_w.close()
                return

            if first_bytes[0] == _TLS_HANDSHAKE:
                self._sink.submit(first_bytes)

            remote_w.write(first_bytes)
            await remote_w.drain()

        await asyncio.gather(
            self._pipe(client_r, remote_w),
            self._pipe(remote_r, client_w),
        )

    @staticmethod
    async def _peek_client_hello(reader: asyncio.StreamReader) -> bytes:
        """Read enough to hold a complete first TLS record.

        Returns whatever arrived — the caller forwards it verbatim either way,
        so a non-TLS or truncated read costs the connection nothing.
        """
        buffer = bytearray()
        try:
            chunk = await asyncio.wait_for(reader.read(16384), timeout=5.0)
            if not chunk:
                return b""
            buffer.extend(chunk)

            if buffer[0] == _TLS_HANDSHAKE and len(buffer) >= 5:
                needed = 5 + struct.unpack("!H", buffer[3:5])[0]
                while len(buffer) < needed:
                    chunk = await asyncio.wait_for(
                        reader.read(needed - len(buffer)), timeout=2.0
                    )
                    if not chunk:
                        break
                    buffer.extend(chunk)
        except (TimeoutError, OSError):
            pass
        return bytes(buffer)

    @staticmethod
    async def _pipe(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (OSError, ConnectionError):
            pass
        finally:
            with_suppressed(writer.close)

    @staticmethod
    async def _read_headers(reader: asyncio.StreamReader) -> dict[str, str]:
        headers: dict[str, str] = {}
        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            except TimeoutError:
                break
            if not line or line == b"\r\n":
                break
            try:
                decoded = line.decode("ascii").strip()
            except UnicodeDecodeError:
                break
            if ":" in decoded:
                key, value = decoded.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        return headers

    @staticmethod
    def _is_http_request_line(data: bytes) -> bool:
        try:
            text = data.decode("ascii")
        except (UnicodeDecodeError, ValueError):
            return False
        return bool(_HTTP_REQUEST_RE.match(text.strip() + "\n"))

    @staticmethod
    def _parse_connect_target(target: str) -> tuple[str, int]:
        if ":" in target:
            host, _, port = target.rpartition(":")
            try:
                return host, int(port)
            except ValueError:
                return target, 443
        return target, 443


def with_suppressed(fn) -> None:
    """Run a teardown call, ignoring the errors teardown always produces."""
    try:
        result = fn()
        if asyncio.iscoroutine(result):
            asyncio.ensure_future(result)
    except (OSError, ConnectionError, RuntimeError):
        pass
