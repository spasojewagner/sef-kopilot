# Account settings and password changes

## Three questions a senior engineer would ask

**1. Why revoke the access tokens as well as the refresh tokens?**

A bearer token already issued could otherwise keep working until it expires. Once the password
changes, the API rejects every earlier password version and returns a new token pair to the
browser that confirmed the change.

**2. What happens if a refresh races with the password change?**

Both operations lock the same user row before issuing tokens. The refresh either commits first
and its new token is revoked with the others, or it sees the old token already revoked.

**3. What does a rename put in the audit log?**

It records the action, the organization and the actor. The event has an empty detail because
the old name could contain a secret.

## The one concept to explain unaided

The account lock makes credential replacement and web-session invalidation atomic across
organizations.
