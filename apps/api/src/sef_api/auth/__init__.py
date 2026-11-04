"""Authentication: passwords, access and refresh tokens, sign-up and sign-in (ADR-0012).

A person signs in with an e-mail address and a password and receives two tokens for one of their
organizations: a short-lived JWT access token, sent as ``Authorization: Bearer`` with each
request, and an opaque refresh token that buys a new pair once and is then spent.
"""
