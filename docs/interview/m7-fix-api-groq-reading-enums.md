# M7 — `fix/api-groq-reading-enums`

## Three questions a senior engineer would ask

**1. "Gemini reads the type with the schema as it is. Why is Groq sent another one?"**

Because the same schema was measured to fail on Groq. With `qwen/qwen3.8-27b` on Groq, the type
came back right in none of twenty readings. Most answers held null, as the schema allowed. The
rest broke off as `json_validate_failed`. Gemini read the same documents right twenty times out
of twenty. Writing the nullable enums as `anyOf` the enum and null, as Gemini is sent them, did
not change the type at all: zero of nine. Requiring the type did: seven of nine. The other two
were the provider's own failures, a refused generation and a 429. Each provider's quirks belong
in its client, as Gemini's reasoning effort and Groq's temperature already are. The evaluation's
recordings, made with Gemini, are untouched.

**2. "A required type means the model must name one, even for a document that is no invoice.
Isn't that a value it may invent?"**

It may guess, and that is acceptable here for two reasons. Every invoice prints its title, and
the instructions already told the model never to leave the type empty for want of a printed
code. And since `fix/web-reading-messages`, the type is the first field the person must confirm
or choose before any invoice is drafted. A guessed type is shown beside the document and
corrected there. It never reaches the validator unseen. Null on every reading helped no one.

**3. "The client now knows the reading schema's name and its `type_code` field. Isn't that a
leak?"**

It is a small one, taken knowingly. The alternative was to make the type required in the shared
schema for every provider. That changes what Gemini is sent and means recording the evaluation
again, for a provider that already reads the type right. The test pins the exact schema sent to
Groq. If the provider is ever set for every model alike, the special case goes with it.

## The one concept to explain unaided

**Constrained decoding is not neutral.** A provider that enforces a JSON schema while the model
writes changes what the model can say, and each provider does it its own way. An option the
schema allows, such as null, can become the path of least resistance. So the schema is part of
the prompt, and its effect is measured per provider, not assumed from another one.
