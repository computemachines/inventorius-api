"""Public-safe build provenance for the running API image."""

import os


COMPONENT = "inventorius-api"
VERSION = "0.3.11"


def metadata():
    """Return deployment metadata that is safe to expose from ``/api/status``."""
    return {
        "component": COMPONENT,
        "component_version": VERSION,
        "revision": os.getenv("BUILD_ID", "dev"),
        "product_release": os.getenv("INVENTORIUS_PRODUCT_RELEASE", "unassigned"),
        "environment": os.getenv("INVENTORIUS_ENVIRONMENT", "unassigned"),
    }
