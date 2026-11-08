# 49. Requests to the language model are traced to Langfuse without the conversation

- Status: accepted
- Date: 2026-11-08
- Deciders: the team (milestone M4)
- Technical story: milestone M4, branch `feat/rag-model-traces`; the guardrails that no invoice
  content reaches a trace, and that a self-hosted deployment calls out to nothing but its
  language model's provider; the budgets of an explanation (< 6 s) and a repair (< 20 s)

## Context and problem statement

The explainer and the repairer ask a language model, which is the slowest and least predictable
part of the API: an answer takes seconds, may be refused, cut off or late, and costs tokens.
Langfuse records such requests, but its usual traces hold the prompt and the answer, which here
quote an invoice. What should be traced, how is it sent, and when?

## Decision drivers

- No invoice content and no model output leave the deployment in a trace.
- Off unless the operator turns it on.
- Enough to see where time and tokens go, per kind of request and per API request.
- A trace never slows or breaks an answer.
- Few dependencies; Langfuse v4 takes spans as OpenTelemetry.

## Considered options

1. **A decorator of the model's client that sends one OTLP span per answer, in JSON, with
   `httpx`, holding only what describes the request.** Chosen.
2. Langfuse's Python SDK, with its OpenTelemetry dependencies.
3. The SDK's traces with the prompt and answer masked.

## Decision outcome

**Off unless both keys are set.** With `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`, the
model the explainer and the repairer share is wrapped in `TracedClient`; with one alone the
settings refuse to load; with neither nothing is sent.

**One generation per answer, and nothing of the conversation.** Each answer becomes a span of
type `generation`: the schema answered (`model.explanation`, `model.repair`), the model, the
most tokens allowed, when it began and ended, the tokens read and written as the provider
reports them, the number of messages, and, if it failed, why, in the words of an `LLMError`,
which never repeat what was sent. No input, output or metadata of the conversation is set. The
answers of one API request share a trace, whose id is digested from the request's id, which the
trace's metadata names, so a slow answer is found from the log and back.

**Sent beside the answer, never in its way.** A span is posted to
`/api/public/otel/v1/traces` (OTLP over HTTP, JSON, `x-langfuse-ingestion-version: 4`, the
project's keys in Basic auth) in a task of its own; a failure is logged with its kind and given
up. When the application stops, the spans under way are sent before it closes.

### Consequences

Good:

- Time, tokens and failures of every request to the model, per kind and per API request,
  without a word of an invoice or of the model's answers.
- No new dependency: `httpx` already speaks to the model's provider.

Bad / accepted:

- Without prompts and answers, a trace cannot show why an answer was wrong; the evaluations of
  M6 judge answers on synthetic invoices, not production traces.
- Spans built by hand follow Langfuse's attribute names, which a later version may change; a
  test holds the shape sent.
- The free plan's monthly units bound how many requests are traced.

## Pros and cons of the options

### Langfuse's SDK

- Good: maintained by Langfuse, with batching and retries.
- Bad: OpenTelemetry's SDK and exporters as dependencies of the API, and an instrumentation
  whose defaults record inputs and outputs, to be switched off and kept off.

### Masked prompts and answers

- Good: a trace shows the shape of a conversation.
- Bad: a mask is one more thing that must be right for every rule and every language; the
  guardrail is simpler kept as "not sent at all".
