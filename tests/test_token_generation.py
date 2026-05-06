from __future__ import annotations

from app.security import generate_csrf_token, generate_session_token


def test_session_token_is_url_safe_and_long():
    t = generate_session_token()
    assert isinstance(t, str)
    # 32 random bytes -> at least 43 chars base64url
    assert len(t) >= 43
    # url-safe charset only
    allowed = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    assert set(t).issubset(allowed)


def test_session_tokens_are_unique():
    seen = {generate_session_token() for _ in range(2000)}
    assert len(seen) == 2000


def test_csrf_tokens_are_unique_and_distinct_from_session():
    s = generate_session_token()
    c = generate_csrf_token()
    assert s != c
    assert len({generate_csrf_token() for _ in range(2000)}) == 2000
