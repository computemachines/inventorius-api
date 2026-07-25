"""Inventorius passwordless authentication foundation."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import click
from flask import Flask, jsonify, request
from flask.cli import with_appcontext

from inventorius.auth.authority import (
    Actor,
    Principal,
    current_actor,
    public_unsafe,
    require_capability,
    token_digest,
)
from inventorius.auth.routes import bp
from inventorius.db import get_mongo_client


def _truthy(value: str | None) -> bool:
    return (value or "").lower() in {"1", "true", "yes", "on"}


def _default_origin(app: Flask) -> str | None:
    configured = os.getenv("WEBAUTHN_ORIGIN")
    if configured:
        return configured.rstrip("/")
    if app.debug or _truthy(os.getenv("FLASK_DEBUG")):
        return "http://localhost:3000"
    return None


def _valid_origin(origin: str | None) -> bool:
    if not origin:
        return False
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return False
    return parsed.scheme == "https" or parsed.hostname in {"localhost", "127.0.0.1"}


def init_auth(app: Flask):
    origin = _default_origin(app)
    if origin and not _valid_origin(origin):
        app.logger.error("Authentication disabled: WEBAUTHN_ORIGIN is not a valid secure origin")
        origin = None
    parsed = urlsplit(origin) if origin else None
    rp_id = os.getenv("WEBAUTHN_RP_ID") or (parsed.hostname if parsed else None)
    if parsed and rp_id and not (
        parsed.hostname == rp_id or parsed.hostname.endswith(f".{rp_id}")
    ):
        app.logger.error("Authentication disabled: WEBAUTHN_RP_ID does not match WEBAUTHN_ORIGIN")
        origin = None
        rp_id = None
    app.config.setdefault("AUTH_ORIGIN", origin)
    app.config.setdefault("AUTH_RP_ID", rp_id)
    app.config.setdefault(
        "AUTH_RP_NAME",
        os.getenv("INVENTORIUS_AUTH_RP_NAME", "Inventorius"),
    )
    app.config.setdefault(
        "AUTH_OWNER_DISPLAY_NAME",
        os.getenv("INVENTORIUS_OWNER_DISPLAY_NAME", "Owner"),
    )
    app.config.setdefault(
        "AUTH_COOKIE_SECURE",
        (
            bool(origin and origin.startswith("https://"))
            or _truthy(os.getenv("INVENTORIUS_AUTH_COOKIE_SECURE"))
        ),
    )
    app.register_blueprint(bp)
    app.cli.add_command(auth_cli)

    @app.before_request
    def load_request_actor():
        current_actor()

    @app.before_request
    def reject_unclassified_unsafe_api_routes():
        if (
            request.method not in {"POST", "PUT", "PATCH", "DELETE"}
            or not request.path.startswith("/api")
            or request.url_rule is None
        ):
            return None
        view = app.view_functions[request.url_rule.endpoint]
        if getattr(view, "inventorius_authority_checked", False) or getattr(
            view, "inventorius_public_unsafe", False
        ):
            return None
        app.logger.error(
            "Unsafe API route has no authority classification: %s %s",
            request.method,
            request.path,
        )
        response = jsonify(
            kind="problem",
            type="unsafe-route-unclassified",
            title="Unsafe route is not classified",
            detail="The server refused an unsafe API route without an authority policy.",
        )
        response.status_code = 500
        return response


@click.group("auth")
def auth_cli():
    """Manage passwordless authentication."""


@auth_cli.command("bootstrap-token")
@click.option(
    "--expires-minutes",
    type=click.IntRange(1, 1440),
    default=15,
    show_default=True,
)
@with_appcontext
def bootstrap_token(expires_minutes: int):
    """Create a single-use token for initial owner registration."""

    from flask import current_app

    if not current_app.config.get("AUTH_ORIGIN") or not current_app.config.get(
        "AUTH_RP_ID"
    ):
        raise click.ClickException(
            "Set WEBAUTHN_ORIGIN (and optionally WEBAUTHN_RP_ID) first."
        )
    database = get_mongo_client().inventoriusdb
    if database.auth_principals.find_one({"_id": "owner"}):
        raise click.ClickException("The owner is already configured.")
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    database.auth_bootstrap_tokens.insert_one(
        {
            "_id": token_digest(raw_token),
            "created_at": now,
            "expires_at": now + timedelta(minutes=expires_minutes),
            "consumed_at": None,
        }
    )
    click.echo(raw_token)


__all__ = [
    "Actor",
    "Principal",
    "current_actor",
    "init_auth",
    "public_unsafe",
    "require_capability",
]
