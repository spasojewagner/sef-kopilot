# 55. The model's explanations are measured on answers recorded once and replayed offline

- Status: accepted
- Date: 2026-11-09
- Deciders: the team (milestone M6)
- Technical story: milestone M6, branch `feat/evals-explanations`; the evaluations of
  ADR-0054, the explanations and their citations of ADR-0021

## Context and problem statement

The brief sets two thresholds on the explanations — every citation resolves to a stored passage
(100 %), and at least 90 % of citations are relevant, labelled by a person — and asks that CI
check them offline, without network or key. The model is neither free of variance nor
reachable from CI, and the project stays on Groq's free tier, whose daily token limit allows
one run of a few dozen explanations, not one per pull request. What is measured, on what, and
how does CI measure a model it cannot call?

## Decision drivers

- CI checks the thresholds on every pull request, offline, the same way every time.
- What is measured is the explanation as the API writes it: the same retrieval, prompt, checks
  and retries, not a copy of them.
- A change to what the model is sent (a prompt, a passage, a document) must show, not pass
  silently on old answers.
- Relevance is judged by a person, once per rule and passage, not by another model.
- No paid service, no key in CI.

## Considered options

1. **Cassettes: each request named by the SHA-256 of what is sent, its answer recorded once
   against the real model, and replayed by an `LLMClient` that answers only what it holds.**
   Chosen.
2. A stand-in model that cites the first passage, as the API's tests use.
3. The real model in CI, with the key as a secret.
4. Another model as the judge of relevance.

## Decision outcome

**The golden set.** `evals/golden/explanations.yaml`: the mutations (the 41 readable ones), each
rule they break explained in Serbian on a fixed day, which dates what applies, by
`explain_report` as the API calls it, on a database of the evaluations' own (the tests'
PostgreSQL server, made anew with the repository's corpus, without embeddings, so retrieval
depends on the code and the corpus alone). For each rule, the passages retrieval finds are
labelled relevant or not: relevant when the rule is authored from it, or when it defines a
business term or group the rule's statement names, by id or in words; a neighbouring field is
not. The labels were proposed from the rules' statements and the passages' text, and are
reviewed by the maintainer. `sef-evals --unlabelled` lists the passages no label names.

**The measures**, with their thresholds:

| Measure | Counts | Threshold |
| --- | --- | --- |
| `explained` | rules the model explained, of those asked | 90 % |
| `citation_resolution` | citations of a stored passage that applies on the day | 100 % |
| `citation_relevance` | citations of a passage labelled relevant to the rule | 90 % |

A citation of a passage no label names counts against relevance, so the labels keep up with
retrieval. A rule left unexplained leaves its person with the message alone, hence a threshold
on `explained` too, so that relevance is not measured on a handful of survivors.

**Cassettes.** `evals/cassettes/explanations.json` maps the SHA-256 of each request (the
schema's name, the schema, the messages and the token limit, as canonical JSON; never the
provider or the key) to the model's answer, with the model's name. `Replaying` answers from it
and raises `LLMError` for a request it does not hold, as a model that gives no answer: a
changed prompt or passage lowers `explained` until it is recorded again on purpose. `make
evals-record` (`sef-evals --record`) asks the model the settings name only what the cassette
lacks, two seconds apart, waits out a 429 a minute at a time, stops after five and keeps what
it recorded, so a daily limit is continued from the next day; a finished recording keeps only
the answers the run used. The answers are about synthetic invoices and the public corpus, so
they are committed.

**Who records.** The maintainer, with his own free key, on his machine (`make up`, then `make
evals-record`); the build environment never holds the key. The report names the model whose
answers it measured.

### Consequences

Good:

- CI measures the model's real answers on every pull request, offline and the same way each
  time; a change that alters what the model is sent is seen at once.
- Relevance has a person's labels behind it, reviewable line by line, and grows with retrieval.
- The first labelling found a gap to close: for BR-CL-23 retrieval offers BT-129 (the quantity),
  not BT-130 (its unit code), because the violation's place stops at the element.

Bad / accepted:

- The answers are one sample of a model with variance: they measure that sample, recorded on
  one day. A new recording may move the measures; the report's diff shows by how much.
- A change to the prompt, the corpus or the documents needs a recording before it can pass, by
  someone with a key; on the free tier, a full recording takes a few dozen requests.
- Explanations are measured in Serbian only, the product's first language; English answers
  share the prompt and the retrieval, and can be added as a language when the budget allows.

## Pros and cons of the options

### A stand-in model

- Good: free, fast, already written.
- Bad: it measures the stand-in. Relevance would be that of the first passage retrieval finds,
  whatever the model would cite.

### The real model in CI

- Good: always current answers.
- Bad: a key in CI, network in the gate, and a free tier's daily limit spent on every push; the
  same pull request could pass and then fail on the model's variance alone.

### Another model as the judge

- Good: no labels to write.
- Bad: the brief asks for a person's labels; a model judging a model has the variance and the
  blind spots this measure exists to catch.
