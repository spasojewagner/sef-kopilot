# 58. An organization may bring its own key to a model's provider, sealed as its SEF key

- Status: accepted
- Date: 2026-11-09
- Deciders: the team (milestone M6)
- Technical story: milestone M6, branch `feat/api-organization-model-key`; the providers of
  ADR-0057, the sealed SEF key of ADR-0050, the model's traces of ADR-0049, the brief's "Groq
  free tier by default, BYOK for others"

## Context and problem statement

ADR-0057 lets the operator choose one provider for the whole server. The brief's "bring your own
key" is about the organizations: an accounting office whose policy names OpenAI or Anthropic, or
that wants its invoices answered under its own contract with a provider, rather than the
server's free Groq tier, had no way to say so. The server keeps one secret per organization
already, the SEF key, and knows how to keep it. Where does an organization's key to a model
live, who sets it, and what answers the organization's requests when it cannot be used?

## Decision drivers

- The organization's choice holds: an invoice it asked to be answered by its own provider is
  never sent to another.
- The key is kept as the SEF key is: sealed, bound to its organization, rotated with the same
  secret, never shown.
- Every way the organization asks a model (the explanation routes, the repair route, and the
  MCP tools that do what they do: `explain_errors`, `explain_invoice`, `propose_fix`) answers by
  the same choice.
- Nothing changes for an organization without a key, nor for a server without one.

## Considered options

1. **A key per organization, sealed with Fernet under `SEF_FERNET_KEY` for its own purpose, and
   a client made for each request from it.** Chosen.
2. The caller sends its key with every request (a header).
3. A client per organization, made once and kept in the application.

## Decision outcome

**Kept sealed.** The table `model_keys` holds one key an organization: the provider (`groq`,
`openai` or `anthropic`), the model if the owner named one (the provider's default otherwise),
the token and when it was set. The token is sealed as the SEF key is (ADR-0050), with the
purpose `model` in the sealed message beside the organization's id: a token opens only for its
organization and its purpose, so a model key copied over a SEF key, or the reverse, is refused
as unreadable. `make rotate-sef-keys` seals both kinds again under the first key.

**Who sets it.** An owner, signed in: `PUT /organization/model-key` with the provider, the model
and the key sets or replaces it, `DELETE` removes it; each is recorded in the audit log
(`model.key_set` with the provider, the model and whether a key was replaced;
`model.key_removed`) and logged as a security event, never with the key. Every member sees
which provider and model write for the organization and since when (`GET /organization`), never
the key. The key is not tried when it is set: that would spend the organization's quota, and a
key the provider refuses shows on the first explanation, as the provider's error code.

**Whose model writes.** For each request that asks a model, the organization's key is read and
opened, a client of its provider is made with it and closed when the answer is written, traced
as the server's model is (ADR-0049) where Langfuse's keys are set. An organization without a
key is answered by the server's model, as before; a server without a model answers an
organization with a key.

**Never elsewhere.** A key the server cannot open (`SEF_FERNET_KEY` unset, or no longer holding
the key that sealed it) answers 503 and says that an owner sets it again; the invoice is not
sent to the server's model instead.

### Consequences

Good:

- An organization chooses its provider, its model and its contract with them; the server's own
  free model stays the default for everyone else.
- One way of keeping secrets, with its binding, its rotation and its audit, for both keys.
- The choice is made in one place (`sef_api.model_choice`), so a new way of asking a model
  cannot forget it.

Bad / accepted:

- A client is made and closed for each request: a new connection to the provider each time,
  some tens of milliseconds within an explanation's six seconds.
- The rate limits stay the server's: a request answered by the organization's own model counts
  as any other.
- A key that is wrong or out of quota is found when it is used, not when it is set.

## Pros and cons of the options

### The caller sends its key with every request

- Good: the server keeps nothing.
- Bad: every client of the organization (the web app, each API key, each MCP client) needs the
  key; it travels with every request and ends up in their settings, where it is not sealed.

### A client per organization, kept in the application

- Good: connections are reused.
- Bad: one more cache to empty when a key is replaced, removed or rotated, on every instance of
  the API; a replaced key would keep answering until each instance noticed.
