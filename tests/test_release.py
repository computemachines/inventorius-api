import json

import inventorius as api_module
from inventorius.release import metadata
from inventorius.resource_models import StatusEndpoint
from inventorius import app


def write_manifest(path, revision):
    path.write_text(json.dumps({
        "schema_version": 1,
        "product_release": "v0.5.0-rc.1",
        "components": {"api": {"revision": revision}},
    }))


def test_release_metadata_accepts_matching_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILD_ID", "a" * 40)
    monkeypatch.setenv("INVENTORIUS_ENVIRONMENT", "development")
    manifest = tmp_path / "release-manifest.json"
    write_manifest(manifest, "a" * 40)
    monkeypatch.setenv("INVENTORIUS_RELEASE_MANIFEST_PATH", str(manifest))

    assert metadata() == {
        "component": "inventorius-api",
        "component_version": "0.3.11",
        "revision": "a" * 40,
        "product_release": "v0.5.0-rc.1",
        "environment": "development",
    }


def test_release_metadata_falls_back_for_stale_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILD_ID", "a" * 40)
    monkeypatch.setenv("INVENTORIUS_ENVIRONMENT", "development")
    manifest = tmp_path / "release-manifest.json"
    write_manifest(manifest, "b" * 40)
    monkeypatch.setenv("INVENTORIUS_RELEASE_MANIFEST_PATH", str(manifest))

    build = metadata()

    assert build["revision"] == "a" * 40
    assert build["product_release"] == "development"


def test_release_metadata_falls_back_for_malformed_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILD_ID", "a" * 40)
    monkeypatch.setenv("INVENTORIUS_ENVIRONMENT", "development")
    manifest = tmp_path / "release-manifest.json"
    manifest.write_text("not json")
    monkeypatch.setenv("INVENTORIUS_RELEASE_MANIFEST_PATH", str(manifest))

    assert metadata()["product_release"] == "development"


def test_release_metadata_falls_back_for_missing_manifest(monkeypatch):
    monkeypatch.setenv("BUILD_ID", "a" * 40)
    monkeypatch.setenv("INVENTORIUS_ENVIRONMENT", "development")
    monkeypatch.setenv("INVENTORIUS_RELEASE_MANIFEST_PATH", "/not-present/release-manifest.json")

    assert metadata()["product_release"] == "development"


def test_sentry_tag_reads_manifest_at_request_time(tmp_path, monkeypatch):
    class FakeSentry:
        def __init__(self):
            self.tags = []

        def set_tag(self, key, value):
            self.tags.append((key, value))

    monkeypatch.setenv("BUILD_ID", "a" * 40)
    monkeypatch.setenv("INVENTORIUS_ENVIRONMENT", "development")
    manifest = tmp_path / "release-manifest.json"
    write_manifest(manifest, "a" * 40)
    monkeypatch.setenv("INVENTORIUS_RELEASE_MANIFEST_PATH", str(manifest))
    fake_sentry = FakeSentry()
    monkeypatch.setattr(api_module, "SENTRY_SDK", fake_sentry)

    with app.test_request_context():
        api_module.tag_sentry_release_context()
    write_manifest(manifest, "b" * 40)
    with app.test_request_context():
        api_module.tag_sentry_release_context()

    assert fake_sentry.tags == [
        ("product_release", "v0.5.0-rc.1"),
        ("product_release", "development"),
    ]


def test_sentry_scrubber_removes_request_and_user_material():
    event = {
        "exception": {"values": [{"type": "ExampleError"}]},
        "request": {
            "headers": {"Authorization": "secret", "Cookie": "session=secret"},
            "data": {"recovery_code": "secret"},
        },
        "user": {"email": "private@example.com"},
        "contexts": {"auth": {"challenge": "secret"}},
        "extra": {"token": "secret"},
        "breadcrumbs": [{"data": {"url": "/setup?token=secret"}}],
    }

    scrubbed = api_module.scrub_sentry_event(event, None)

    assert scrubbed == {"exception": {"values": [{"type": "ExampleError"}]}}


def test_status_endpoint_preserves_release_provenance():
    with app.test_request_context():
        response = StatusEndpoint(
            version="0.3.11",
            db_connected=True,
            build_id="a" * 40,
            component="inventorius-api",
            revision="a" * 40,
            product_release="2026.07.26",
            environment="development",
        ).get_response()

    assert response.get_json()["state"] == {
        "version": "0.3.11",
        "is-up": True,
        "db-connected": True,
        "build-id": "a" * 40,
        "component": "inventorius-api",
        "revision": "a" * 40,
        "product-release": "2026.07.26",
        "environment": "development",
    }
