"""The policy: which role grants which permission."""

from __future__ import annotations

import re
import uuid
from dataclasses import replace
from typing import get_args

import pytest

from sef_api.api_keys.routes import KeyPermission
from sef_api.api_keys.service import Grant
from sef_api.auth.dependencies import Principal, require
from sef_api.auth.permissions import KEY_PERMISSIONS, ROLE_PERMISSIONS, Permission
from sef_api.models import Role


def test_every_role_has_an_entry_and_the_owner_holds_every_permission() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)
    assert ROLE_PERMISSIONS[Role.OWNER] == set(Permission)


def test_an_accountant_sees_the_members_and_a_client_does_not() -> None:
    assert Permission.MEMBERS_READ in ROLE_PERMISSIONS[Role.ACCOUNTANT]
    assert Permission.MEMBERS_READ not in ROLE_PERMISSIONS[Role.CLIENT]


def test_every_role_may_have_an_invoice_validated_and_store_invoices() -> None:
    for permission in (Permission.INVOICES_VALIDATE, Permission.INVOICES_SUBMIT):
        assert all(permission in ROLE_PERMISSIONS[role] for role in Role)
    assert ROLE_PERMISSIONS[Role.CLIENT] == {
        Permission.INVOICES_VALIDATE,
        Permission.INVOICES_SUBMIT,
        Permission.API_KEYS_ISSUE,
        Permission.ORGANIZATION_READ,
    }


def test_owners_and_accountants_read_every_stored_invoice_and_clients_their_own() -> None:
    assert [role for role in Role if Permission.INVOICES_MANAGE in ROLE_PERMISSIONS[role]] == [
        Role.OWNER,
        Role.ACCOUNTANT,
    ]


def test_owners_and_accountants_send_invoices_to_sef_and_no_key_may_yet() -> None:
    assert [role for role in Role if Permission.INVOICES_SEND in ROLE_PERMISSIONS[role]] == [
        Role.OWNER,
        Role.ACCOUNTANT,
    ]
    assert Permission.INVOICES_SEND not in KEY_PERMISSIONS


def test_only_owners_manage_members() -> None:
    assert [role for role in Role if Permission.MEMBERS_MANAGE in ROLE_PERMISSIONS[role]] == [
        Role.OWNER
    ]


@pytest.mark.parametrize("role", list(Role))
def test_a_caller_may_do_what_their_role_grants(role: Role) -> None:
    caller = Principal(uuid.uuid4(), uuid.uuid4(), role)

    assert {permission for permission in Permission if caller.may(permission)} == (
        ROLE_PERMISSIONS[role]
    )


def test_every_member_sees_how_long_invoices_are_kept_and_only_owners_set_it() -> None:
    assert all(Permission.ORGANIZATION_READ in ROLE_PERMISSIONS[role] for role in Role)
    assert [role for role in Role if Permission.ORGANIZATION_MANAGE in ROLE_PERMISSIONS[role]] == [
        Role.OWNER
    ]


def test_every_role_may_issue_api_keys_and_only_owners_see_everyones() -> None:
    assert all(Permission.API_KEYS_ISSUE in ROLE_PERMISSIONS[role] for role in Role)
    assert [role for role in Role if Permission.API_KEYS_MANAGE in ROLE_PERMISSIONS[role]] == [
        Role.OWNER
    ]


def test_a_key_may_hold_only_permissions_for_work_on_invoices() -> None:
    assert set(KEY_PERMISSIONS) == {
        Permission.INVOICES_VALIDATE,
        Permission.INVOICES_SUBMIT,
        Permission.INVOICES_MANAGE,
    }
    assert set(get_args(KeyPermission)) == {permission.value for permission in KEY_PERMISSIONS}


def test_a_caller_with_a_key_may_do_what_both_their_role_and_the_key_allow() -> None:
    key = Grant(uuid.uuid4(), frozenset({Permission.INVOICES_SUBMIT, Permission.INVOICES_MANAGE}))
    caller = Principal(uuid.uuid4(), uuid.uuid4(), Role.ACCOUNTANT, key)
    demoted = replace(caller, role=Role.CLIENT)

    assert {permission for permission in Permission if caller.may(permission)} == {
        Permission.INVOICES_SUBMIT,
        Permission.INVOICES_MANAGE,
    }
    assert {permission for permission in Permission if demoted.may(permission)} == {
        Permission.INVOICES_SUBMIT
    }


def test_permissions_are_named_area_colon_action() -> None:
    for permission in Permission:
        assert re.fullmatch(r"[a-z_]+:[a-z_]+", permission.value), permission


def test_the_policy_cannot_be_changed_at_run_time() -> None:
    with pytest.raises(TypeError):
        ROLE_PERMISSIONS[Role.CLIENT] = frozenset(Permission)  # type: ignore[index]


def test_there_is_one_dependency_per_permission_and_variant() -> None:
    reading = require(Permission.MEMBERS_MANAGE)

    assert reading is require(Permission.MEMBERS_MANAGE, changes_members=False)
    assert reading is not require(Permission.MEMBERS_MANAGE, changes_members=True)
    assert reading is not require(Permission.MEMBERS_READ)
