"""What each role may do: the permissions, and which roles grant them (ADR-0013).

Endpoints ask for a permission, never for a role, so the policy is this one table and changes
in one place. A permission names an area and an action, ``area:action``. The owner holds every
permission there is; the other roles hold what their work needs. An API key holds some of the
permissions of the member it acts for, among those keys may hold at all (ADR-0017).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from sef_api.models import Role

__all__ = ["KEY_PERMISSIONS", "ROLE_PERMISSIONS", "Permission"]


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
    and delete the ones submitted oneself."""
    INVOICES_MANAGE = "invoices:manage"
    """Read and delete every invoice the organization stores, whoever submitted it."""
    API_KEYS_ISSUE = "api_keys:issue"
    """Issue API keys with which machine clients act for oneself, with some of one's
    permissions, and see and revoke one's own."""
    API_KEYS_MANAGE = "api_keys:manage"
    """See and revoke every API key of the organization, whoever it acts for."""
    ORGANIZATION_READ = "organization:read"
    """See the organization's name, how long it keeps its stored invoices, and whether it has a
    key to SEF."""
    ORGANIZATION_MANAGE = "organization:manage"
    """Set how long the organization keeps its stored invoices, after which they are deleted,
    and set or remove its key to SEF."""


#: What an API key may be allowed: the work on invoices that machine clients do. A key
#: administers no one and issues no keys, so that a leaked key can neither let anyone in nor
#: outlive its own revocation.
KEY_PERMISSIONS: Final[frozenset[Permission]] = frozenset(
    {Permission.INVOICES_VALIDATE, Permission.INVOICES_SUBMIT, Permission.INVOICES_MANAGE}
)


ROLE_PERMISSIONS: Final[Mapping[Role, frozenset[Permission]]] = MappingProxyType(
    {
        Role.OWNER: frozenset(Permission),
        Role.ACCOUNTANT: frozenset(
            {
                Permission.MEMBERS_READ,
                Permission.INVOICES_VALIDATE,
                Permission.INVOICES_SUBMIT,
                Permission.INVOICES_MANAGE,
                Permission.API_KEYS_ISSUE,
                Permission.ORGANIZATION_READ,
            }
        ),
        Role.CLIENT: frozenset(
            {
                Permission.INVOICES_VALIDATE,
                Permission.INVOICES_SUBMIT,
                Permission.API_KEYS_ISSUE,
                Permission.ORGANIZATION_READ,
            }
        ),
    }
)
