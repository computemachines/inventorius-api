"""Authenticated HTTP access to persistence-free constraint queries."""

from flask import Blueprint, jsonify, request

from inventorius.auth import require_capability
from inventorius.constraint_queries import ConstraintQueryEvaluator
from inventorius.constraint_query_codec import (
    query_request_from_document,
    query_result_document,
)
from inventorius.util import no_cache
import inventorius.util_error_responses as problem


constraint_query_routes = Blueprint("constraint_query_routes", __name__)


@constraint_query_routes.route("/api/solver/query", methods=["POST"])
@require_capability("solver.query")
@no_cache
def solver_query_post():
    """Evaluate one supplied snapshot and disposable overlay without mutation."""

    body = request.get_json(silent=True)
    try:
        snapshot, overlay, query = query_request_from_document(body)
        result = ConstraintQueryEvaluator().evaluate(
            snapshot,
            query,
            overlay=overlay,
        )
    except ValueError as error:
        return problem.invalid_params_response_simple("body", str(error))
    return jsonify({"state": {"result": query_result_document(result)}})
