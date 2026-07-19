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
    """Return {name, env} for a known JA4, or None. `label` is the two joined.

    Three kinds of catalog key, tried most-specific first:

      a_b_c  a full JA4, exact — right for a library whose ja4_c is stable.
      a_b    a prefix (no third part) — matches any ja4_c, right for a browser
             that permutes its extensions so ja4_c varies while its version and
             cipher list (a_b) hold.
      b      a bare cipher-list hash (12 hex, no 't', no '_') — matches any JA4
             with that ja4_b regardless of ja4_a. A browser's cipher list is its
             most stable signature: Chrome's ja4_b is the same whether it offers
             16 or 17 extensions, but the two differ in ja4_a, so an a_b prefix
             catches only one of them. Keyed only for cipher lists distinctive
             to one client (Chrome, Firefox); libraries stay on exact keys.
    """
    if not ja4:
        return None
    entry = _CATALOG.get(ja4)
    if entry is None:
        parts = ja4.split("_")
        if len(parts) == 3:
            entry = _CATALOG.get(f"{parts[0]}_{parts[1]}") or _CATALOG.get(parts[1])
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
