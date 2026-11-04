"""The people of an organization: its members, their roles and the invitations to join it
(ADR-0013).

Every operation runs in the caller's organization, the one their access token names; a member
or an invitation of another organization is not found, never forbidden, so nothing reveals what
exists elsewhere.
"""
