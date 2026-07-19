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


# A browser's ALPN offer. A bare-ja4_b (cipher-list) match is trusted only when
# the hello also advertises these: Chrome and Firefox both offer h2 then
# http/1.1, optionally behind h3. A client that copied the cipher list but
# offers only http/1.1, only h2, or no ALPN is NOT the browser — impersonation
# tools and libraries reuse Chrome's ciphers without its ALPN. And JA4's ja4_a
# cannot tell "h2" alone from "h2, http/1.1" (it encodes only the first
# protocol), so the full ALPN list, not the JA4, is what settles it.
_BROWSER_ALPN = frozenset(
    {
        ("h2", "http/1.1"),
        ("h3", "h2", "http/1.1"),
    }
)


def known_client(ja4: str | None, alpn: list[str] | None = None) -> dict | None:
    """Return {name, env} for a known JA4, or None. `label` is the two joined.

    Two kinds of catalog key:

      a_b_c  a full JA4, exact — a library, whose whole hello (ja4_c included)
             is stable, so the exact string is the identity.
      b      a bare cipher-list hash (12 hex, no 't', no '_') — a browser's
             cipher list, its most stable signature. It matches any JA4 with
             that ja4_b, since a browser permutes extensions (varying ja4_a and
             ja4_c) but not its ciphers. BUT the cipher list alone is not proof:
             it is trusted only when `alpn` is a browser's (see _BROWSER_ALPN),
             because impersonation tools copy the ciphers and not the ALPN.
             Pass the fingerprint's ALPN or the browser match is skipped.
    """
    if not ja4:
        return None
    entry = _CATALOG.get(ja4)
    if entry is None:
        parts = ja4.split("_")
        # Bare ja4_b = a browser cipher-list signature, gated on a browser ALPN.
        if len(parts) == 3 and alpn is not None and tuple(alpn) in _BROWSER_ALPN:
            entry = _CATALOG.get(parts[1])
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
