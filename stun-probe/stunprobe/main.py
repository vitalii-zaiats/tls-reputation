"""Entrypoint — serves the /init and /consume API and the STUN listeners in one
asyncio process (uvicorn), so the HTTP side and the UDP side share session state.
"""
from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "stunprobe.app:app",
        host=os.getenv("STUNPROBE_HTTP_HOST", "0.0.0.0"),
        port=int(os.getenv("STUNPROBE_HTTP_PORT", "8100")),
        log_level=os.getenv("STUNPROBE_LOG_LEVEL", "info"),
        access_log=False,
    )


if __name__ == "__main__":
    main()
