# 44. The MCP endpoint's authorization server is the API's own, for public clients

- Status: accepted
- Date: 2026-11-07
- Deciders: the team (milestone M4; a departure from the brief's Authlib)
- Technical story: milestone M4, branch `feat/mcp-oauth-clients` and the branches after it; the
  MCP endpoint of ADR-0042; the authorization of the protocol's 2026-07-28 revision

## Context and problem statement

An assistant that signs its users in, as the milestone's demonstration needs, connects to an
MCP server only through OAuth 2.1. The protocol's revision of 2026-07-28 asks the server for
protected resource metadata (RFC 9728), an authorization server with its metadata (RFC 8414),
PKCE, resource indicators (RFC 8707), tokens accepted only by the resource they were issued for,
the authorization server's identity in its answers (RFC 9207), and a way for a client it has
never met to register: client ID metadata documents, or dynamic registration (RFC 7591), which
the revision keeps for compatibility. The brief names Authlib for all of it. What should the
authorization server be built on, and what may its clients be?

## Decision drivers

- A person, signed in to SEF Kopilot, decides what a client may do; nothing else grants it.
- The API is asynchronous throughout: FastAPI, SQLAlchemy's asyncio, one event loop.
- The revision's newest requirements, client ID metadata documents and the issuer in the
  authorization response, must be possible.
- No secret of a client stored in a form that could be read back.

## Considered options

1. **Routes of the API's own, small and tested, for public clients only, with the protocol's
   pieces from the standard library and the API's token code.** Chosen.
2. Authlib's authorization server, as the brief has it.
3. The MCP SDK's authorization server (`mcp.server.auth`) with a provider over PostgreSQL.

## Decision outcome

**The authorization server is routes of the API** (`/oauth/...`), which answer once
`SEF_PUBLIC_URL` names the API's address, the issuer of everything it signs. It is built in
steps, each reviewable on its own: clients registering themselves (this branch); a person's
consent, in the web application, and the codes it issues; the tokens, with the MCP endpoint
accepting them and the metadata documents that send clients to it; client ID metadata
documents. Until the last steps, the MCP endpoint takes API keys only (ADR-0042).

**Every client is public.** Whatever authentication a client asks for when it registers, it is
registered with none, as RFC 7591 lets a server substitute a value it supports, and told so; it
proves with PKCE (S256) that it began the authorization it ends. So the server stores no client
secret at all. A redirect URI is one OAuth 2.1 allows: `https`, `http` on the loopback interface
for an application on the person's own computer, or a scheme of the application's own; never
with a fragment, never `javascript:` or `data:`, at most ten a client, compared exactly when
used. Registering grants nothing and needs no account, so it is counted by address (ten an
hour).

### Consequences

Good:

- The policy is the server's own and short to read: one kind of client, one way to prove it.
- No library's server classes to adapt to an asynchronous stack, and no secret to protect.
- What the revision added after the libraries, the issuer in the answer and metadata
  documents, is a function of ours, not a fork of theirs.

Bad / accepted:

- The protocol's rules are the team's to get right. Each step is tested against the RFC's
  requirements and seeded faults, and the step that issues tokens gets a review of its own.
- A confidential client, such as a server holding a secret, is treated as public: it proves
  itself with PKCE, which OAuth 2.1 asks of every client anyway.
- Anyone may register; an unused registration costs a row. Registrations are counted by
  address, and clients that never complete an authorization can be deleted later.

## Pros and cons of the options

### Authlib's authorization server

- Good: a mature implementation of the RFCs, named by the brief.
- Bad: its server classes are synchronous and built for Flask and Django requests; adapting them
  to FastAPI and asyncio means threads and a second session model. Client ID metadata documents
  and the issuer in the authorization response are not among its grants.

### The MCP SDK's authorization server

- Good: asynchronous, Starlette's, written for this protocol, already a dependency.
- Bad: its registration mints a secret for every client that does not ask for none, and checks
  it by comparing the stored secret itself, so the server would keep secrets in clear. It has
  neither client ID metadata documents nor the issuer in its answers, and its error answers
  could not carry one.
