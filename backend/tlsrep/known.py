"""Known-fingerprint catalog.

A curated map JA4 -> named client, built by the ground-truth matrix in
tools/fingerprint-matrix (each library in each base image, fingerprinted and
cross-checked). It turns an anonymous JA4 in the corpus into a name: "Python
requests on Alpine," "Amazon Linux 2 — TLS 1.2 only." Loaded once at import;
lookups are a dict hit.

This is deliberately a static, version-controlled file, not a table: the
labels are editorial (they name a build, not just a hash), and they should
change by review, in the repo, not by ingest.
"""

from __future__ import annotations

import json
from pathlib import Path

_PATH = Path(__file__).with_name("known_fingerprints.json")


def _load() -> dict[str, dict]:
    raw = json.loads(_PATH.read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


_CATALOG = _load()


def known_client(ja4: str | None) -> dict | None:
    """Return {name, env} for a known JA4, or None. `label` is the two joined."""
    if not ja4:
        return None
    entry = _CATALOG.get(ja4)
    if entry is None:
        return None
    name, env = entry["name"], entry.get("env", "")
    return {
        "name": name,
        "env": env,
        "label": f"{name} · {env}" if env else name,
    }


def catalog_size() -> int:
    return len(_CATALOG)
