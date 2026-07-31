"""Public-safe build provenance for the running API image."""

import json
import os
from pathlib import Path


COMPONENT = "inventorius-api"
VERSION = "0.4.1"
MANIFEST_COMPONENT = "api"


def product_release(revision, environment):
    """Return a release only when this immutable image is in its manifest.

    The manifest is deliberately read for every call: a deployment coordinator can
    atomically publish or withdraw release state without rebuilding this image.
    Invalid or stale state is public-safe and fails closed to the environment.
    """
    manifest_path = os.getenv("INVENTORIUS_RELEASE_MANIFEST_PATH")
    if not manifest_path:
        return environment

    try:
        manifest = json.loads(Path(manifest_path).read_text())
        component = manifest["components"][MANIFEST_COMPONENT]
        release = manifest["product_release"]
    except (OSError, TypeError, ValueError, KeyError):
        return environment

    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or not isinstance(component, dict)
        or component.get("revision") != revision
        or not isinstance(release, str)
        or not release
    ):
        return environment

    return release


def metadata():
    """Return deployment metadata that is safe to expose from ``/api/status``."""
    revision = os.getenv("BUILD_ID", "dev")
    environment = os.getenv("INVENTORIUS_ENVIRONMENT", "unassigned")
    return {
        "component": COMPONENT,
        "component_version": VERSION,
        "revision": revision,
        "product_release": product_release(revision, environment),
        "environment": environment,
    }
