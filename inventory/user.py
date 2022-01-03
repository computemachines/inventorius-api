from flask import Blueprint, request, Response, url_for, session, make_response
from flask_login import current_user, login_user
from flask_login.utils import login_required, logout_user
import json
import os
import hashlib
import random
import time
import base64
from voluptuous import MultipleInvalid

from inventory.data_models import Batch, Bin, Sku, DataModelJSONEncoder as Encoder, UserData
from inventory.db import db
from inventory.util import admin_increment_code, check_code_list, login_manager, principals, admin_permission
from inventory.validation import new_user_schema, problem_duplicate_resource_response, problem_invalid_params_response, problem_missing_user_response
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


# @user.route("/api/admin-secret")
# @admin_permission.require(http_exception=403)
# def admin_secret():
#     return Response("admin secrets")


@user.route("/api/login", methods=["POST"])
def login_post():
    resp = Response()

    json = request.get_json()

    requested_user_data = UserData.from_mongodb_doc(
        db.user.find_one({"_id": json['id']}))
    if requested_user_data is None:
        resp.status_code = 401
        resp.data = "bad username"
        return resp

    request_hashed_password = hashlib.pbkdf2_hmac("sha256", str(
        json['password']).encode("utf-8"), requested_user_data.password_salt, 100000)
    if requested_user_data.password_hash != request_hashed_password:
        resp.status_code = 401
        resp.data = "bad password"
        return resp

    user = User.from_user_data(requested_user_data)
    if login_user(user):
        resp.status_code = 201
        resp.data = "logged in"
        return resp
    else:
        resp.status_code = 401
        resp.data = "user is inactive"
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


@user.route("/api/users", methods=["POST"])
def users_post():
    resp = Response()
    try:
        json = new_user_schema(request.get_json())
    except MultipleInvalid as e:
        return problem_invalid_params_response(e)

    existing_user = db.user.find_one({"_id": json["id"]})
    if existing_user:
        return problem_duplicate_resource_response("id")

    salt = os.urandom(64)
    derived_shadow_id = hashlib.sha256((str(time.time()) + str(json['id'])).encode("utf-8"),
                               usedforsecurity=False)
    clipped_shadow_id = base64.encodebytes(derived_shadow_id.digest()).decode("ascii")[:16]
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
    )
    db.user.insert_one(user_data.to_mongodb_doc())
    resp.status_code = 201
    resp.data = "user created"
    return resp


@user.route("/api/user/<id>", methods=["GET"])
def user_get(id):
    public_profile = PublicProfile.retrieve_from_id(id)
    if public_profile:
        return public_profile.hypermedia_response()
    else:
        resp = problem_missing_user_response(id)
        return resp

# @user.route("/api/user/<user_id>/activate", methods=["POST"])
# def user_activate_post(user_id):
#     resp = Response()
#     db.user.update_one({"_id": user_id}, {"$set": {"active": True}})
#     resp.status_code = 201
#     resp.data = "activated user"
#     return resp


@user.route("/api/user/<id>", methods=["DELETE"])
def user_delete(id):
    resp = Response()
    if current_user.is_authenticated and current_user.userdata.id == id:
        logout_user()
    if not db.user.find_one({"_id": id}):
        return problem_missing_user_response(id)
    db.user.delete_one({"_id": id})
    resp.status_code = 204
    return resp


# @user.route("/api/private-report", methods=["GET"])
# @login_required
# def private_report_get():
#     return {"secret": "information", "userId": current_user.user_data.fixed_id}


@user.route('/api/logout', methods=["GET"])
def logout_get():
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
