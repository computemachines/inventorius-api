import functools
from flask import request
from flask.helpers import make_response
from flask_login import LoginManager
from flask_principal import Principal, Permission, RoleNeed
import re
from string import ascii_letters

from inventorius.db import db
from inventorius.validation import CANONICAL_ID_SUFFIX_WIDTH


MAX_IDENTIFIER_SUFFIX = (10 ** CANONICAL_ID_SUFFIX_WIDTH) - 1


class IdentifierSpaceExhausted(Exception):
    """The monotonic counter has no valid fixed-width identifier left."""

    def __init__(self, prefix):
        self.prefix = prefix
        super().__init__(f"{prefix} identifier space is exhausted")

login_manager = LoginManager()
principals = Principal()

admin_permission = Permission(RoleNeed("admin"))


def getIntArgs(args, name, default):
    str_value = args.get(name, default)
    try:
        value = int(str_value)
    except ValueError:
        value = default
    return value


def get_body_type():
    if request.mimetype == 'application/json':
        return 'json'
    if request.mimetype in ('application/x-www-form-urlencoded',
                            'multipart/form-data'):
        return 'form'


def owned_code_get(id):
    existing = Sku.from_mongodb_doc(
        db.sku.find_one({'owned_codes': id}))
    return existing


def _counter_state(prefix, next_number):
    exhausted = next_number > MAX_IDENTIFIER_SUFFIX
    return {
        "next": None if exhausted else (
            f"{prefix}{next_number:0{CANONICAL_ID_SUFFIX_WIDTH}d}"
        ),
        "exhausted": exhausted,
    }


def admin_increment_code(prefix, code):
    """Record that a code was used and update next if needed.

    Maintains an ordered list of all IDs ever used to ensure IDs are never reused,
    even if items are deleted.
    """
    code_number = int(re.sub('[^0-9]', '', code))

    # Ensure admin doc exists
    try:
        admin_get_next(prefix)
    except IdentifierSpaceExhausted:
        # Exhaustion stops generated IDs, not valid explicit IDs in lower gaps.
        pass

    doc = db.admin.find_one({"_id": prefix})
    used = doc.get("used", [])

    if code_number not in used:
        used.append(code_number)
        used.sort()
        max_used = max(used)
        current_next = int(re.sub('[^0-9]', '', doc['next'])) \
            if doc.get("next") else 1
        next_number = max(current_next, max_used + 1)
        if doc.get("exhausted"):
            next_number = MAX_IDENTIFIER_SUFFIX + 1
        db.admin.update_one(
            {"_id": prefix},
            {"$set": {
                "used": used,
                **_counter_state(prefix, next_number),
            }}
        )


def admin_get_next(prefix):
    """Get the next unused ID for a fixed-width resource namespace.

    Returns the next ID that has never been used, tracked via a persistent
    'used' list that survives item deletions. Raises rather than widening or
    wrapping once the six-digit namespace is exhausted.
    """
    def collect_existing_ids(collection, prefix_str):
        """One-time migration: collect all existing IDs from a collection."""
        cursor = collection.find({}, {"_id": 1})
        ids = []
        for doc in cursor:
            try:
                code_number = int(re.sub('[^0-9]', '', doc['_id']))
                ids.append(code_number)
            except (ValueError, KeyError):
                continue
        return sorted(ids)

    next_code_doc = db.admin.find_one({"_id": prefix})

    if not next_code_doc:
        # Initialize: collect existing IDs (one-time migration)
        if prefix == "SKU":
            used = collect_existing_ids(db.sku, "SKU")
        elif prefix == "BAT":
            used = collect_existing_ids(db.batch, "BAT")
        elif prefix == "BIN":
            used = collect_existing_ids(db.bin, "BIN")
        elif prefix == "PRC":
            used = collect_existing_ids(db.process_definition, "PRC")
        else:
            raise Exception("bad prefix", prefix)

        max_used = max(used) if used else 0
        db.admin.insert_one({
            "_id": prefix,
            "used": used,
            **_counter_state(prefix, max_used + 1),
        })
        next_code_doc = db.admin.find_one({"_id": prefix})

    # Migrate old docs that don't have 'used' field
    if "used" not in next_code_doc:
        if prefix == "SKU":
            used = collect_existing_ids(db.sku, "SKU")
        elif prefix == "BAT":
            used = collect_existing_ids(db.batch, "BAT")
        elif prefix == "BIN":
            used = collect_existing_ids(db.bin, "BIN")
        elif prefix == "PRC":
            used = collect_existing_ids(db.process_definition, "PRC")
        else:
            raise Exception("bad prefix", prefix)

        max_used = max(used) if used else 0
        current_next = int(re.sub('[^0-9]', '', next_code_doc['next']))
        # Keep the higher of current next or max_used + 1
        new_next = max(current_next, max_used + 1)

        db.admin.update_one(
            {"_id": prefix},
            {"$set": {
                "used": used,
                **_counter_state(prefix, new_next),
            }}
        )
        next_code_doc = db.admin.find_one({"_id": prefix})

    if next_code_doc.get("exhausted"):
        raise IdentifierSpaceExhausted(prefix)

    used = next_code_doc["used"]
    current_next = int(re.sub('[^0-9]', '', next_code_doc['next']))
    next_number = max(current_next, (max(used) + 1) if used else 1)
    state = _counter_state(prefix, next_number)
    if state["exhausted"]:
        db.admin.update_one({"_id": prefix}, {"$set": state})
        raise IdentifierSpaceExhausted(prefix)
    if state["next"] != next_code_doc["next"]:
        db.admin.update_one({"_id": prefix}, {"$set": state})

    return state["next"]


def check_code_list(codes):
    return any(re.search('\\s', code) or code == '' for code in codes)

def no_cache(view):
    @functools.wraps(view)
    def no_cache_(*args, **kwargs):
        resp = make_response(view(*args, **kwargs))
        resp.headers.add("Cache-Control", "no-cache")
        return resp
    return no_cache_
