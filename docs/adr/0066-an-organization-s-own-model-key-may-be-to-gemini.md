# 66. An organization's own key to a model may be to Google's Gemini

- Status: accepted
- Date: 2026-11-15
- Deciders: Marko Spasojević
- Technical story: branch `feat/gemini-own-model-key`; amends ADR-0058, whose providers were
  those of ADR-0057; Gemini's client of ADR-0062

## Context and problem statement

ADR-0058 lets an organization's owner set a key of its own to Groq, OpenAI or Anthropic, the
providers the operator could name when it was written. Gemini came later (ADR-0062): the operator
may name it for the server, through Google's OpenAI-compatible chat completions, but an
organization whose contract is with Google could not bring its key. Should it?

## Decision drivers

- An organization chooses among the providers the server can ask, no fewer.
- The key is kept, chosen and audited as every other organization's key is.

## Considered options

1. **Gemini joins the providers an organization may name.** Chosen.
2. The providers stay the three ADR-0058 named.

## Decision outcome

**`gemini` is a fourth provider** of `PUT /organization/model-key`, and of the table
`model_keys`, whose check gains it (migration `0026`; undoing it forgets the keys to Gemini, and
those organizations go back to the server's model). Its default model is Gemini's client's,
`gemini-3.1-flash-lite`, which also reads its documents. A test holds the providers an
organization may name to those the server has a client for, so the two lists cannot drift apart.
Everything else is ADR-0058's: sealed with Fernet, never shown again, set by an owner signed in,
recorded in the audit log, and the only provider that organization's requests go to.

### Consequences

Good:

- An organization whose policy names Google, or that has credit there, pays for its own
  explanations, repairs and readings there.

Bad / accepted:

- On Google's free tier, Google may use what it is sent to improve its products (ADR-0062). An
  organization's key is under its own contract with Google, which decides that, as the page
  already says of every provider; the server sends it what it sends any other provider.

## Pros and cons of the options

### The three providers of ADR-0058

- Good: nothing changes.
- Bad: the server can ask Gemini, yet an organization cannot; the list an organization chooses
  from is no longer the server's.
