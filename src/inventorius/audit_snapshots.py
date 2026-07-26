"""HTTP boundary for read-only physical audit snapshots."""

from flask import Blueprint, jsonify

from inventorius.audit_snapshot import read_audit_snapshot
from inventorius.db import db
from inventorius.util import no_cache
from inventorius.validation import validate_url_id
import inventorius.util_error_responses as problem


audit_snapshots = Blueprint("audit_snapshots", __name__)


@audit_snapshots.route("/api/audit-snapshots/<bin_id>", methods=["GET"])
@no_cache
@validate_url_id("BIN", param_name="bin_id")
def audit_snapshot_get(bin_id):
    snapshot = read_audit_snapshot(db, bin_id)
    if snapshot is None:
        return problem.missing_bin_response(bin_id)
    return jsonify({"state": snapshot})
