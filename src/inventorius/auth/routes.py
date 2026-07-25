"""Passwordless, single-owner authentication routes."""

from __future__ import annotations

import base64
import binascii
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, make_response, request
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from webauthn.helpers import base64url_to_bytes

from inventorius.auth import webauthn_backend
from inventorius.auth.authority import (
    ANONYMOUS_ACTOR,
    SESSION_COOKIE,
    current_actor,
    public_unsafe,
    require_csrf,
    require_exact_origin,
    token_digest,
)
from inventorius.db import db


bp = Blueprint("auth", __name__, url_prefix="/api/auth")
OWNER_ID = "owner"
CHALLENGE_TTL = timedelta(minutes=5)
SESSION_TTL = timedelta(days=30)
RECOVERY_CODE_COUNT = 10


def _now():
    return datetime.now(timezone.utc)


def _problem(status: int, problem_type: str, title: str, detail: str):
    response = jsonify(
        kind="problem", type=problem_type, title=title, detail=detail
    )
    response.status_code = status
    return response


def _operation(rel: str, method: str, href: str):
    return {"rel": rel, "method": method, "href": href}


def _configured() -> bool:
    return bool(
        current_app.config.get("AUTH_ORIGIN")
        and current_app.config.get("AUTH_RP_ID")
    )


def _owner():
    return db.auth_principals.find_one({"_id": OWNER_ID})


def _session_resource(actor=None):
    actor = actor or current_actor()
    owner = _owner()
    if actor.is_authenticated:
        state = {
            "status": "authenticated",
            "principal": actor.principal.summary(),
            "csrf_token": actor.csrf_token,
        }
        operations = [
            _operation(
                "register-passkey-options",
                "POST",
                "/api/auth/bootstrap/registration/options",
            ),
            _operation("logout", "POST", "/api/auth/logout"),
        ]
    elif owner:
        state = {"status": "anonymous", "principal": None}
        operations = [
            _operation(
                "authenticate-passkey-options",
                "POST",
                "/api/auth/passkeys/authentication/options",
            ),
            _operation(
                "recover-passkey-options",
                "POST",
                "/api/auth/bootstrap/registration/options",
            ),
        ]
    else:
        state = {"status": "unconfigured", "principal": None}
        operations = (
            [
                _operation(
                    "bootstrap-registration-options",
                    "POST",
                    "/api/auth/bootstrap/registration/options",
                )
            ]
            if _configured()
            else []
        )
    return {
        "kind": "auth-session",
        "Id": "/api/auth/session",
        "state": state,
        "operations": operations,
    }


def _ceremony_resource(ceremony_id: str, public_key: dict, verify_href: str):
    return {
        "kind": "passkey-ceremony",
        "Id": f"/api/auth/ceremonies/{ceremony_id}",
        "state": {
            "ceremony_id": ceremony_id,
            "public_key": public_key,
        },
        "operations": [_operation("verify", "POST", verify_href)],
    }


def _json_object():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return None
    return value


def _decode_credential_id(value: str) -> bytes:
    try:
        return base64url_to_bytes(value)
    except (ValueError, TypeError, binascii.Error) as error:
        raise ValueError("credential id is not valid base64url") from error


def _encode_credential_id(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _consume_challenge(ceremony_id: str, purpose: str):
    return db.auth_challenges.find_one_and_delete(
        {
            "_id": ceremony_id,
            "purpose": purpose,
            "expires_at": {"$gt": _now()},
        }
    )


def _issue_session(principal_id: str):
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    digest = token_digest(raw_token)
    db.auth_sessions.insert_one(
        {
            "_id": digest,
            "principal_id": principal_id,
            "csrf_token": csrf_token,
            "created_at": _now(),
            "expires_at": _now() + SESSION_TTL,
        }
    )
    principal = db.auth_principals.find_one({"_id": principal_id})
    from inventorius.auth.authority import Actor, OWNER_CAPABILITIES, Principal

    actor = Actor(
        principal=Principal(
            id=principal["_id"],
            display_name=principal["display_name"],
            kind=principal.get("kind", "owner"),
        ),
        capabilities=OWNER_CAPABILITIES,
        session_digest=digest,
        csrf_token=csrf_token,
    )
    response = make_response(jsonify(_session_resource(actor)))
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        httponly=True,
        secure=current_app.config["AUTH_COOKIE_SECURE"],
        samesite="Lax",
        path="/",
    )
    return response


def _new_recovery_codes() -> list[str]:
    codes = []
    documents = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = base64.b32encode(secrets.token_bytes(10)).decode("ascii")
        code = f"{raw[:5]}-{raw[5:10]}-{raw[10:15]}-{raw[15:]}"
        codes.append(code)
        documents.append(
            {
                "_id": token_digest(code),
                "principal_id": OWNER_ID,
                "created_at": _now(),
            }
        )
    db.auth_recovery_codes.insert_many(documents)
    return codes


@bp.after_request
def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/session")
def get_session():
    return jsonify(_session_resource())


@bp.post("/bootstrap/registration/options")
@public_unsafe
def registration_options():
    rejected = require_exact_origin()
    if rejected:
        return rejected
    payload = _json_object()
    if payload is None:
        return _problem(400, "invalid-request", "Invalid request", "Expected a JSON object.")

    owner = _owner()
    actor = current_actor()
    authorization = None
    authorization_digest = None
    if actor.is_authenticated:
        rejected = require_csrf(actor)
        if rejected:
            return rejected
        authorization = "session"
        authorization_digest = actor.session_digest
    elif owner and payload.get("recovery_code"):
        recovery_digest = token_digest(str(payload["recovery_code"]).upper())
        recovered = db.auth_recovery_codes.find_one(
            {"_id": recovery_digest, "principal_id": OWNER_ID}
        )
        if not recovered:
            return _problem(
                401,
                "invalid-recovery-code",
                "Recovery code rejected",
                "The recovery code is invalid or has already been used.",
            )
        authorization = "recovery"
        authorization_digest = recovery_digest
    elif not owner and payload.get("bootstrap_token"):
        bootstrap_digest = token_digest(str(payload["bootstrap_token"]))
        token = db.auth_bootstrap_tokens.find_one(
            {
                "_id": bootstrap_digest,
                "expires_at": {"$gt": _now()},
                "consumed_at": None,
            }
        )
        if not token:
            return _problem(
                401,
                "invalid-bootstrap-token",
                "Bootstrap token rejected",
                "The bootstrap token is invalid, expired, or already used.",
            )
        authorization = "bootstrap"
        authorization_digest = bootstrap_digest
    else:
        return _problem(
            409 if owner else 401,
            "bootstrap-unavailable" if owner else "invalid-bootstrap-token",
            "Bootstrap registration unavailable" if owner else "Bootstrap token rejected",
            (
                "The owner is already configured; authenticate or use a recovery code."
                if owner
                else "Supply a valid one-time bootstrap token."
            ),
        )

    user_handle = owner["user_handle"] if owner else secrets.token_bytes(32)
    credentials = list(db.auth_credentials.find({"principal_id": OWNER_ID}))
    challenge = secrets.token_bytes(32)
    ceremony_id = secrets.token_urlsafe(24)
    db.auth_challenges.insert_one(
        {
            "_id": ceremony_id,
            "purpose": "registration",
            "authorization": authorization,
            "authorization_digest": authorization_digest,
            "challenge": challenge,
            "user_handle": user_handle,
            "created_at": _now(),
            "expires_at": _now() + CHALLENGE_TTL,
        }
    )
    public_key = webauthn_backend.registration_options(
        rp_id=current_app.config["AUTH_RP_ID"],
        rp_name=current_app.config["AUTH_RP_NAME"],
        user_id=user_handle,
        user_name=OWNER_ID,
        user_display_name=(
            owner["display_name"]
            if owner
            else current_app.config["AUTH_OWNER_DISPLAY_NAME"]
        ),
        challenge=challenge,
        exclude_credential_ids=[
            _decode_credential_id(item["_id"]) for item in credentials
        ],
    )
    return jsonify(
        _ceremony_resource(
            ceremony_id,
            public_key,
            "/api/auth/bootstrap/registration/verification",
        )
    )


@bp.post("/bootstrap/registration/verification")
@public_unsafe
def registration_verification():
    rejected = require_exact_origin()
    if rejected:
        return rejected
    payload = _json_object()
    if payload is None or not isinstance(payload.get("credential"), dict):
        return _problem(400, "invalid-request", "Invalid request", "Expected ceremony_id and credential.")
    challenge_doc = _consume_challenge(
        str(payload.get("ceremony_id", "")), "registration"
    )
    if not challenge_doc:
        return _problem(
            400,
            "invalid-ceremony",
            "Registration ceremony rejected",
            "The ceremony is invalid, expired, or has already been used.",
        )
    if challenge_doc["authorization"] == "session":
        actor = current_actor()
        if (
            not actor.is_authenticated
            or actor.session_digest != challenge_doc.get("authorization_digest")
        ):
            return _problem(
                401,
                "registration-session-ended",
                "Registration session ended",
                "Authenticate again before registering another passkey.",
            )
        rejected = require_csrf(actor)
        if rejected:
            return rejected
    try:
        verified = webauthn_backend.verify_registration(
            credential=payload["credential"],
            expected_challenge=challenge_doc["challenge"],
            expected_rp_id=current_app.config["AUTH_RP_ID"],
            expected_origin=current_app.config["AUTH_ORIGIN"],
        )
    except Exception:
        current_app.logger.info("WebAuthn registration verification failed")
        return _problem(
            400,
            "invalid-passkey",
            "Passkey registration rejected",
            "The authenticator response could not be verified.",
        )

    authorization = challenge_doc["authorization"]
    authorization_digest = challenge_doc.get("authorization_digest")
    if authorization == "bootstrap":
        consumed = db.auth_bootstrap_tokens.find_one_and_update(
            {
                "_id": authorization_digest,
                "expires_at": {"$gt": _now()},
                "consumed_at": None,
            },
            {"$set": {"consumed_at": _now()}},
            return_document=ReturnDocument.BEFORE,
        )
        if not consumed:
            return _problem(
                409,
                "bootstrap-token-consumed",
                "Bootstrap registration lost the race",
                "The one-time bootstrap token was already used.",
            )
    elif authorization == "recovery":
        consumed = db.auth_recovery_codes.find_one_and_delete(
            {"_id": authorization_digest, "principal_id": OWNER_ID}
        )
        if not consumed:
            return _problem(
                409,
                "recovery-code-consumed",
                "Recovery registration lost the race",
                "The one-time recovery code was already used.",
            )

    owner = _owner()
    created_owner = False
    if owner and owner["user_handle"] != challenge_doc["user_handle"]:
        return _problem(
            409,
            "owner-already-configured",
            "Owner already configured",
            "Another bootstrap ceremony configured the owner first.",
        )
    if not owner:
        owner_doc = {
            "_id": OWNER_ID,
            "display_name": current_app.config["AUTH_OWNER_DISPLAY_NAME"],
            "kind": "owner",
            "user_handle": challenge_doc["user_handle"],
            "created_at": _now(),
        }
        try:
            db.auth_principals.insert_one(owner_doc)
            created_owner = True
        except DuplicateKeyError:
            owner = _owner()
            if not owner or owner["user_handle"] != challenge_doc["user_handle"]:
                return _problem(
                    409,
                    "owner-already-configured",
                    "Owner already configured",
                    "Another bootstrap ceremony configured the owner first.",
                )

    credential_id = _encode_credential_id(verified.credential_id)
    try:
        db.auth_credentials.insert_one(
            {
                "_id": credential_id,
                "principal_id": OWNER_ID,
                "public_key": verified.credential_public_key,
                "sign_count": verified.sign_count,
                "aaguid": verified.aaguid,
                "device_type": verified.credential_device_type.value,
                "backed_up": verified.credential_backed_up,
                "created_at": _now(),
            }
        )
    except DuplicateKeyError:
        if created_owner:
            db.auth_principals.delete_one(
                {"_id": OWNER_ID, "user_handle": challenge_doc["user_handle"]}
            )
        return _problem(
            409,
            "passkey-already-registered",
            "Passkey already registered",
            "That credential is already registered.",
        )

    recovery_codes = _new_recovery_codes() if created_owner else None
    response = _issue_session(OWNER_ID)
    if recovery_codes:
        body = response.get_json()
        body["recovery_codes"] = recovery_codes
        response.set_data(current_app.json.dumps(body))
        response.mimetype = "application/json"
    return response


@bp.post("/passkeys/authentication/options")
@public_unsafe
def authentication_options():
    rejected = require_exact_origin()
    if rejected:
        return rejected
    owner = _owner()
    credentials = list(db.auth_credentials.find({"principal_id": OWNER_ID}))
    if not owner or not credentials:
        return _problem(
            409,
            "auth-unconfigured",
            "Passkey authentication unavailable",
            "No owner passkeys are registered.",
        )
    challenge = secrets.token_bytes(32)
    ceremony_id = secrets.token_urlsafe(24)
    db.auth_challenges.insert_one(
        {
            "_id": ceremony_id,
            "purpose": "authentication",
            "challenge": challenge,
            "created_at": _now(),
            "expires_at": _now() + CHALLENGE_TTL,
        }
    )
    public_key = webauthn_backend.authentication_options(
        rp_id=current_app.config["AUTH_RP_ID"],
        challenge=challenge,
        credential_ids=[
            _decode_credential_id(item["_id"]) for item in credentials
        ],
    )
    return jsonify(
        _ceremony_resource(
            ceremony_id,
            public_key,
            "/api/auth/passkeys/authentication/verification",
        )
    )


@bp.post("/passkeys/authentication/verification")
@public_unsafe
def authentication_verification():
    rejected = require_exact_origin()
    if rejected:
        return rejected
    payload = _json_object()
    credential_payload = payload.get("credential") if payload else None
    if not isinstance(credential_payload, dict):
        return _problem(400, "invalid-request", "Invalid request", "Expected ceremony_id and credential.")
    challenge_doc = _consume_challenge(
        str(payload.get("ceremony_id", "")), "authentication"
    )
    if not challenge_doc:
        return _problem(
            400,
            "invalid-ceremony",
            "Authentication ceremony rejected",
            "The ceremony is invalid, expired, or has already been used.",
        )
    try:
        credential_id = _encode_credential_id(
            _decode_credential_id(str(credential_payload.get("id", "")))
        )
    except ValueError:
        return _problem(400, "invalid-passkey", "Passkey authentication rejected", "The credential id is invalid.")
    stored = db.auth_credentials.find_one(
        {"_id": credential_id, "principal_id": OWNER_ID}
    )
    if not stored:
        return _problem(
            401,
            "unknown-passkey",
            "Passkey authentication rejected",
            "The credential is not registered.",
        )
    try:
        verified = webauthn_backend.verify_authentication(
            credential=credential_payload,
            expected_challenge=challenge_doc["challenge"],
            expected_rp_id=current_app.config["AUTH_RP_ID"],
            expected_origin=current_app.config["AUTH_ORIGIN"],
            credential_public_key=stored["public_key"],
            credential_current_sign_count=stored["sign_count"],
        )
    except Exception:
        current_app.logger.info("WebAuthn authentication verification failed")
        return _problem(
            401,
            "invalid-passkey",
            "Passkey authentication rejected",
            "The authenticator response could not be verified.",
        )
    if verified.credential_id != _decode_credential_id(credential_id):
        return _problem(401, "invalid-passkey", "Passkey authentication rejected", "The verified credential did not match.")
    db.auth_credentials.update_one(
        {"_id": credential_id},
        {
            "$set": {
                "sign_count": verified.new_sign_count,
                "device_type": verified.credential_device_type.value,
                "backed_up": verified.credential_backed_up,
                "last_used_at": _now(),
            }
        },
    )
    return _issue_session(OWNER_ID)


@bp.post("/logout")
@public_unsafe
def logout():
    rejected = require_exact_origin()
    if rejected:
        return rejected
    actor = current_actor()
    response = make_response(jsonify(_session_resource(ANONYMOUS_ACTOR)))
    if actor.is_authenticated:
        rejected = require_csrf(actor)
        if rejected:
            return rejected
        db.auth_sessions.delete_one({"_id": actor.session_digest})
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="Lax")
    return response
