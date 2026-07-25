"""Narrow boundary around py_webauthn, mockable by route tests."""

from __future__ import annotations

import json

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)


def registration_options(
    *,
    rp_id: str,
    rp_name: str,
    user_id: bytes,
    user_name: str,
    user_display_name: str,
    challenge: bytes,
    exclude_credential_ids: list[bytes],
) -> dict:
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_id=user_id,
        user_name=user_name,
        user_display_name=user_display_name,
        challenge=challenge,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=credential_id)
            for credential_id in exclude_credential_ids
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return json.loads(options_to_json(options))


def verify_registration(**kwargs):
    return verify_registration_response(
        **kwargs,
        require_user_verification=True,
    )


def authentication_options(
    *,
    rp_id: str,
    challenge: bytes,
    credential_ids: list[bytes],
) -> dict:
    options = generate_authentication_options(
        rp_id=rp_id,
        challenge=challenge,
        # An empty list enables discoverable credentials and hybrid passkeys.
        allow_credentials=[],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return json.loads(options_to_json(options))


def verify_authentication(**kwargs):
    return verify_authentication_response(
        **kwargs,
        require_user_verification=True,
    )
