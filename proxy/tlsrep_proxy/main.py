"""Entrypoint for the collector proxy."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal

from .proxy import ProxyServer
from .sink import IngestSink

log = logging.getLogger("tlsrep_proxy")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tlsrep-proxy",
        description="HTTP CONNECT proxy that reports observed TLS ClientHellos.",
    )
    parser.add_argument("--host", default=os.getenv("TLSREP_LISTEN_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("TLSREP_LISTEN_PORT", "24761"))
    )
    parser.add_argument(
        "--ingest-url",
        default=os.getenv("TLSREP_INGEST_URL", "http://localhost:8000/internal/v1/ingest"),
    )
    parser.add_argument("--ingest-key", default=os.getenv("TLSREP_INGEST_KEY", ""))
    parser.add_argument(
        "--batch-size", type=int, default=int(os.getenv("TLSREP_BATCH_SIZE", "200"))
    )
    parser.add_argument(
        "--flush-interval",
        type=float,
        default=float(os.getenv("TLSREP_FLUSH_INTERVAL", "10")),
    )
    parser.add_argument("--log-level", default=os.getenv("TLSREP_LOG_LEVEL", "INFO"))
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    sink = IngestSink(
        url=args.ingest_url,
        key=args.ingest_key,
        batch_size=args.batch_size,
        flush_interval=args.flush_interval,
    )
    await sink.start()

    server = await asyncio.start_server(
        ProxyServer(sink).handle_client, args.host, args.port
    )
    for socket_ in server.sockets or ():
        log.info("listening on %s", socket_.getsockname())
    log.info("shipping observations to %s", args.ingest_url)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async with server:
        await stop.wait()

    log.info("draining ingest queue")
    await sink.stop()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not args.ingest_key:
        log.warning("no ingest key set — the API will reject every batch")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
