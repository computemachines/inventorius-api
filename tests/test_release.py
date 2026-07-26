from inventorius.release import metadata
from inventorius.resource_models import StatusEndpoint
from inventorius import app


def test_release_metadata_uses_runtime_product_context(monkeypatch):
    monkeypatch.setenv("BUILD_ID", "a" * 40)
    monkeypatch.setenv("INVENTORIUS_PRODUCT_RELEASE", "2026.07.26")
    monkeypatch.setenv("INVENTORIUS_ENVIRONMENT", "development")

    assert metadata() == {
        "component": "inventorius-api",
        "component_version": "0.3.11",
        "revision": "a" * 40,
        "product_release": "2026.07.26",
        "environment": "development",
    }


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
