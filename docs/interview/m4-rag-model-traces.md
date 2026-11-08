# M4 — `feat/rag-model-traces`

## Three questions a senior engineer would ask

**1. "What is a trace worth without the prompt and the answer?"**

Where the time and the tokens go, and what fails. Each answer is a generation with its schema
(explanation or repair), model, duration, tokens read and written, and outcome; the answers of
one API request share a trace. That answers "why was this request slow?", "how many tokens does
an explanation cost?" and "how often does the provider refuse us?". Why an answer was wrong is
the evaluations' question (M6), on synthetic invoices, not production traces.

**2. "Why hand-build OTLP JSON instead of using Langfuse's SDK?"**

Two reasons. The SDK brings OpenTelemetry's SDK and exporters into the API for one kind of span,
and its instrumentation records inputs and outputs by default, which the guardrail forbids and
would have to be switched off and kept off. A small decorator with `httpx`, which the API already
uses, sends exactly what ADR-0049 allows, and a test holds the shape and the absence of the
conversation.

**3. "How does tracing avoid slowing an answer down?"**

The span is sent in a task of its own after the answer is known; the answer is returned at once.
A failure to send is logged with its kind and given up. When the application stops, the tasks
under way are awaited, then the client is closed. The tokens come from the provider's `usage`,
passed through a context variable, so concurrent answers of one request never mix.

## The one concept to explain unaided

**Observability by metadata**: trace what describes a request (kind, timing, cost, outcome,
correlation id) and leave out its content, when the content is personal or confidential.

## Supporting facts worth remembering

- The trace id is digested from `X-Request-ID`, which the trace's metadata names.
- With one of the two keys alone, the settings refuse to load: half a configuration is a mistake.
