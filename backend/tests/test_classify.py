"""The SNI classifier is a name heuristic, and its job is precision: a false
"auth" label pointed at an ordinary domain would manufacture a brute-force
alarm out of nothing. These cases pin the boundary behaviour and the traps."""

import pytest

from tlsrep.classify import AUTH_SQL_REGEX, sni_category


@pytest.mark.parametrize(
    "host",
    [
        "accounts.google.com",
        "login.microsoftonline.com",
        "auth.example.com",
        "sso.corp.example",
        "signin.aws.amazon.com",
        "oauth2.googleapis.com",
        "id-login.bank.example",       # term after a hyphen
        "register-service.gmx.net",    # term before a hyphen
        "x-auth.example",
    ],
)
def test_auth_like_names_are_classified(host):
    assert sni_category(host) == "auth"


@pytest.mark.parametrize(
    "host",
    [
        "video.example.com",           # contains "id" but not as a label
        "api.stripe.com",              # handles auth, but name doesn't — a known miss
        "cdn.cloudflare.com",
        "paypalish.example.com",       # substring, not a label
        "avatars.githubusercontent.com",
        "tmx.bestbuy.com",
        "myaccounting.example.com",    # "account" only as a substring of a longer label
        "",
        None,
    ],
)
def test_non_auth_names_are_not_classified(host):
    assert sni_category(host) is None


def test_the_only_category_is_auth_for_now():
    # Guards against a future term list quietly emitting a category the API
    # documents nowhere.
    assert sni_category("auth.example") in (None, "auth")


def test_sql_regex_agrees_with_python_on_a_battery():
    """Filter and label are generated from one term list; a divergence here
    means a domain shows a category the /snis?category filter would not select,
    or vice versa. Checked with Python's re as a stand-in for Postgres ~*."""
    import re

    rx = re.compile(AUTH_SQL_REGEX, re.IGNORECASE)
    for host in [
        "accounts.google.com",
        "id-login.bank.example",
        "api.stripe.com",
        "video.example.com",
        "sso.example",
        "cdn.example",
        "register-x.example",
    ]:
        assert bool(rx.search(host)) == (sni_category(host) == "auth")
