# M6 — `feat/llm-openai-anthropic`

## Three questions a senior engineer would ask

**1. "Why not the official SDKs?"**

For one call each, they would bring two large dependencies with their own retries, timeouts and
logging to tame, and the tests would mock the SDKs instead of the HTTP the providers document.
What the three providers share — retry on 429 and 5xx as `Retry-After` asks, three attempts,
errors that name the provider and its error code but never its message — is written once; each
provider adds only how its request and its answer read.

**2. "You hold no paid key. How do you know the adapters work?"**

I know they do what the providers' API references document, which is what the tests hold: the
request each is sent, the answer read, every failure. I do not know they work against the live
services today, and the ADR says so: the first operator with a key is the first to try it. The
comparison on the evaluations was left out at the maintainer's decision, since it needs paid
accounts; anyone with a key can record the cassettes with their provider and see the measures.

**3. "What differs between the providers that the rest of the system must not see?"**

Where the system prompt goes (Anthropic's top-level `system`), how the schema is asked for
(`response_format` against `output_config.format`), what reasoning models refuse (temperature),
how a cut-off answer reads (`finish_reason: length` against `stop_reason: max_tokens`), and
where the error's code is. All of it stays in the adapter; the explainer and the repairer send
the same messages and schema, and check every answer the same way.

## The one concept to explain unaided

**An adapter is a contract, not a wrapper**: `LLMClient` promises JSON text meant to match a
schema, or an error that quotes nothing; each provider's quirks are translated at the boundary,
and the code above never learns which provider answered.

## Supporting facts worth remembering

- Defaults: Groq `openai/gpt-oss-120b` (free), OpenAI `gpt-6-luna`, Anthropic `claude-haiku-5-5`;
  `SEF_LLM_MODEL` names another.
- Anthropic's API version `2026-10-21` removed `temperature`, `top_p` and `top_k`.
- OpenAI's reasoning models are asked for `reasoning_effort: low`, since reasoning counts against
  the answer's token limit.
