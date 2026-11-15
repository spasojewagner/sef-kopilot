# 67. Changing a password replaces the account's web sessions

- Status: accepted
- Date: 2026-11-15
- Deciders: Marko Spasojević
- Technical story: branch `feat/account-rename-and-password`; extends ADR-0012, ADR-0018 and
  ADR-0024

## Context and problem statement

A person may change their password because someone else knows it. That person may already have
signed in, including under another organization. An organization name may also contain a
secret entered by mistake before the registration rules checked for it.

## Decision drivers

- A new password takes effect for every organization the person belongs to.
- The browser that confirmed the current password can continue with a new session.
- The organization can see who renamed it without retaining either name in the audit log.

## Considered options

1. Revoke the account's refresh tokens and let outstanding access tokens expire.
2. Revoke the refresh tokens and invalidate outstanding web access tokens immediately. Chosen.

## Decision outcome

Change the argon2id hash, advance the account's password version, revoke every web refresh
token for that account and issue a new pair for the current organization in one transaction.
A lock on the account serialises sign-in, invitation acceptance and refresh with the change.
The API checks the password version of each web access token against the account. Migration
`0027` starts existing accounts with a null version so their current tokens keep working until
they change their password.

An organization rename records the action and the actor. The event has no name in its detail,
so a previous name that held a secret cannot be recovered from that event.

### Consequences

Web token checks now read the account's password version. Machine credentials have their own
revocation paths and the password change applies to web sessions.
