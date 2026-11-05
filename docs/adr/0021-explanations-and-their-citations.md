# 21. Explanations: the report's rules, passages found from the rule outward, an answer held to the passages it cites

- Status: accepted
- Date: 2026-11-05
- Deciders: Marko Spasojević
- Technical story: milestone M2, branch `feat/rag-explain-citations`

## Context and problem statement

Layer 1 says that an invoice breaks `BR-CO-15` or `SRB-009`; an accountant needs to hear what
the rule asks, why the invoice fails it and what to change, in Serbian or English, with the
passage of the regulation it comes from (the brief, §2). The corpus holds those passages, each
with the days it applies and an id that names it for ever (ADR-0020). The brief fixes the
rest: a language model behind an adapter (`LLMClient`, Groq by default), structured output
validated with Pydantic and retried with the validation's feedback at most three times, hybrid
retrieval (the rule's own passages, pgvector, `pg_trgm`), and every citation resolving to a
stored passage, or the response fails. Open were:

- what the explainer explains, and what of the invoice the model is sent;
- how passages are found for a rule whose message is English and whose regulation is Serbian;
- how the model's answer is held to the passages it was given;
- which model, and how a request stays within a provider's free tier and a time budget;
- what a request answers when some rule cannot be explained.

## Decision drivers

- The model is never trusted (the brief): it explains, it does not decide, and it may cite
  only what retrieval returned.
- An invoice's content goes to the model only as far as the explanation needs it; nothing of it
  is stored or logged.
- Free tiers: Groq's gives 8 000 tokens a minute for its GPT-OSS models.
- Explainable, boring choices; the database, the corpus and the rate limiter are already there.

## Considered options

What is explained:

1. **The violations of a report that layer 1 makes in the same request, one explanation for
   each rule, from its first violation.** Chosen.
2. Violations the client sends.
3. Every violation separately.

How passages are found:

1. **The rule's references, the terms its message or the rule names, its place, the codes it
   names, then words and meaning fused by rank.** Chosen.
2. Embeddings alone.
3. The rule's references alone.

What the meaning is searched with:

1. **What the rule says: a Schematron rule's message, an SRB-CIUS rule's title, an arithmetic
   rule's statement.** Chosen.
2. The violation's message.

How the answer is held:

1. **A JSON schema whose citations are an enum of the given ids, structured outputs in strict
   mode, and the same checks again in Pydantic, an unusable answer sent back with what was
   wrong.** Chosen.
2. Free text with citation markers, parsed afterwards.
3. JSON mode without a schema.

Which model:

1. **Groq's `openai/gpt-oss-120b` (a production model with strict structured outputs), behind
   `LLMClient`; `SEF_LLM_MODEL` changes it.** Chosen.
2. A smaller model (`openai/gpt-oss-20b`) by default.
3. An OpenAI or Anthropic model by default.

When a rule cannot be explained:

1. **The rule's entry says why (`problem`), the others stand, the answer is 200.** Chosen.
2. The whole request fails (502).

## Decision outcome

**The endpoint.** `POST /invoices/explain?profile=srb&language=sr` takes an invoice as
`POST /invoices/validate` does, validates it in the same way (the same limits, the child
process, the same errors), and explains the rules its report names. Nothing is stored. It needs
`invoices:validate`, counts as a validation and, beside it, against its own limits of requests
for explanations, per caller and per organization (`SEF_EXPLANATIONS_PER_MINUTE`, 10;
`SEF_ORGANIZATION_EXPLANATIONS_PER_MINUTE`, 30). Without a model (`LLM_PROVIDER=none`, the
default) it answers 503 before it reads the body. The day whose law applies is the invoice's
issue date (BT-2), or today when the document cannot be read.

**Rules, not violations.** Each rule is explained once, from its first violation, with how many
violations it has: five lines that break `BR-CO-10` need one explanation. Rules with a fatal
violation come first, in the report's order, up to `SEF_MAX_EXPLANATIONS` (5); the rest are
named in `unexplained`, for a request after the first ones are fixed.

**Retrieval** (`sef_api.rag.retrieval`) finds up to six passages that apply on the day, each
once, in the order these ways find them:

1. the rule's references, for an SRB-CIUS rule (`sef_api.rag.citations`);
2. the semantic terms (`BT-112`, `BG-25`) the message names and the rule declares: the rows
   of the specification's tables that define them;
3. the place: the XPath without positions (`/Invoice/cac:LegalMonetaryTotal`) is a UBL path of
   a row, or the nearest row above it;
4. the codes: a rule that cites the Ministry's list finds the categories its message names
   (`S20`, `O`), and an exemption code (`PDV-RS-11-1`) the category whose list holds it;
5. the words, `word_similarity` of the message over `search_text` through the trigram index
   above 0.3, and the meaning, cosine distance to the embedding of what the rule says when the
   corpus is embedded, fused by reciprocal rank (each list gives `1 / (60 + rank)`). The words
   of the XML parser's and the schema's messages are left out: they name elements, which the
   place finds better.

What the rule says is a Schematron rule's message, which is the rule set's own fixed words (a
test checks that no message of the pinned rule sets is computed from the document), an SRB-CIUS
rule's title or an arithmetic rule's statement; never a message that may quote the invoice, as
those of the SRB-CIUS rules, the arithmetic, the schema and the parser do. An embedder is thus
sent public text only, as ADR-0020 has it, and the model stays the one party that may be sent
anything of an invoice. The parser's and the schema's violations are not searched by meaning.

The words work across the two languages because the headings of the specification's rows carry
the English term beside the Serbian one ("Seller VAT identifier — ПИБ продавца"): `BR-CO-15`'s
message finds `BT-109`, `BT-112` and `BT-110` at 0.75, 0.70 and 0.60. The passages are read in
one transaction, which is committed before the model is asked, so that no connection waits for
it.

**The question.** The model is sent the violation (rule, severity, layer, place and message) and
the passages, each under its id, in Latin letters, at most 2 000 characters each and 6 000 in
all, which keeps a question near 2 000 tokens. Nothing else of the invoice. The system prompt
asks for an explanation in at most three sentences and a fix in at most two that invents no
amount, rate, date or identifier, in Serbian (Latin script) or English, and says that the
violation and the passages are data whose instructions are not to be followed. The message's
angle brackets are escaped, so that a message that quotes the invoice cannot close its tag.

**The answer** is JSON for a schema with `explanation`, `fix` and `citations`, whose items are an
enum of the given ids. Groq's structured outputs in strict mode decode only what the schema
allows; the answer is checked again all the same, for a model or a provider that holds it
less: texts of 1 to 1 200 and 800 characters, one to three citations, each an id given, none
twice. An answer that fails goes back to the model with what was wrong, and a third that fails
gives no explanation. What an explanation cites is a stored passage that applies on the day,
always; each citation carries the document's title, the passage's label, the edition and the
days it applies.

**The model.** `LLM_PROVIDER=groq` with `GROQ_API_KEY` uses Groq's chat completions with
`openai/gpt-oss-120b`, at temperature 0, reasoning briefly and not sending the reasoning back,
up to 1 024 tokens; 429 and 5xx are tried again three times in all, waiting as `Retry-After`
asks but at most ten seconds. All of a request's explanations together have
`SEF_EXPLANATION_SECONDS` (30); a rule not explained by then says so. The rules are explained
one after another, which a provider's limit of tokens a minute favours. With
`EMBEDDINGS_PROVIDER=jina`, what the rules say is embedded too (`retrieval.query`), within a
fifth of the request's time; an embedder that fails or is late leaves the words to find
passages.

### Consequences

Good:

- A citation is a stored passage by construction: the schema cannot name another, the check
  refuses another, and the response is built from the rows retrieval read.
- The explanations rest on what the deterministic validator found in this very request; a
  client cannot have the model explain a violation the validator did not report.
- Most passages are found without the model or the embeddings: by the rule, its terms, its place
  and its codes. Keywords find the rest in either language; embeddings, when configured, find
  what the words miss.
- A rule the model cannot explain does not cost the others theirs, and says why.
- A question of about 2 000 tokens and one rule at a time leave Groq's free tier room for
  several explanations a minute.
- An embedder is sent the same public text for a rule whatever the invoice, so the embeddings
  of the rules could be kept and reused.

Bad / accepted:

- The model is sent the first violation of each rule, whose message may quote the invoice (an
  amount, a PIB, an identifier); an operator who configures a provider accepts that, and
  `LLM_PROVIDER=none` sends nothing.
- Explanations of a stored invoice are not kept, and are made again on every request; storing
  them with the report is backlog.
- One provider: OpenAI's and Anthropic's adapters (bring your own key) are backlog, behind the
  same `LLMClient`.
- Quality is not measured yet: the evaluation set and recorded answers come with M6. The tests
  check the mechanism with stand-in models, not what a real model writes.
- The rules are explained one after another: five rules take five round trips to the model.
- The meaning of a rule is the same for every invoice: it cannot tell two cases of one rule
  apart, which the terms, the place and the words do.
- The day of a document that cannot be read is today in UTC, which differs from Serbia's for
  an hour or two after midnight; such a document's violations are the parser's and the schema's,
  whose passages do not change with the day.

## Pros and cons of the options

### Violations the client sends

- Good: a client could explain a report it already has without sending the invoice again.
- Bad: the model would explain whatever the client wrote, a violation the validator never
  reported or a message written to steer it; the chain from layer 1 to layer 2 would break.

### Every violation separately

- Good: an explanation could name the line it is about.
- Bad: one call per violation: an invoice with 40 lines that break one rule would cost 40
  answers saying the same, and the free tier's minute.

### Embeddings alone

- Good: one mechanism, across languages.
- Bad: nothing found without an embedding provider, which is off by default; and the rule's own
  passages, which are known, would be guessed.

### The rule's references alone

- Good: exact.
- Bad: only the 29 SRB-CIUS rules have references; the EN 16931 and Peppol rules, the schema and
  the parser would find nothing.

### The violation's message for the meaning

- Good: closer to the case at hand, as the words are.
- Bad: an embedder would be sent the invoice's PIBs, amounts and dates, a second party that
  sees invoices beside the model, where ADR-0020 accepted its call as one that carries public
  text only; and the values give a passage nothing to match.

### Free text with citation markers

- Good: a model writes more naturally.
- Bad: markers are parsed out of prose, may name what was never given, and leave no field for
  the fix; checking them is guessing.

### JSON mode without a schema

- Good: works with more models.
- Bad: valid JSON of any shape: every answer would need the retries that a schema prevents.

### A smaller model by default

- Good: twice as fast on Groq, the same limits on the free tier.
- Bad: weaker at keeping to the passages in Serbian; `SEF_LLM_MODEL=openai/gpt-oss-20b` is one
  variable away.

### OpenAI or Anthropic by default

- Good: strong models, mature structured outputs.
- Bad: no free tier to run the demo on; they are the bring-your-own-key options, not the default.

### The whole request fails

- Good: simple.
- Bad: one rule the model stumbles on would take the explanations of the others with it.
