"""The caller's organization: its name, how long it keeps its stored invoices before they are
deleted (ADR-0039), and its key to SEF, kept sealed (ADR-0050).

Every member may see it, and whether a key to SEF is set; only an owner may set the period,
since a shorter one deletes invoices, and set or remove the key, which sends in the
organization's name. The organization is always the one the caller's access token names: a path
never names another.
"""
