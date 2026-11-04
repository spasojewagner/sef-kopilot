"""API keys: the credentials with which machine clients, such as an ERP, act for a member of an
organization with some of the member's permissions (ADR-0017).

A key works in the organization of the member who issued it, for that member, and never for
more than their role grants when it is used; a key of another organization is never found.
"""
