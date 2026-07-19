"""Heuristic classification of a server name.

The point is one derived signal: is this domain an authentication endpoint?
Because the credential-stuffing shape is an auth endpoint reached by many
distinct client stacks — the fingerprint rotation the corpus already measures
as `unique_fingerprints` and `spread`. Crossing "auth-like domain" with "many
fingerprints" is what turns those into a brute-force candidate.

This CLASSIFIES the name; it never EXTRACTS anything from it. Pulling an
id- or username-looking substring out of an SNI and storing it would drag
personal data into the corpus — some clients really do put device names and
tokens in SNI — which is exactly what this project refuses to keep. The output
is a category, computed on read, stored nowhere.

It is deliberately high-precision and low-recall, and it is a hint, not a
verdict: an auth endpoint with a boring name (api.stripe.com handles auth) is
missed, and the name alone can never establish intent.
"""

from __future__ import annotations

import re

# Whole dot- or dash-delimited label components that mark an auth surface.
# High-precision only: `id`, `my`, `secure`, `connect` are common on non-auth
# hosts and are left out on purpose.
_AUTH_TERMS = (
    "login",
    "signin",
    "sign-in",
    "logon",
    "auth",
    "authn",
    "sso",
    "oauth",
    "oauth2",
    "oidc",
    "openid",
    "account",
    "accounts",
    "idp",
    "mfa",
    "otp",
    "2fa",
    "signup",
    "sign-up",
    "register",
)

# Anchored to label boundaries (start, dot, or hyphen on either side) so
# `video` cannot match on "id" and `paypalish.example` cannot match on a
# substring. No nested quantifiers, so no ReDoS.
_AUTH_RE = re.compile(
    r"(^|[.\-])(" + "|".join(re.escape(t) for t in _AUTH_TERMS) + r")([.\-]|$)",
    re.IGNORECASE,
)

# The equivalent as a Postgres regex, so a WHERE filter and the Python label
# come from the same term list rather than drifting apart.
AUTH_SQL_REGEX = r"(^|[.\-])(" + "|".join(_AUTH_TERMS) + r")([.\-]|$)"


def sni_category(host: str | None) -> str | None:
    """Return a coarse category for a server name, or None if unclassified.

    Currently the only category is "auth". More may be added, but only where
    the name is a genuinely reliable signal — over-categorising by hostname
    manufactures false confidence.
    """
    if not host:
        return None
    if _AUTH_RE.search(host):
        return "auth"
    return None
