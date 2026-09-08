from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from flask import Flask

from inventorius import app
import inventorius.auth as auth_package
from inventorius.auth import webauthn_backend
from inventorius.auth.authority import token_digest
from tests.database import get_test_database


ORIGIN = "https://inventory.example.test"


@pytest.fixture
def auth_client(client):
    previous = {
        key: app.config.get(key)
        for key in (
            "AUTH_ORIGIN",
            "AUTH_RP_ID",
            "AUTH_RP_NAME",
            "AUTH_OWNER_DISPLAY_NAME",
            "AUTH_COOKIE_SECURE",
            "AUTH_LOCAL_LOGIN_ENABLED",
        )
    }
    app.config.update(
        AUTH_ORIGIN=ORIGIN,
        AUTH_RP_ID="inventory.example.test",
        AUTH_RP_NAME="Inventorius Test",
        AUTH_OWNER_DISPLAY_NAME="Test Owner",
        AUTH_COOKIE_SECURE=True,
        AUTH_LOCAL_LOGIN_ENABLED=False,
    )
    database = get_test_database()
    for name in (
        "auth_bootstrap_tokens",
        "auth_challenges",
        "auth_credentials",
        "auth_principals",
        "auth_recovery_codes",
        "auth_sessions",
        "auth_local_login_tokens",
        "auth_access_tokens",
    ):
        database[name].delete_many({})
    yield client
    for key, value in previous.items():
        app.config[key] = value


def _bootstrap_token(database, raw="bootstrap-secret"):
    database.auth_bootstrap_tokens.insert_one(
        {
            "_id": token_digest(raw),
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
            "consumed_at": None,
        }
    )
    return raw


def _registration_result(credential_id=b"credential-one"):
    return SimpleNamespace(
        credential_id=credential_id,
        credential_public_key=b"public-key",
        sign_count=4,
        aaguid="test-aaguid",
        credential_device_type=SimpleNamespace(value="multi_device"),
        credential_backed_up=True,
    )


def _authentication_result(credential_id=b"credential-one"):
    return SimpleNamespace(
        credential_id=credential_id,
        new_sign_count=5,
        credential_device_type=SimpleNamespace(value="multi_device"),
        credential_backed_up=True,
    )


def _enable_local_login():
    app.config.update(
        AUTH_ORIGIN="http://localhost:3000",
        AUTH_RP_ID="localhost",
        AUTH_COOKIE_SECURE=False,
        AUTH_LOCAL_LOGIN_ENABLED=True,
    )


def _insert_owner(database):
    database.auth_principals.insert_one(
        {
            "_id": "owner",
            "display_name": "Test Owner",
            "kind": "owner",
            "user_handle": b"owner-handle",
            "created_at": datetime.now(timezone.utc),
        }
    )


def _start_registration(auth_client, monkeypatch, token="bootstrap-secret"):
    monkeypatch.setattr(
        webauthn_backend,
        "registration_options",
        lambda **kwargs: {
            "challenge": "browser-challenge",
            "rp": {"id": kwargs["rp_id"]},
        },
    )
    return auth_client.post(
        "/api/auth/bootstrap/registration/options",
        json={"bootstrap_token": token},
        headers={"Origin": ORIGIN},
    )


def _register_owner(auth_client, monkeypatch):
    database = get_test_database()
    token = _bootstrap_token(database)
    options = _start_registration(auth_client, monkeypatch, token)
    monkeypatch.setattr(
        webauthn_backend,
        "verify_registration",
        lambda **kwargs: _registration_result(),
    )
    verified = auth_client.post(
        "/api/auth/bootstrap/registration/verification",
        json={
            "ceremony_id": options.json["state"]["ceremony_id"],
            "credential": {"id": "Y3JlZGVudGlhbC1vbmU"},
        },
        headers={"Origin": ORIGIN},
    )
    return options, verified


def test_session_is_discoverable_before_bootstrap(auth_client):
    response = auth_client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json == {
        "kind": "auth-session",
        "Id": "/api/auth/session",
        "state": {"status": "unconfigured", "principal": None},
        "operations": [
            {
                "rel": "bootstrap-registration-options",
                "method": "POST",
                "href": "/api/auth/bootstrap/registration/options",
            }
        ],
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_application_root_supports_the_unified_proxy_trailing_slash(auth_client):
    response = auth_client.get("/api/")

    assert response.status_code == 200
    assert response.json["Id"] == "/api"
    assert response.json["operations"] == []
    assert {link["rel"] for link in response.json["links"]} == {
        "search",
        "inventory-activity",
        "authentication",
    }


def test_registration_options_advertise_verification_without_consuming_token(
    auth_client, monkeypatch
):
    database = get_test_database()
    raw_token = _bootstrap_token(database)

    response = _start_registration(auth_client, monkeypatch, raw_token)

    assert response.status_code == 200
    assert response.json["kind"] == "passkey-ceremony"
    assert response.json["operations"] == [
        {
            "rel": "verify",
            "method": "POST",
            "href": "/api/auth/bootstrap/registration/verification",
        }
    ]
    assert (
        database.auth_bootstrap_tokens.find_one(
            {"_id": token_digest(raw_token)}
        )["consumed_at"]
        is None
    )


def test_bootstrap_verification_creates_owner_recovery_codes_and_hashed_session(
    auth_client, monkeypatch
):
    database = get_test_database()
    _, response = _register_owner(auth_client, monkeypatch)

    assert response.status_code == 200
    assert response.json["state"]["status"] == "authenticated"
    assert response.json["state"]["principal"] == {
        "id": "owner",
        "display_name": "Test Owner",
        "kind": "owner",
    }
    assert len(response.json["recovery_codes"]) == 10
    assert database.auth_recovery_codes.count_documents({}) == 10
    assert database.auth_principals.count_documents({}) == 1
    assert database.auth_credentials.count_documents({}) == 1
    assert database.auth_challenges.count_documents({}) == 0
    assert (
        database.auth_bootstrap_tokens.find_one({})["consumed_at"] is not None
    )

    cookie = response.headers["Set-Cookie"]
    raw_session = cookie.split("=", 1)[1].split(";", 1)[0]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=Lax" in cookie
    assert "Max-Age" not in cookie
    assert database.auth_sessions.find_one({"_id": raw_session}) is None
    assert database.auth_sessions.find_one(
        {"_id": token_digest(raw_session)}
    )


def test_registration_challenge_and_bootstrap_token_are_one_use(
    auth_client, monkeypatch
):
    _, first = _register_owner(auth_client, monkeypatch)
    ceremony_id = (
        get_test_database()
        .auth_challenges.find_one({"purpose": "registration"})
    )
    assert first.status_code == 200
    # The completed ceremony was deleted, and the token cannot authorize another.
    assert ceremony_id is None
    auth_client.delete_cookie("inventorius_session")
    second = _start_registration(auth_client, monkeypatch)
    assert second.status_code == 409


def test_failed_registration_does_not_consume_bootstrap_token(
    auth_client, monkeypatch
):
    database = get_test_database()
    raw_token = _bootstrap_token(database)
    options = _start_registration(auth_client, monkeypatch, raw_token)

    def reject(**kwargs):
        raise ValueError("mock verification failure")

    monkeypatch.setattr(webauthn_backend, "verify_registration", reject)
    response = auth_client.post(
        "/api/auth/bootstrap/registration/verification",
        json={
            "ceremony_id": options.json["state"]["ceremony_id"],
            "credential": {"id": "not-valid"},
        },
        headers={"Origin": ORIGIN},
    )

    assert response.status_code == 400
    assert (
        database.auth_bootstrap_tokens.find_one(
            {"_id": token_digest(raw_token)}
        )["consumed_at"]
        is None
    )
    retry = _start_registration(auth_client, monkeypatch, raw_token)
    assert retry.status_code == 200


def test_recovery_code_registers_an_additional_passkey(
    auth_client, monkeypatch
):
    database = get_test_database()
    _, registered = _register_owner(auth_client, monkeypatch)
    recovery_code = registered.json["recovery_codes"][0]
    remaining_codes = database.auth_recovery_codes.count_documents({})
    auth_client.delete_cookie("inventorius_session")
    monkeypatch.setattr(
        webauthn_backend,
        "registration_options",
        lambda **kwargs: {"challenge": "recovery-challenge"},
    )

    options = auth_client.post(
        "/api/auth/bootstrap/registration/options",
        json={"recovery_code": recovery_code.lower()},
        headers={"Origin": ORIGIN},
    )
    assert options.status_code == 200
    assert database.auth_recovery_codes.count_documents({}) == remaining_codes

    monkeypatch.setattr(
        webauthn_backend,
        "verify_registration",
        lambda **kwargs: _registration_result(b"credential-two"),
    )
    verified = auth_client.post(
        "/api/auth/bootstrap/registration/verification",
        json={
            "ceremony_id": options.json["state"]["ceremony_id"],
            "credential": {"id": "Y3JlZGVudGlhbC10d28"},
        },
        headers={"Origin": ORIGIN},
    )
    assert verified.status_code == 200
    assert "recovery_codes" not in verified.json
    assert database.auth_credentials.count_documents({}) == 2
    assert database.auth_recovery_codes.count_documents({}) == remaining_codes - 1


def test_authentication_is_discoverable_and_issues_new_session(
    auth_client, monkeypatch
):
    database = get_test_database()
    _, registered = _register_owner(auth_client, monkeypatch)
    auth_client.delete_cookie("inventorius_session")
    anonymous_session = auth_client.get("/api/auth/session")
    assert {
        operation["rel"] for operation in anonymous_session.json["operations"]
    } == {"authenticate-passkey-options", "recover-passkey-options"}
    seen = {}

    def options(**kwargs):
        seen.update(kwargs)
        return {"challenge": "authentication-challenge", "allowCredentials": []}

    monkeypatch.setattr(webauthn_backend, "authentication_options", options)
    options_response = auth_client.post(
        "/api/auth/passkeys/authentication/options",
        headers={"Origin": ORIGIN},
    )
    assert options_response.status_code == 200
    assert seen["credential_ids"] == [b"credential-one"]
    assert options_response.json["operations"][0]["rel"] == "verify"

    monkeypatch.setattr(
        webauthn_backend,
        "verify_authentication",
        lambda **kwargs: _authentication_result(),
    )
    verification = auth_client.post(
        "/api/auth/passkeys/authentication/verification",
        json={
            "ceremony_id": options_response.json["state"]["ceremony_id"],
            "credential": {"id": "Y3JlZGVudGlhbC1vbmU"},
        },
        headers={"Origin": ORIGIN},
    )
    assert verification.status_code == 200
    assert verification.json["state"]["status"] == "authenticated"
    assert database.auth_credentials.find_one({})["sign_count"] == 5
    assert database.auth_sessions.count_documents({}) == 2
    assert registered.json["state"]["csrf_token"] != verification.json["state"]["csrf_token"]

    authenticated_session = auth_client.get("/api/auth/session")
    assert {
        operation["rel"]
        for operation in authenticated_session.json["operations"]
    } == {
        "access-tokens",
        "register-passkey-options",
        "logout",
        "sessions",
        "recent-passkey-options",
    }


def test_expired_or_idle_session_is_anonymous(auth_client):
    database = get_test_database()
    _insert_owner(database)
    now = datetime.now(timezone.utc)
    for raw_token, expires_at, idle_expires_at in (
        ("absolute-expired", now - timedelta(seconds=1), now + timedelta(hours=1)),
        ("idle-expired", now + timedelta(hours=1), now - timedelta(seconds=1)),
    ):
        database.auth_sessions.insert_one(
            {
                "_id": token_digest(raw_token),
                "principal_id": "owner",
                "csrf_token": "csrf",
                "created_at": now - timedelta(hours=1),
                "last_seen_at": now - timedelta(hours=1),
                "idle_expires_at": idle_expires_at,
                "expires_at": expires_at,
            }
        )
        auth_client.set_cookie("inventorius_session", raw_token)
        response = auth_client.get("/api/auth/session")
        assert response.json["state"]["status"] == "anonymous"


def test_session_inventory_is_private_and_logout_all_requires_recent_passkey(
    auth_client, monkeypatch
):
    database = get_test_database()
    _, registered = _register_owner(auth_client, monkeypatch)
    csrf = registered.json["state"]["csrf_token"]
    now = datetime.now(timezone.utc)
    database.auth_sessions.insert_one(
        {
            "_id": "other-session",
            "principal_id": "owner",
            "csrf_token": "other-csrf",
            "authentication_method": "passkey",
            "created_at": now,
            "last_seen_at": now,
            "idle_expires_at": now + timedelta(hours=1),
            "expires_at": now + timedelta(days=1),
            "recent_auth_at": now,
        }
    )
    inventory = auth_client.get("/api/auth/sessions")
    assert inventory.status_code == 200
    assert len(inventory.json["state"]["sessions"]) == 2
    assert any(item["current"] for item in inventory.json["state"]["sessions"])

    current = database.auth_sessions.find_one({"csrf_token": csrf})
    database.auth_sessions.update_one(
        {"_id": current["_id"]},
        {"$set": {"recent_auth_at": now - timedelta(minutes=6)}},
    )
    rejected = auth_client.post(
        "/api/auth/logout-all-sessions",
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert rejected.status_code == 401
    assert rejected.json["type"] == "recent-authentication-required"
    assert database.auth_sessions.count_documents({}) == 2


def test_recent_passkey_confirmation_refreshes_current_session(auth_client, monkeypatch):
    database = get_test_database()
    _, registered = _register_owner(auth_client, monkeypatch)
    csrf = registered.json["state"]["csrf_token"]
    current = database.auth_sessions.find_one({"csrf_token": csrf})
    database.auth_sessions.update_one(
        {"_id": current["_id"]},
        {"$set": {"recent_auth_at": _past_recent_authentication()}},
    )
    monkeypatch.setattr(
        webauthn_backend, "authentication_options", lambda **kwargs: {"challenge": "recent"}
    )
    options = auth_client.post(
        "/api/auth/passkeys/recent-authentication/options",
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert options.status_code == 200
    monkeypatch.setattr(webauthn_backend, "verify_authentication", lambda **kwargs: _authentication_result())
    verified = auth_client.post(
        "/api/auth/passkeys/recent-authentication/verification",
        json={"ceremony_id": options.json["state"]["ceremony_id"], "credential": {"id": "Y3JlZGVudGlhbC1vbmU"}},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert verified.status_code == 200
    refreshed = database.auth_sessions.find_one({"_id": current["_id"]})
    assert refreshed["recent_auth_at"].replace(tzinfo=timezone.utc) > _past_recent_authentication()


def test_registering_another_passkey_requires_recent_confirmation(auth_client, monkeypatch):
    database = get_test_database()
    _, registered = _register_owner(auth_client, monkeypatch)
    csrf = registered.json["state"]["csrf_token"]
    current = database.auth_sessions.find_one({"csrf_token": csrf})
    database.auth_sessions.update_one(
        {"_id": current["_id"]},
        {"$set": {"recent_auth_at": _past_recent_authentication()}},
    )
    response = auth_client.post(
        "/api/auth/bootstrap/registration/options",
        json={},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 401
    assert response.json["type"] == "recent-authentication-required"


def _past_recent_authentication():
    return datetime.now(timezone.utc) - timedelta(minutes=6)


def test_exact_origin_and_logout_csrf_are_enforced(auth_client, monkeypatch):
    database = get_test_database()
    _, registered = _register_owner(auth_client, monkeypatch)

    wrong_origin = auth_client.post(
        "/api/auth/passkeys/authentication/options",
        headers={"Origin": "https://evil.example"},
    )
    assert wrong_origin.status_code == 403
    assert wrong_origin.json["type"] == "origin-mismatch"

    no_csrf = auth_client.post(
        "/api/auth/logout", headers={"Origin": ORIGIN}
    )
    assert no_csrf.status_code == 403
    assert database.auth_sessions.count_documents({}) == 1

    logged_out = auth_client.post(
        "/api/auth/logout",
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": registered.json["state"]["csrf_token"],
        },
    )
    assert logged_out.status_code == 200
    assert logged_out.json["state"]["status"] == "anonymous"
    assert database.auth_sessions.count_documents({}) == 0


def test_webauthn_backend_requests_required_discoverable_credentials(monkeypatch):
    registration_call = {}
    authentication_call = {}

    monkeypatch.setattr(
        webauthn_backend,
        "generate_registration_options",
        lambda **kwargs: registration_call.update(kwargs) or SimpleNamespace(),
    )
    monkeypatch.setattr(
        webauthn_backend,
        "generate_authentication_options",
        lambda **kwargs: authentication_call.update(kwargs) or SimpleNamespace(),
    )
    monkeypatch.setattr(
        webauthn_backend, "options_to_json", lambda options: "{}"
    )

    webauthn_backend.registration_options(
        rp_id="inventory.example.test",
        rp_name="Inventorius",
        user_id=b"owner",
        user_name="owner",
        user_display_name="Owner",
        challenge=b"challenge",
        exclude_credential_ids=[],
    )
    selection = registration_call["authenticator_selection"]
    assert selection.resident_key.value == "required"
    assert selection.require_resident_key is True

    webauthn_backend.authentication_options(
        rp_id="inventory.example.test",
        challenge=b"challenge",
        credential_ids=[b"ignored-for-discoverability"],
    )
    assert authentication_call["allow_credentials"] == []
    assert authentication_call["user_verification"].value == "required"


def test_cli_creates_only_a_hashed_one_time_bootstrap_token(
    auth_client, monkeypatch
):
    database = get_test_database()
    database.auth_principals.delete_many({})
    monkeypatch.setattr(
        auth_package,
        "get_mongo_client",
        lambda: SimpleNamespace(inventoriusdb=database),
    )

    result = app.test_cli_runner().invoke(
        args=["auth", "bootstrap-token", "--expires-minutes", "5"]
    )

    assert result.exit_code == 0
    raw_token = result.output.strip()
    assert raw_token
    assert database.auth_bootstrap_tokens.find_one({"_id": raw_token}) is None
    stored = database.auth_bootstrap_tokens.find_one(
        {"_id": token_digest(raw_token)}
    )
    assert stored
    assert stored["consumed_at"] is None


def test_local_login_is_disabled_by_default_for_endpoint_cli_and_hypermedia(
    auth_client, monkeypatch
):
    database = get_test_database()
    _insert_owner(database)
    monkeypatch.setattr(
        auth_package,
        "get_mongo_client",
        lambda: SimpleNamespace(inventoriusdb=database),
    )

    session = auth_client.get("/api/auth/session")
    response = auth_client.post(
        "/api/auth/local-login",
        json={"token": "not-a-token"},
        headers={"Origin": ORIGIN},
    )
    command = app.test_cli_runner().invoke(
        args=["auth", "local-login-token"]
    )

    assert response.status_code == 404
    assert response.json["type"] == "not-found"
    assert command.exit_code != 0
    assert "disabled or its safety checks failed" in command.output
    assert {
        operation["rel"] for operation in session.json["operations"]
    } == {"authenticate-passkey-options", "recover-passkey-options"}


def test_local_login_configuration_fails_closed_for_non_loopback_origin():
    isolated_app = Flask("unsafe-local-login-test")
    isolated_app.config.update(
        AUTH_ORIGIN="https://inventory.example.test",
        AUTH_RP_ID="inventory.example.test",
        AUTH_COOKIE_SECURE=False,
        AUTH_LOCAL_LOGIN_ENABLED=True,
    )

    with pytest.raises(RuntimeError, match="localhost or 127.0.0.1"):
        auth_package.init_auth(isolated_app)


def test_local_login_cli_requires_an_owner(auth_client, monkeypatch):
    database = get_test_database()
    _enable_local_login()
    monkeypatch.setattr(
        auth_package,
        "get_mongo_client",
        lambda: SimpleNamespace(inventoriusdb=database),
    )

    result = app.test_cli_runner().invoke(
        args=["auth", "local-login-token"]
    )

    assert result.exit_code != 0
    assert "Configure the owner" in result.output
    assert database.auth_local_login_tokens.count_documents({}) == 0


def test_local_login_cli_stores_only_a_short_lived_hash(
    auth_client, monkeypatch
):
    database = get_test_database()
    _enable_local_login()
    _insert_owner(database)
    monkeypatch.setattr(
        auth_package,
        "get_mongo_client",
        lambda: SimpleNamespace(inventoriusdb=database),
    )
    result = app.test_cli_runner().invoke(
        args=["auth", "local-login-token"]
    )

    assert result.exit_code == 0
    raw_token = result.output.strip()
    assert raw_token
    assert database.auth_local_login_tokens.find_one({"_id": raw_token}) is None
    stored = database.auth_local_login_tokens.find_one(
        {"_id": token_digest(raw_token)}
    )
    assert stored
    assert stored["expires_at"] - stored["created_at"] == timedelta(minutes=5)

    too_long = app.test_cli_runner().invoke(
        args=["auth", "local-login-token", "--expires-minutes", "31"]
    )
    assert too_long.exit_code != 0


def test_local_login_requires_exact_origin_without_consuming_token(
    auth_client,
):
    database = get_test_database()
    _enable_local_login()
    _insert_owner(database)
    raw_token = "local-login-secret"
    database.auth_local_login_tokens.insert_one(
        {
            "_id": token_digest(raw_token),
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
    )

    response = auth_client.post(
        "/api/auth/local-login",
        json={"token": raw_token},
        headers={"Origin": "http://127.0.0.1:3000"},
    )

    assert response.status_code == 403
    assert response.json["type"] == "origin-mismatch"
    assert database.auth_local_login_tokens.find_one(
        {"_id": token_digest(raw_token)}
    )


def test_local_login_atomically_consumes_token_and_issues_normal_owner_session(
    auth_client,
):
    database = get_test_database()
    _enable_local_login()
    _insert_owner(database)
    raw_token = "local-login-secret"
    database.auth_local_login_tokens.insert_many(
        [
            {
                "_id": token_digest(raw_token),
                "created_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
            {
                "_id": token_digest("expired-secret"),
                "created_at": datetime.now(timezone.utc) - timedelta(minutes=10),
                "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
            },
        ]
    )

    session = auth_client.get("/api/auth/session")
    assert "local-login" in {
        operation["rel"] for operation in session.json["operations"]
    }

    expired = auth_client.post(
        "/api/auth/local-login",
        json={"token": "expired-secret"},
        headers={"Origin": "http://localhost:3000"},
    )
    invalid = auth_client.post(
        "/api/auth/local-login",
        json={"token": "wrong-secret"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert expired.status_code == invalid.status_code == 401
    assert expired.json == invalid.json

    response = auth_client.post(
        "/api/auth/local-login",
        json={"token": raw_token},
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 200
    assert response.json["state"]["status"] == "authenticated"
    assert response.json["state"]["principal"]["id"] == "owner"
    cookie = response.headers["Set-Cookie"]
    raw_session = cookie.split("=", 1)[1].split(";", 1)[0]
    stored_session = database.auth_sessions.find_one(
        {"_id": token_digest(raw_session)}
    )
    assert stored_session["authentication_method"] == "local-development-token"
    assert database.auth_local_login_tokens.find_one(
        {"_id": token_digest(raw_token)}
    ) is None

    auth_client.delete_cookie("inventorius_session")
    reused = auth_client.post(
        "/api/auth/local-login",
        json={"token": raw_token},
        headers={"Origin": "http://localhost:3000"},
    )
    assert reused.status_code == 401
    assert reused.json == invalid.json


def test_every_unsafe_api_route_has_an_explicit_authority_classification():
    unsafe_methods = {"POST", "PUT", "PATCH", "DELETE"}
    unclassified = []
    for rule in app.url_map.iter_rules():
        methods = rule.methods & unsafe_methods
        if not rule.rule.startswith("/api") or not methods:
            continue
        view = app.view_functions[rule.endpoint]
        if not (
            getattr(view, "inventorius_authority_checked", False)
            or getattr(view, "inventorius_public_unsafe", False)
        ):
            unclassified.append((sorted(methods), rule.rule))

    assert unclassified == []


def _create_access_token(auth_client, monkeypatch, **payload):
    _, registered = _register_owner(auth_client, monkeypatch)
    return auth_client.post(
        "/api/auth/access-tokens",
        json=payload,
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": registered.json["state"]["csrf_token"],
        },
    )


def test_access_token_creation_requires_a_recent_browser_session(auth_client, monkeypatch):
    anonymous = auth_client.post(
        "/api/auth/access-tokens",
        json={},
        headers={"Origin": ORIGIN},
    )
    assert anonymous.status_code == 401
    assert anonymous.json["type"] == "authentication-required"

    _, registered = _register_owner(auth_client, monkeypatch)
    database = get_test_database()
    current = database.auth_sessions.find_one(
        {"csrf_token": registered.json["state"]["csrf_token"]}
    )
    database.auth_sessions.update_one(
        {"_id": current["_id"]},
        {"$set": {"recent_auth_at": _past_recent_authentication()}},
    )
    stale = auth_client.post(
        "/api/auth/access-tokens",
        json={},
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": registered.json["state"]["csrf_token"],
        },
    )
    assert stale.status_code == 401
    assert stale.json["type"] == "recent-authentication-required"


def test_access_token_secret_is_returned_once_and_only_its_digest_is_stored(
    auth_client, monkeypatch
):
    created = _create_access_token(
        auth_client,
        monkeypatch,
        label="Workshop reviewer",
    )
    assert created.status_code == 201
    state = created.json["state"]
    raw_token = state["secret"]
    assert raw_token.startswith("ivt_")
    assert state["token"]["label"] == "Workshop reviewer"
    assert state["token"]["capabilities"] == [
        "inventory:read",
        "catalog.mutate",
        "schema.admin",
    ]
    expires_at = datetime.fromisoformat(
        state["token"]["expires_at"].replace("Z", "+00:00")
    )
    created_at = datetime.fromisoformat(
        state["token"]["created_at"].replace("Z", "+00:00")
    )
    assert timedelta(days=29, hours=23) < expires_at - created_at <= timedelta(days=30)

    stored = get_test_database().auth_access_tokens.find_one(
        {"token_id": state["token"]["id"]}
    )
    assert stored["_id"] == token_digest(raw_token)
    assert raw_token not in repr(stored)

    listed = auth_client.get("/api/auth/access-tokens")
    assert listed.status_code == 200
    assert listed.json["state"]["tokens"] == [state["token"]]
    assert "secret" not in repr(listed.json)
    assert stored["_id"] not in repr(listed.json)


def test_access_token_has_scoped_bearer_authority_without_account_security_access(
    auth_client, monkeypatch
):
    created = _create_access_token(auth_client, monkeypatch)
    raw_token = created.json["state"]["secret"]
    bearer = {"Authorization": f"Bearer {raw_token}"}

    session = auth_client.get("/api/auth/session", headers=bearer)
    assert session.status_code == 200
    assert session.json["state"] == {
        "status": "authenticated",
        "principal": {
            "id": created.json["state"]["token"]["id"],
            "display_name": "Inventory Assistant",
            "kind": "application",
        },
        "csrf_token": None,
    }
    assert session.json["operations"] == []

    root = auth_client.get("/api/", headers=bearer)
    assert {operation["rel"] for operation in root.json["operations"]} == {
        "create-bin",
        "create-sku",
        "create-batch",
        "define-process",
        "schema-admin",
    }
    catalog = auth_client.post(
        "/api/bins",
        headers={**bearer, "Origin": ORIGIN},
    )
    assert catalog.status_code == 400
    assert catalog.json["type"] != "csrf-rejected"

    stock = auth_client.post(
        "/api/intake",
        headers={**bearer, "Origin": ORIGIN},
    )
    assert stock.status_code == 403
    assert stock.json["type"] == "capability-required"

    account_inventory = auth_client.get("/api/auth/access-tokens", headers=bearer)
    assert account_inventory.status_code == 401
    sessions = auth_client.get("/api/auth/sessions", headers=bearer)
    assert sessions.status_code == 401
    create = auth_client.post(
        "/api/auth/access-tokens",
        json={},
        headers={**bearer, "Origin": ORIGIN},
    )
    assert create.status_code == 401


def test_access_token_can_opt_into_inventory_mutation_authority(
    auth_client, monkeypatch
):
    created = _create_access_token(
        auth_client, monkeypatch, allow_inventory_changes=True
    )
    raw_token = created.json["state"]["secret"]
    bearer = {"Authorization": f"Bearer {raw_token}", "Origin": ORIGIN}

    assert created.json["state"]["token"]["capabilities"] == [
        "inventory:read",
        "catalog.mutate",
        "schema.admin",
        "inventory.mutate",
    ]

    # An absent idempotency key reaches the command's request validation,
    # proving this scoped bearer passed the inventory.mutate boundary.
    receipt = auth_client.post("/api/inventory-operations", headers=bearer)
    assert receipt.status_code == 400
    assert receipt.json["invalid-params"] == [{
        "name": "Idempotency-Key", "reason": "header is required",
    }]


@pytest.mark.parametrize("value", ["true", 1, None, []])
def test_access_token_rejects_non_boolean_inventory_change_permission(
    auth_client, monkeypatch, value
):
    created = _create_access_token(
        auth_client, monkeypatch, allow_inventory_changes=value
    )

    assert created.status_code == 400
    assert created.json["type"] == "invalid-inventory-changes"


def test_access_token_requires_exact_origin_and_revocation_is_immediate(
    auth_client, monkeypatch
):
    created = _create_access_token(auth_client, monkeypatch)
    raw_token = created.json["state"]["secret"]
    token_id = created.json["state"]["token"]["id"]
    bearer = {"Authorization": f"Bearer {raw_token}"}

    wrong_origin = auth_client.post(
        "/api/bins",
        headers={**bearer, "Origin": "https://evil.example"},
    )
    assert wrong_origin.status_code == 403
    assert wrong_origin.json["type"] == "origin-mismatch"

    csrf = auth_client.get("/api/auth/session").json["state"]["csrf_token"]
    revoked = auth_client.delete(
        f"/api/auth/access-tokens/{token_id}",
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert revoked.status_code == 200
    assert revoked.json["state"]["token"]["revoked"] is True
    assert "secret" not in repr(revoked.json)

    rejected = auth_client.post(
        "/api/bins",
        headers={**bearer, "Origin": ORIGIN},
    )
    assert rejected.status_code == 401
    assert rejected.json["type"] == "authentication-required"


def test_expired_access_token_is_rejected(auth_client, monkeypatch):
    created = _create_access_token(auth_client, monkeypatch, expires_in_days=1)
    raw_token = created.json["state"]["secret"]
    get_test_database().auth_access_tokens.update_one(
        {"_id": token_digest(raw_token)},
        {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
    )

    response = auth_client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert response.status_code == 200
    assert response.json["state"] == {"status": "anonymous", "principal": None}


def test_unclassified_unsafe_api_route_fails_closed(monkeypatch):
    monkeypatch.setattr(
        auth_package, "current_actor", lambda: SimpleNamespace()
    )
    isolated_app = Flask("fail-closed-auth-test")
    auth_package.init_auth(isolated_app)

    @isolated_app.post("/api/unclassified")
    def unclassified():
        return {"unsafe": True}

    response = isolated_app.test_client().post("/api/unclassified")

    assert response.status_code == 500
    assert response.json["type"] == "unsafe-route-unclassified"
