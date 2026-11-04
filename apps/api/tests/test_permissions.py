"""The policy: which role grants which permission."""

from __future__ import annotations

import re

import pytest

from sef_api.auth.dependencies import require
from sef_api.auth.permissions import ROLE_PERMISSIONS, Permission
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
    }


def test_owners_and_accountants_read_every_stored_invoice_and_clients_their_own() -> None:
    assert [role for role in Role if Permission.INVOICES_MANAGE in ROLE_PERMISSIONS[role]] == [
        Role.OWNER,
        Role.ACCOUNTANT,
    ]


def test_only_owners_manage_members() -> None:
    assert [role for role in Role if Permission.MEMBERS_MANAGE in ROLE_PERMISSIONS[role]] == [
        Role.OWNER
    ]


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
