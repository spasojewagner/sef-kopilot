# M4 — `feat/mcp-oauth-authorization`

## Three questions a senior engineer would ask

**1. "Why is an unknown redirect URI answered with a 400, when every other fault is sent back
to the client?"**

Because sending the browser to an address nobody registered is exactly what an attacker wants:
an open redirector that carries the server's name. Until the client and its redirect URI are
known, the server cannot tell the client from someone pretending, so it answers where it was
asked. Every other fault goes back to the registered URI, with the client's state and the
server's identifier, so the client can tell its own request's answer from a forged one.

**2. "What does `iss` in the answer protect against?"**

A mix-up: a client that talks to two authorization servers could be sent a code from one in
place of the other's. With `iss` (RFC 9207), the client compares the answer's issuer with the
one it began with before it sends a code anywhere. The server names itself in every answer, an
error or a refusal included.

**3. "A client asks for scopes the person's role does not grant. What happens?"**

The consent grants what the role grants, and no more; if it grants none of them, the approval
is refused (403) and the person sees why. The role is read when the person decides, and will
be read again on every request the client makes with its token, so a consent never outlasts
the role behind it.

## The one concept to explain unaided

**The authorization code flow with PKCE**: the client sends the person to the server with the
SHA-256 of a secret it keeps; the person decides; the client gets a short-lived code at its
registered address, and will exchange it, with the secret itself, for a token.

## Supporting facts worth remembering

- A request waits ten minutes; a code lives two, and is kept only as its SHA-256.
- Only a person decides, never an API key; the decision is made once, in one conditional
  update, so two decisions cannot both win.
