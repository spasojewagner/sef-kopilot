# Credentials for machines: API keys

A person signs in with a password and gets short-lived tokens. A machine, such as an ERP that
sends invoices every night, cannot type a password and should not hold one. It gets a key.

## What a key is, and how it is kept

- A long random secret: here `sefk_` and 256 bits from `secrets`, in base64url. Generate it;
  never let people choose it.
- Store a **SHA-256 digest**, never the key. A password needs a slow, salted hash (argon2id,
  note 07) because people choose guessable ones. Nobody can guess 256 random bits, so a fast
  digest is enough, and finding the key is one probe in a unique index.
- Show it **once**, in an answer marked `Cache-Control: no-store`. A lost key is replaced, not
  recovered.
- Keep a short **prefix** in clear (`sefk_AbC12x9`), so people can tell their keys apart.
- A **recognizable prefix** lets a secret scanner catch a key pasted into code: gitleaks here,
  GitHub's push protection for the big providers.

## What a key may do: least privilege twice

```text
may(p)  =  p ∈ what the member's role grants now   ∧   p ∈ what the key holds
```

- A key acts **for a member**, and never for more than that member's role grants at the moment
  of the request. Demote the member and the key shrinks; remove the member and the key is gone.
- A key holds only what it was given, and keys may only be given work on invoices. A key cannot
  invite people or issue keys, so a leaked one can neither open new doors nor outlive its own
  revocation.
- Every request asks this question again. A key's permissions are never copied into something
  that outlives the request.

## Its life

```text
issue ──▶ use: Authorization: Bearer sefk_… ──▶ rotate: issue a second, switch, revoke the first
                                            └─▶ revoke: refused on the next request
```

- Tie the key to what it belongs to in the schema. Here a foreign key to the membership, with
  `ON DELETE CASCADE`, deletes it with the membership. A person removed and invited back does
  not find their old keys working again.
- Send it in the `Authorization` header that proxies and loggers already treat as secret, not in
  a header or a query string of your own.
- Bound how many exist, under a lock, as for any quota (note 10): here 20 working keys per
  member.

## In this repository

- `apps/api/src/sef_api/api_keys/`: issuing, authenticating, listing and revoking keys.
  `auth/dependencies.py`: `Principal.may()`, and `current_principal`, which tells a key from an
  access token by its prefix.
- `apps/api/tests/test_api_keys.py`, and `test_access_control.py` for the cross-tenant cases
  with another organization's key.
- The decisions are recorded in ADR-0017.
