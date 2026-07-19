"""Runtime configuration, all from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _csv(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    dsn: str = os.getenv(
        "TLSREP_DSN", "postgresql://tlsrep:tlsrep@localhost:5432/tlsrep"
    )
    # Shared secret the ingest proxies present. Empty disables the write path
    # entirely, which is the correct default for a read-only public deploy.
    ingest_key: str = os.getenv("TLSREP_INGEST_KEY", "")
    cors_origins: list[str] = field(
        default_factory=lambda: _csv("TLSREP_CORS_ORIGINS", "*")
    )
    pool_min: int = int(os.getenv("TLSREP_POOL_MIN", "2"))
    pool_max: int = int(os.getenv("TLSREP_POOL_MAX", "16"))
    # Cap on rows returned by any list endpoint.
    max_limit: int = int(os.getenv("TLSREP_MAX_LIMIT", "500"))
    # How many SNIs the fingerprint detail response embeds.
    top_snis: int = int(os.getenv("TLSREP_TOP_SNIS", "50"))


settings = Settings()
