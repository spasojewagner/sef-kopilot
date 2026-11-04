"""What each role may do: the permissions, and which roles grant them (ADR-0013).

Endpoints ask for a permission, never for a role, so the policy is this one table and changes
in one place. A permission names an area and an action, ``area:action``. The owner holds every
permission there is; the other roles hold what their work needs.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from sef_api.models import Role

__all__ = ["ROLE_PERMISSIONS", "Permission"]


class Permission(StrEnum):
    """Something a member may be allowed to do in their organization."""

    MEMBERS_READ = "members:read"
    """See the organization's members and their roles."""
    MEMBERS_MANAGE = "members:manage"
    """Invite people, change members' roles and remove members."""
    INVOICES_VALIDATE = "invoices:validate"
    """Have an invoice checked by the validator."""
    INVOICES_SUBMIT = "invoices:submit"
    """Store invoices in the organization, each with the validator's report on it, and read
    the ones submitted oneself."""
    INVOICES_MANAGE = "invoices:manage"
    """Read every invoice the organization stores, whoever submitted it."""


ROLE_PERMISSIONS: Final[Mapping[Role, frozenset[Permission]]] = MappingProxyType(
    {
        Role.OWNER: frozenset(Permission),
        Role.ACCOUNTANT: frozenset(
            {
                Permission.MEMBERS_READ,
                Permission.INVOICES_VALIDATE,
                Permission.INVOICES_SUBMIT,
                Permission.INVOICES_MANAGE,
            }
        ),
        Role.CLIENT: frozenset({Permission.INVOICES_VALIDATE, Permission.INVOICES_SUBMIT}),
    }
)
