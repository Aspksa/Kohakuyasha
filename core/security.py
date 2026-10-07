from __future__ import annotations

import hmac
from urllib.parse import urlsplit

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
SESSION_COOKIE = "kohakuyasha_session"
ACTION_HEADER = "X-Kohakuyasha-Request"


def _hostname(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return urlsplit(f"//{value}").hostname
    except ValueError:
        return None


def is_allowed_host_header(host_header: str | None, port: int) -> bool:
    if not host_header:
        return False
    try:
        parsed = urlsplit(f"//{host_header}")
    except ValueError:
        return False
    if parsed.hostname not in LOCAL_HOSTS:
        return False
    return parsed.port in {None, int(port)}


def is_allowed_origin(origin: str | None, port: int) -> bool:
    if not origin:
        return False
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    if parsed.scheme != "http" or parsed.hostname not in LOCAL_HOSTS:
        return False
    effective_port = parsed.port or 80
    return effective_port == int(port)


def session_matches(value: str | None, expected: str) -> bool:
    return bool(value) and hmac.compare_digest(value, expected)
