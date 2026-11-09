# 57. OpenAI and Anthropic answer through the same client, chosen by the operator

- Status: accepted
- Date: 2026-11-09
- Deciders: the team (milestone M6)
- Technical story: milestone M6, branch `feat/llm-openai-anthropic`; the `LLMClient` adapter of
  ADR-0021, the brief's "Groq free tier by default, BYOK for others"

## Context and problem statement

The explanations and the repairs ask a model through `LLMClient`, which only Groq's chat
completions implemented. The brief names Groq's free tier as the default and others for whoever
brings a key; an operator who already pays for OpenAI or Anthropic, or whose policy names one,
had no way to use it. The project stays free: nobody on it holds a paid key, so the adapters can
be neither compared on the evaluations nor run against the real services here. How are the two
providers asked, and how is that trusted without calling them?

## Decision drivers

- One contract: the same questions, the same JSON schema, the same checks of every answer,
  whichever provider answers.
- Structured outputs on each provider, so that an answer keeps to the schema while it is
  written, as on Groq.
- No new dependency for two HTTP calls; failures said the same way, never quoting what was sent.
- Tested offline, without an account, against what each provider documents.

## Considered options

1. **One retrying HTTP client, with OpenAI's chat completions and Anthropic's Messages API on
   it, raw `httpx`, structured outputs on both.** Chosen.
2. The providers' official SDKs.
3. OpenAI's Responses API instead of chat completions.
4. Anthropic's tool use, a tool whose input is the schema, for JSON.

## Decision outcome

**One client.** What every provider does alike is written once (`_HTTPClient`): the request,
tried again on 429, 5xx (Anthropic's 529 included) or a failure on the way, waiting as
`Retry-After` asks or longer each time, at most ten seconds, three attempts; an error that names
the provider, the status and its error code (OpenAI's `error.code`, Anthropic's `error.type`),
never the message, which may repeat the question; the tokens counted, for the model's traces.

**OpenAI** answers by chat completions, as Groq does: `response_format` with the schema in strict
mode, `max_completion_tokens`. Its reasoning models (`gpt-6…`, `gpt-5…`, `o3`, `o4`) are asked
for `reasoning_effort: low`, since their reasoning counts against the tokens an answer may have,
and are sent no temperature, which they refuse; other models are sent neither. Default:
`gpt-6-luna`, its low-cost model with structured outputs.

**Anthropic** answers by the Messages API, version `2026-10-21`: the system's messages joined into
`system`, the others in turn, the schema in `output_config.format`, no temperature (that version
refuses it). The answer is the text of the first text block; `stop_reason` `max_tokens` is an
answer cut off, `refusal` a model that declined. Default: `claude-haiku-5-5`. The two schemas the
API asks with keep within what Anthropic's structured outputs support: objects closed with
`additionalProperties: false`, string enums, no length or number constraints.

**Choice.** `LLM_PROVIDER` names `groq` (the default deployment's), `openai` or `anthropic`, with
`GROQ_API_KEY`, `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`; a provider named without its key refuses
to start. `SEF_LLM_MODEL` names another model of the provider. The evaluations' recorder names
its model the same way.

**Tests.** Each provider answers the tests as its API reference shows an answer, through `httpx`'s
mock transport: the request each is sent, the answer read, every failure. The comparison of the
providers on the evaluations is left out at the maintainer's decision (2026-11-09): it needs paid
accounts, and the project stays free. Whoever runs the API with a key of theirs can record the
evaluations' cassettes with it (`make evals-record`) and see the measures for that provider.

### Consequences

Good:

- An operator chooses the provider by two settings; nothing else changes, the checks and the
  evaluations included.
- No SDK in the image; one place for retries, timeouts and errors that quote nothing.

Bad / accepted:

- The requests follow the providers' references as of November 2026, untried against the real
  services here: a provider that changes its API breaks the adapter until it is followed, and the
  first operator with a key is the first to see it.
- Model names age: the defaults and the list of OpenAI's reasoning models are kept by hand.

## Pros and cons of the options

### The official SDKs

- Good: the providers keep them current, and they type every field.
- Bad: two large dependencies, their own retries and logging to tame, for one call each; the
  tests would mock the SDKs instead of the HTTP the providers document.

### OpenAI's Responses API

- Good: OpenAI's recommended interface for new work, with tools and state.
- Bad: nothing here needs tools or state; chat completions share the request, the answer and the
  code with Groq's, and OpenAI's current models still answer them.

### Anthropic's tool use for JSON

- Good: works on older models.
- Bad: the answer is a tool's input, not text, and the schema is a suggestion; structured outputs
  hold the answer to it while it is written, as on the other two.
