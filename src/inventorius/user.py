from flask import Blueprint, request, Response, url_for, session, make_response, current_app, app
from flask.ctx import after_this_request
import flask_login
from flask_login import current_user
from flask_principal import Permission, UserNeed, identity_changed, Identity, AnonymousIdentity, identity_loaded
from json import dumps
import os
import hashlib
import random
import time
import base64
from voluptuous import MultipleInvalid
from werkzeug.wrappers import response

from inventorius.data_models import Batch, Bin, Sku, DataModelJSONEncoder as Encoder, UserData
from inventorius.db import db
from inventorius.util import admin_increment_code, check_code_list, login_manager, no_cache, principals, admin_permission
import inventorius.util_error_responses as problem
import inventorius.util_success_responses as success
from inventorius.validation import new_user_schema, user_patch_schema, login_request_schema
from inventorius.resource_models import PrivateProfile, Profile

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
        identity_changed.send(current_app._get_current_object(),
                              identity=Identity(user_data.fixed_id))
        return User.from_user_data(user_data)
    else:
        session.pop("identity.name", None)
        session.pop("identity.auth_type", None)
        identity_changed.send(current_app._get_current_object(), identity=AnonymousIdentity())

        return None


def on_identity_loaded(sender, identity):
    if identity.id:
        identity.provides.add(UserNeed(identity.id))
identity_loaded.connect(on_identity_loaded)

def login_dangerous(user, remember=False):
    if flask_login.login_user(user, remember=remember):
        identity_changed.send(current_app._get_current_object(),
                              identity=Identity(user.user_data.fixed_id))
        return True
    else:
        return False


def logout_dangerous():
    session.pop("identity.name", None)
    session.pop("identity.auth_type", None)
    flask_login.logout_user()
    identity_changed.send(current_app._get_current_object(), identity=AnonymousIdentity())


def set_password_dangerous(id, password):
    """Set the password for any user. Does not check permissions. Also changes shadow_id, forcing all sessions to reauthenticate."""

    derived_shadow_id = hashlib.sha256((str(time.time()) + id).encode("utf-8"))
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
@no_cache
def login_post():
    try:
        json = login_request_schema(request.get_json())
    except MultipleInvalid as e:
        return problem.invalid_params_response(e, status_code=401)

    requested_user_data = UserData.from_mongodb_doc(
        db.user.find_one({"_id": json['id']}))
    if requested_user_data is None:
        return problem.bad_username_password_response("id")

    request_hashed_password = hashlib.pbkdf2_hmac("sha256", str(
        json['password']).encode("utf-8"), requested_user_data.password_salt, 100000)
    if requested_user_data.password_hash != request_hashed_password:
        return problem.bad_username_password_response("password")

    user = User.from_user_data(requested_user_data)
    if login_dangerous(user):
        return Profile.from_user_data(requested_user_data).login_success_response()
    else:
        return problem.deactivated_account(user.user_data.fixed_id)


@ user.route("/api/whoami", methods=["GET"])
@no_cache
def whoami():
    resp = Response()
    resp.mimetype = "application/json"

    data = {"id": None}

    if current_user.is_authenticated:
        data["id"] = current_user.user_data.fixed_id
    resp.data = dumps(data)
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
@no_cache
def users_post():
    try:
        json = new_user_schema(request.get_json())
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)

    existing_user = db.user.find_one({"_id": json["id"]})
    if existing_user:
        return problem.duplicate_resource_response("id")

    derived_shadow_id = hashlib.sha256((str(time.time()) + str(json['id'])).encode("utf-8"))
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
    return Profile.from_user_data(user_data).created_success_response()


@ user.route("/api/user/<id>", methods=["PATCH"])
@no_cache
def user_patch(id):
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

    return Profile.from_user_data(existing).updated_success_response()


@ user.route("/api/user/<id>", methods=["GET"])
def user_get(id):

    UserPermission = Permission(UserNeed(id))

    public_profile = Profile.from_id(id, retrieve=True)
    private_profile = PrivateProfile.from_id(id, retrieve=True)
    if public_profile and private_profile:
        if UserPermission.can():
            return private_profile.get_response()
        else:
            return public_profile.get_response()
    else:
        resp = problem.missing_user_response(id)
        return resp


@ user.route("/api/user/<id>", methods=["DELETE"])
def user_delete(id):
    @ after_this_request
    def no_cache(resp):
        resp.headers.add("Cache-Control", "no-cache")
        return resp

    if current_user.is_authenticated and current_user.user_data.fixed_id == id:

        logout_dangerous()
    if not db.user.find_one({"_id": id}):
        return problem.missing_user_response(id)
    db.user.delete_one({"_id": id})
    return Profile(id).deleted_success_response()

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
        logout_dangerous()
        return success.logged_out_response()
    else:
        return success.already_logged_out()


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
