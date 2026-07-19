"""Batching sink — buffers ClientHellos and POSTs them to the ingest API.

The wire format is deliberately trivial:

    {"data": ["<base64 ClientHello>", ...]}

The proxy computes nothing. It ships bytes. Fingerprint definitions change
(JA4 is younger than JA3, and something will follow it); exit nodes on other
people's hardware are the last thing you want to redeploy when that happens.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


class IngestSink:
    def __init__(
        self,
        url: str,
        key: str,
        batch_size: int = 200,
        flush_interval: float = 10.0,
        max_queue: int = 10000,
        timeout: float = 15.0,
    ) -> None:
        self._url = url
        self._key = key
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._timeout = timeout
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max_queue)
        self._task: asyncio.Task | None = None
        self._dropped = 0

    def submit(self, client_hello: bytes) -> None:
        """Queue a ClientHello. Never blocks and never raises.

        A stalled ingest endpoint must not stall the proxy — we are sitting in
        the path of somebody's real connection. If the queue is full we drop
        the observation and count it.
        """
        try:
            self._queue.put_nowait(base64.b64encode(client_hello).decode("ascii"))
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped % 100 == 1:
                log.warning("ingest queue full, dropped %d observations", self._dropped)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        await self._flush(self._drain())

    def _drain(self) -> list[str]:
        items: list[str] = []
        while not self._queue.empty() and len(items) < self._batch_size:
            items.append(self._queue.get_nowait())
        return items

    async def _run(self) -> None:
        while True:
            batch: list[str] = []
            deadline = asyncio.get_running_loop().time() + self._flush_interval

            while len(batch) < self._batch_size:
                timeout = deadline - asyncio.get_running_loop().time()
                if timeout <= 0:
                    break
                try:
                    batch.append(
                        await asyncio.wait_for(self._queue.get(), timeout=timeout)
                    )
                except TimeoutError:
                    break

            if batch:
                await self._flush(batch)

    async def _flush(self, batch: list[str]) -> None:
        if not batch:
            return
        try:
            result = await asyncio.to_thread(self._post, batch)
            log.info("ingest: sent %d, accepted %s", len(batch), result.get("accepted"))
        except Exception as exc:
            # Deliberately not requeued: on a sustained outage retrying would
            # grow the queue until it evicts live traffic. Observations are
            # cheap and continuous; connections are not.
            log.warning("ingest failed, dropping %d observations: %s", len(batch), exc)

    def _post(self, batch: list[str]) -> dict:
        payload = json.dumps({"data": batch}).encode()
        request = urllib.request.Request(
            self._url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Ingest-Key": self._key,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.loads(response.read() or b"{}")
