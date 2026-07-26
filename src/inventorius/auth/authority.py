"""Request authority backed by opaque, server-side sessions."""

from __future__ import annotations

import functools
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, TypeVar

from flask import current_app, g, jsonify, request

from inventorius.db import db


SESSION_COOKIE = "inventorius_session"
OWNER_CAPABILITIES = frozenset({"*"})
PUBLIC_CAPABILITIES = frozenset({"inventory:read"})


@dataclass(frozen=True)
class Principal:
    id: str
    display_name: str
    kind: str

    def summary(self) -> dict[str, str]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class Actor:
    principal: Principal | None
    capabilities: frozenset[str]
    session_digest: str | None = None
    csrf_token: str | None = None

    @property
    def is_authenticated(self) -> bool:
        return self.principal is not None

    @property
    def id(self) -> str | None:
        return self.principal.id if self.principal else None

    def can(self, capability: str) -> bool:
        return "*" in self.capabilities or capability in self.capabilities

    def durable_ref(self) -> dict[str, str] | None:
        """Return stable audit identity, excluding transport/session secrets."""

        if not self.principal:
            return None
        return {
            "actor_id": self.principal.id,
            "actor_type": self.principal.kind,
        }


ANONYMOUS_ACTOR = Actor(principal=None, capabilities=PUBLIC_CAPABILITIES)
F = TypeVar("F", bound=Callable)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load_actor() -> Actor:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return ANONYMOUS_ACTOR
    try:
        digest = token_digest(token)
    except (UnicodeEncodeError, AttributeError):
        return ANONYMOUS_ACTOR
    session = db.auth_sessions.find_one(
        {"_id": digest, "expires_at": {"$gt": datetime.now(timezone.utc)}}
    )
    if not session:
        return ANONYMOUS_ACTOR
    principal_doc = db.auth_principals.find_one({"_id": session["principal_id"]})
    if not principal_doc:
        return ANONYMOUS_ACTOR
    return Actor(
        principal=Principal(
            id=principal_doc["_id"],
            display_name=principal_doc["display_name"],
            kind=principal_doc.get("kind", "owner"),
        ),
        capabilities=OWNER_CAPABILITIES,
        session_digest=digest,
        csrf_token=session["csrf_token"],
    )


def current_actor() -> Actor:
    if "inventorius_actor" not in g:
        g.inventorius_actor = _load_actor()
    return g.inventorius_actor


def _problem(status: int, problem_type: str, title: str, detail: str):
    response = jsonify(
        kind="problem", type=problem_type, title=title, detail=detail
    )
    response.status_code = status
    return response


def require_exact_origin():
    expected = current_app.config.get("AUTH_ORIGIN")
    if not expected:
        return _problem(
            503,
            "auth-not-configured",
            "Authentication is not configured",
            "The server has no WebAuthn origin configured.",
        )
    if request.headers.get("Origin") != expected:
        return _problem(
            403,
            "origin-mismatch",
            "Request origin rejected",
            "The request Origin does not exactly match the configured origin.",
        )
    return None


def require_csrf(actor: Actor):
    supplied = request.headers.get("X-CSRF-Token", "")
    expected = actor.csrf_token or ""
    if not supplied or not hmac.compare_digest(supplied, expected):
        return _problem(
            403,
            "csrf-rejected",
            "CSRF token rejected",
            "Supply the CSRF token from the current auth session.",
        )
    return None


def require_capability(capability: str):
    """Require owner authority, an exact browser origin, and CSRF."""

    def decorate(function: F) -> F:
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            actor = current_actor()
            if not actor.is_authenticated:
                return _problem(
                    401,
                    "authentication-required",
                    "Authentication required",
                    "This operation requires an authenticated owner session.",
                )
            if not actor.can(capability):
                return _problem(
                    403,
                    "capability-required",
                    "Capability required",
                    f"The current actor lacks {capability}.",
                )
            rejected = require_exact_origin() or require_csrf(actor)
            if rejected:
                return rejected
            return function(*args, **kwargs)

        setattr(wrapped, "inventorius_authority_checked", True)
        setattr(wrapped, "inventorius_required_capability", capability)
        return wrapped  # type: ignore[return-value]

    return decorate


def public_unsafe(function: F) -> F:
    """Mark a route as intentionally public despite using an unsafe method."""

    setattr(function, "inventorius_public_unsafe", True)
    return function
