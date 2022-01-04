from flask import Blueprint, request, Response, url_for, session, make_response
from flask.ctx import after_this_request
from flask_login import current_user, login_user
from flask_login.utils import login_required, logout_user
from json import dumps
import os
import hashlib
import random
import time
import base64
from voluptuous import MultipleInvalid
from werkzeug.wrappers import response

from inventory.data_models import Batch, Bin, Sku, DataModelJSONEncoder as Encoder, UserData
from inventory.db import db
from inventory.util import admin_increment_code, check_code_list, login_manager, principals, admin_permission
import inventory.util_error_responses as problem
import inventory.util_success_responses as success
from inventory.validation import new_user_schema, user_patch_schema, login_request_schema
from inventory.resource_models import PublicProfile

user = Blueprint("user", __name__)


class User:
    @classmethod
    def from_user_data(cls, user_data):
        if user_data is None:
            return None
        user = cls()
        user.valid_shadow_id = user_data.shadow_id
        user.user_data = user_data
        user.is_active = user_data.active
        user.is_authenticated = True
        user.is_anonymous = False
        return user

    def __init__(self) -> None:
        # sensible defaults
        self.is_authenticated = False
        self.is_active = False
        self.is_anonymous = True

    def get_id(self):
        return self.valid_shadow_id


@login_manager.user_loader
def load_user(shadow_id):
    user_data = UserData.from_mongodb_doc(
        db.user.find_one({"shadow_id": shadow_id}))
    if user_data:
        return User.from_user_data(user_data)
    else:
        return None


def set_password_dangerous(id, password):
    """Set the password for any user. Does not check permissions. Also changes shadow_id, forcing all sessions to reauthenticate."""

    derived_shadow_id = hashlib.sha256((str(time.time()) + id).encode("utf-8"),
                                       usedforsecurity=False)
    clipped_shadow_id = base64.encodebytes(
        derived_shadow_id.digest()).decode("ascii")[:16]

    salt = os.urandom(64)
    db.user.update_one({"_id": id}, {
        "$set": {
            "shadow_id": clipped_shadow_id,
            "password_hash": hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                100000),
            "password_salt": salt,
        }
    })


# @user.route("/api/admin-secret")
# @admin_permission.require(http_exception=403)
# def admin_secret():
#     return Response("admin secrets")


@ user.route("/api/login", methods=["POST"])
def login_post():
    @ after_this_request
    def no_cache(resp):
        resp.headers.add("Cache-Control", "no-cache")
        return resp

    try:
        json = login_request_schema(request.get_json())
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)

    requested_user_data = UserData.from_mongodb_doc(
        db.user.find_one({"_id": json['id']}))
    if requested_user_data is None:
        return problem.bad_username_password_response("id")

    request_hashed_password = hashlib.pbkdf2_hmac("sha256", str(
        json['password']).encode("utf-8"), requested_user_data.password_salt, 100000)
    if requested_user_data.password_hash != request_hashed_password:
        return problem.bad_username_password_response("password")

    user = User.from_user_data(requested_user_data)
    if login_user(user):
        return success.login_response(user.user_data.fixed_id)
    else:
        return problem.deactivated_account(user.user_data.fixed_id)


@ user.route("/api/whoami", methods=["GET"])
def whoami():
    @ after_this_request
    def no_cache(resp):
        resp.headers.add("Cache-Control", "no-cache")
        return resp

    resp = Response()
    resp.mimetype = "application/json"
    if current_user.is_authenticated:
        resp.data = dumps({"id": current_user.user_data.fixed_id})
    else:
        resp.data = dumps({"id": None})
    return resp

# @user.route("/api/profile", methods=["GET"])
# def profile_get():
#     resp = Response()
#     resp.status_code = 200
#     # resp.data = json.dumps({
#     #     "is_authenticated": current_user.is_authenticated,
#     #     "is_active": current_user.is_active,
#     #     "is_anonymous": current_user.is_anonymous,
#     #     "current_user.shadow_id": current_user.get_id(),
#     #     "current_user.fixed_id": hasattr(current_user, 'user_data') and current_user.user_data.fixed_id,
#     #     "current_user.name": hasattr(current_user, 'user_data') and current_user.user_data.name,
#     # })
#     return resp


@ user.route("/api/users", methods=["POST"])
def users_post():
    @ after_this_request
    def no_cache(resp):
        resp.headers.add("Cache-Control", "no-cache")
        return resp

    try:
        json = new_user_schema(request.get_json())
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)

    existing_user = db.user.find_one({"_id": json["id"]})
    if existing_user:
        return problem.duplicate_resource_response("id")

    derived_shadow_id = hashlib.sha256((str(time.time()) + str(json['id'])).encode("utf-8"),
                                       usedforsecurity=False)
    clipped_shadow_id = base64.encodebytes(
        derived_shadow_id.digest()).decode("ascii")[:16]

    salt = os.urandom(64)
    user_data = UserData(
        fixed_id=json['id'],
        shadow_id=clipped_shadow_id,
        password_hash=hashlib.pbkdf2_hmac(
            "sha256",
            json['password'].encode("utf-8"),
            salt,
            100000),
        password_salt=salt,
        name=json['name'],
        active=True,
    )
    db.user.insert_one(user_data.to_mongodb_doc())
    return success.user_created_response(user_data.fixed_id)


@ user.route("/api/user/<id>", methods=["PATCH"])
def user_patch(id):
    @ after_this_request
    def no_cache(resp):
        resp.headers.add("Cache-Control", "no-cache")
        return resp

    try:
        patch = user_patch_schema(request.get_json())
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)

    existing = UserData.from_mongodb_doc(db.user.find_one({"_id": id}))
    if not existing:
        return problem.invalid_params_response(problem.missing_resource_param_error("id", "user does not exist"), status_code=404)

    if "name" in patch:
        db.user.update_one({"_id": id}, {"$set": {"name": patch["name"]}})
    if "password" in patch:
        set_password_dangerous(id, patch["password"])

    return success.user_updated_response(id)


@ user.route("/api/user/<id>", methods=["GET"])
def user_get(id):
    public_profile = PublicProfile.retrieve_from_id(id)
    if public_profile:
        return public_profile.hypermedia_response()
    else:
        resp = problem.missing_user_response(id)
        return resp


@ user.route("/api/user/<id>", methods=["DELETE"])
def user_delete(id):
    @ after_this_request
    def no_cache(resp):
        resp.headers.add("Cache-Control", "no-cache")
        return resp

    resp = Response()
    if current_user.is_authenticated and current_user.userdata.id == id:
        logout_user()
    if not db.user.find_one({"_id": id}):
        return problem.missing_user_response(id)
    db.user.delete_one({"_id": id})
    resp.status_code = 204
    return resp

# @user.route("/api/private-report", methods=["GET"])
# @login_required
# def private_report_get():
#     return {"secret": "information", "userId": current_user.user_data.fixed_id}


@ user.route('/api/logout', methods=["POST"])
def logout_post():
    @ after_this_request
    def no_cache(resp):
        resp.headers.add("Cache-Control", "no-cache")
        return resp

    if current_user.is_authenticated:
        return "Logged out"
    else:
        return "Already logged out"


# @user.route("/api/users", methods=["GET"])
# def users_get():
#     mongo_users = db.user.find({})
#     users = []
#     for mongo_user in mongo_users:
#         ud = UserData.from_mongodb_doc(mongo_user)
#         users.append({
#             "active": ud.active,
#             "fixed_id": ud.fixed_id,
#             "name": ud.name,
#             "password_hash": str(ud.password_hash),
#             "password_salt": str(ud.password_salt),
#             "shadow_id": ud.shadow_id
#         })
#     return json.dumps(users)
