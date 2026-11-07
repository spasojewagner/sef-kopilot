"""The caller's organization: its name, and how long it keeps its stored invoices before they are
deleted (ADR-0039).

Every member may see it; only an owner may set the period, since a shorter one deletes invoices.
The organization is always the one the caller's access token names: a path never names another.
"""
