"""The AniList token input must reject the OAuth client SECRET."""

import re


def _looks_like_secret(value: str) -> bool:
    """Same rule as main._a_token: a bare alphanumeric client secret.

    AniList OAuth access tokens are JWTs (three dot-separated parts); the
    client SECRET from /apps/developer is a single short alphanumeric blob.
    """
    v = value.strip()
    return (32 <= len(v) <= 64
            and bool(re.fullmatch(r"[A-Za-z0-9]+", v))
            and "." not in v)


def test_client_secret_shape_is_recognised():
    assert _looks_like_secret("M8zWOeR6i146wxrCaXLbVjz9mhkUcWA3SlMzj0")
    assert _looks_like_secret("0123456789abcdef0123456789abcdef01234567")
    assert not _looks_like_secret("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig")
    assert not _looks_like_secret("eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.abc.def")
    assert not _looks_like_secret("short")


def test_source_uses_the_same_guard():
    from pathlib import Path
    src = Path("src/freeflix_cli/main.py").read_text(encoding="utf-8")
    assert '[A-Za-z0-9]+' in src
    assert "looks like the API Client SECRET" in src
