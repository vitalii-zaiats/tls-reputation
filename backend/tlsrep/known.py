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


def _alpn_ok(entry: dict, alpn: list[str] | None) -> bool:
    """Whether a bare-ja4_b entry accepts this fingerprint's ALPN.

    A cipher-list match is only as trustworthy as the client it points to. A
    browser's cipher list is that browser ONLY when the hello also offers a
    browser ALPN (h2 then http/1.1, optionally behind h3) — impersonation tools
    copy Chrome's ciphers but not its ALPN, and JA4's ja4_a can't tell "h2"
    alone from "h2, http/1.1", so the full ALPN list is what settles it. A
    browser entry carries that requirement in its own `alpn` list.

    An entry with no `alpn` list matches any ALPN — right for a platform like
    Android's Conscrypt, whose native apps legitimately offer every ALPN.
    """
    req = entry.get("alpn")
    if req is None:
        return True
    return alpn is not None and list(alpn) in req


def known_client(ja4: str | None, alpn: list[str] | None = None) -> dict | None:
    """Return {name, env} for a known JA4, or None. `label` is the two joined.

    Two kinds of catalog key:

      a_b_c  a full JA4, exact — a library, whose whole hello (ja4_c included)
             is stable, so the exact string is the identity.
      b      a bare cipher-list hash (12 hex, no 't', no '_') — a cipher list
             that is a client's signature: a browser (Chrome, Firefox) or a
             platform (Android Conscrypt / Flutter's mobile BoringSSL). It
             matches any JA4 with that ja4_b, since the client permutes
             extensions (varying ja4_a and ja4_c) but not its ciphers. A browser
             entry adds an `alpn` guard (see _alpn_ok); a platform entry does
             not. Exact wins over bare.
    """
    if not ja4:
        return None
    entry = _CATALOG.get(ja4)
    if entry is None:
        parts = ja4.split("_")
        if len(parts) == 3:
            cand = _CATALOG.get(parts[1])
            if cand is not None and _alpn_ok(cand, alpn):
                entry = cand
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
