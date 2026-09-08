"""Opaque validators and Mongo compare-and-swap filters for catalog edits."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Iterable


CAPABILITY_HEADER = "Inventory-Edit-Preconditions"
CAPABILITY_VALUE = "etag-v1"


def etag_for_state(namespace: str, state: Any) -> str:
    """Return a strong, deterministic ETag for one editable representation."""
    canonical = json.dumps(
        {"namespace": namespace, "state": state},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f'"inventory-etag-v1-{sha256(canonical).hexdigest()}"'


def advertise(response, etag: str):
    response.headers["ETag"] = etag
    response.headers[CAPABILITY_HEADER] = CAPABILITY_VALUE
    return response


def supplied_if_match() -> str | None:
    from flask import request

    return request.headers.get("If-Match")


def matches_if_supplied(current_etag: str) -> bool:
    supplied = supplied_if_match()
    return supplied is None or supplied.strip() == current_etag


def exact_document_filter(
    identifier: str,
    observed: dict[str, Any],
    mutable_fields: Iterable[str],
) -> dict[str, Any]:
    """Match the observed editable document, including absent fields.

    This filter is used only when a caller supplied If-Match. It closes the
    gap between validating the tag and applying the update without requiring a
    stored revision field on legacy catalog documents.
    """
    clauses: list[dict[str, Any]] = [{"_id": identifier}]
    for field in mutable_fields:
        if field == "_id":
            continue
        if field in observed:
            clauses.append({field: observed[field]})
        else:
            clauses.append({field: {"$exists": False}})
    return {"$and": clauses}


def failed_response():
    from inventorius.util_error_responses import problem_response

    return problem_response(status_code=412, json={
        "type": "edit-precondition-failed",
        "title": "The resource changed. Reload it and try again.",
    })
