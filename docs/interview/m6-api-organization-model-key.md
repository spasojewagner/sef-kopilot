# M6 — `feat/api-organization-model-key`

## Three questions a senior engineer would ask

**1. "The organization's key can't be opened. Why not fall back to the server's model?"**

Because the organization chose where its invoices go. An owner who set a key to Anthropic did so
for a reason: a contract, a policy, a data agreement. Sending the same violations to the server's
Groq model because a secret was rotated badly would quietly break that choice, and nobody would
notice. A 503 that says "an owner sets it again" is loud, and costs one form.

**2. "The SEF key and the model key are both sealed under `SEF_FERNET_KEY`. What stops one
being used as the other?"**

The purpose is sealed with the key. Fernet authenticates the whole message, and the message
holds the organization's id, the key and, for a model key, `"purpose": "model"`; opening checks
both. A token copied from `sef_keys` into `model_keys` (or to another organization's row) opens
but is refused as sealed for another purpose. The SEF keys sealed before this change have no
purpose field and read as `sef`, so nothing had to be sealed again.

**3. "Why make a client per request instead of caching one per organization?"**

A cache has to be emptied when a key is replaced, removed or rotated, on every instance of the
API. A client made from the stored token for one request cannot outlive the key it was made
with. The cost is a new connection to the provider each time, tens of milliseconds within an
explanation's six-second budget; the traces, which do hold a connection, stay shared, which is
why a traced client now knows whether it owns them.

## The one concept to explain unaided

**Authenticated encryption binds context, not just secrecy**: Fernet's HMAC covers every byte
of the message, so whatever you put beside the secret (whose it is, what it is for) cannot be
changed or swapped without the token failing to open. That is how one secret seals two kinds of
key for many organizations without any of them opening where it does not belong.

## Supporting facts worth remembering

- `PUT /organization/model-key` takes `provider` (`groq`, `openai`, `anthropic`), an optional
  `model` and `api_key` (8 to 300 characters, no spaces); an owner only, audited, never shown.
- `GET /organization` shows `model_key`: provider, model, `set_at`.
- `sef_api.model_choice` is the one place that decides whose model writes; the explanation
  routes, the repair route and the MCP tools that do what they do all ask it.
- The key is not tried when it is set; a key the provider refuses shows as its error code (502).
