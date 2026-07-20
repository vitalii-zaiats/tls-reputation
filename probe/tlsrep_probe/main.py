"""Entrypoint for the reputation probe server.

Terminates TLS for probe.tls-reputation.com, peeks each connecting client's
ClientHello, and answers with what the reputation API makes of it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import ssl

from .server import ProbeServer

log = logging.getLogger("tlsrep_probe")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="tlsrep-probe",
        description="TLS server that answers with the reputation of the caller's ClientHello.",
    )
    p.add_argument("--host", default=os.getenv("TLSREP_PROBE_HOST", "::"))
    p.add_argument(
        "--port", type=int, default=int(os.getenv("TLSREP_PROBE_PORT", "8443"))
    )
    p.add_argument("--cert", default=os.getenv("TLSREP_PROBE_CERT", ""))
    p.add_argument("--key", default=os.getenv("TLSREP_PROBE_KEY", ""))
    p.add_argument(
        "--reputation-url",
        default=os.getenv(
            "TLSREP_REPUTATION_URL", "http://localhost:8000/api/v1/reputation"
        ),
    )
    p.add_argument("--log-level", default=os.getenv("TLSREP_LOG_LEVEL", "INFO"))
    return p.parse_args()


def build_ssl(cert: str, key: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    # Offer h2 and http/1.1 like an ordinary server would, so a browser probing
    # us negotiates as it normally does; we answer HTTP/1.1 regardless.
    with _suppress():
        ctx.set_alpn_protocols(["http/1.1"])
    return ctx


async def run(args: argparse.Namespace) -> None:
    ssl_ctx = build_ssl(args.cert, args.key)
    server = ProbeServer(args.reputation_url, ssl_ctx)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    serving = asyncio.create_task(server.serve(args.host, args.port))
    log.info("reputation target: %s", args.reputation_url)
    await stop.wait()
    serving.cancel()
    with _suppress():
        await serving


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not args.cert or not args.key:
        raise SystemExit("--cert and --key (or TLSREP_PROBE_CERT/KEY) are required")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


class _suppress:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc) -> bool:
        return True


if __name__ == "__main__":
    main()
