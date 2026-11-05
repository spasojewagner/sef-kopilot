# M2 — `feat/rag-explain-citations`

## Three questions a senior engineer would ask

**1. "Models invent citations. How do you know every one you return is real?"**

Four walls, each tested. The schema sent with the question lists the ids of the passages
retrieval found as an enum, and Groq's structured outputs in strict mode decode only what the
schema allows, so the model cannot write another id. The answer is checked again in Pydantic
anyway (another model or provider may hold the schema less): one to three citations, each an id
that was given, none twice, and texts within their lengths. An answer that fails goes back to
the model with what was wrong, at most three answers in all. And the response is built from the
rows the retriever read from the database, not from anything the model wrote, so each citation
carries the stored passage's title, label, edition and the days it applies. A test answers with
an id that was not given, another cites one twice, a third never gives a usable answer: the
first two are retried with the reason, the third ends in a `problem` for that rule only.

**2. "You send invoice data to a third-party model. What exactly leaves, and what about prompt
injection in a crafted invoice?"**

To the model, only the first violation of each rule: its rule id, severity, layer, place and
message, which may quote a value (an amount, a PIB); and public passages of the regulation. Not
the document. The embedder, when one is configured, is sent what each rule says (its title,
statement or rule-set message), never the violation's message, so it stays a party that sees
public text only. Nothing is stored, the response is `no-store`, and the logs name the rule, the
model and the attempts, never a message. `LLM_PROVIDER=none` is the default and sends nothing.
Injection: the violation and the passages are delimited (a message's angle brackets escaped, so
it cannot close its tag) and the system prompt says they are data whose instructions are not to
be followed, but that is a mitigation, not the defence. The defence is that the model decides
nothing: the verdict was made by layer 1 before the model was asked, its answer can only be text
of bounded length and citations from a closed list, and it reaches no tool. The worst an
injected message can do is make one explanation wrong, and it still cites real passages.

**3. "Groq's free tier is 8 000 tokens a minute. What happens when an office of ten clicks
explain at once?"**

A question is about 2 000 tokens: passages are cut to 2 000 characters each and 6 000 in all,
and the answer to 1 024 tokens. Each rule is one call, up to five rules a request, one after
another. The API counts requests for explanations per caller (10 a minute) and per organization
(30), beside the validation limits, so one office cannot take the server's whole budget. When
Groq answers 429, the client waits as `Retry-After` asks, at most ten seconds, three attempts in
all; the whole request has 30 seconds, after which the remaining rules say "not explained in the
time allowed; ask again" and the rest of the answer stands. Honestly: the server's limits do not
know the provider's, so on the free tier a burst degrades to some rules unexplained; the real
fixes are keeping explanations with a stored invoice's report so they are not asked again
(backlog) and a key on a paid tier (`SEF_LLM_MODEL` and the adapter are already there).

## The one concept to explain unaided

**A citation the model cannot invent.** Retrieval finds the passages; their ids become the enum
of the answer's schema; strict structured outputs constrain decoding to that schema; Pydantic
checks it again and sends a failure back with the reason, three answers at most; the response
is built from the stored rows, so a citation is a stored passage by construction, not by trust.

## Supporting facts worth remembering

- `POST /invoices/explain?profile=srb&language=sr|en`: validates as `/invoices/validate` does,
  then explains each rule once, fatal ones first; the rest beyond `SEF_MAX_EXPLANATIONS` (5) are
  listed in `unexplained`. Without a model: 503 before the body is read or anything counted.
- Retrieval, in order: the rule's references, BT/BG terms, the place (XPath without positions,
  or the nearest row above), tax categories and exemption codes, then `word_similarity` > 0.3
  of the message and cosine distance to what the rule says, fused by reciprocal rank
  (`1 / (60 + rank)`); six passages, each once, all applying on the invoice's issue date
  (note 16). Embedding may take a fifth of the request's 30 seconds.
- The passages are read in one transaction that is committed before the model is asked: no
  database connection waits on a network call to a model.
- `openai/gpt-oss-120b` at temperature 0, `reasoning_effort: low`, reasoning not returned.
- 686 API tests, 100 % coverage. Stand-in models test the mechanism, an `httpx.MockTransport`
  the Groq adapter; what a real model writes is measured from M6 with the evaluation set, and
  the latency budget (< 6 s an explanation) is to be measured with a live key.
