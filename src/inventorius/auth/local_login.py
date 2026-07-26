"""Safety policy for the explicitly local development login escape hatch."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit


LOCAL_LOGIN_TOKEN_TTL_MINUTES = 5
LOCAL_LOGIN_TOKEN_MAX_TTL_MINUTES = 30
LOOPBACK_HOSTNAMES = frozenset({"localhost", "127.0.0.1"})


def local_login_requested(config: Mapping) -> bool:
    value = config.get("AUTH_LOCAL_LOGIN_ENABLED", False)
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return value is True


def local_login_safety_error(config: Mapping) -> str | None:
    """Explain why an enabled local login configuration must fail closed."""

    if not local_login_requested(config):
        return None
    origin = config.get("AUTH_ORIGIN")
    hostname = urlsplit(origin).hostname if isinstance(origin, str) else None
    if hostname not in LOOPBACK_HOSTNAMES:
        return (
            "AUTH_LOCAL_LOGIN_ENABLED requires AUTH_ORIGIN to use "
            "localhost or 127.0.0.1."
        )
    if config.get("AUTH_COOKIE_SECURE"):
        return (
            "AUTH_LOCAL_LOGIN_ENABLED requires AUTH_COOKIE_SECURE to be false."
        )
    return None


def local_login_available(config: Mapping) -> bool:
    return (
        local_login_requested(config)
        and local_login_safety_error(config) is None
    )
