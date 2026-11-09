# M6 — `feat/evals-explanations`

## Three questions a senior engineer would ask

**1. "How do you measure a language model in CI without calling it?"**

With cassettes: every request the evaluations make is named by the SHA-256 of what is sent
(the messages, the schema, the token limit), and its answer is recorded once, with
`make evals-record`, against Groq's free tier. CI replays: a request the cassette does not hold
is an error, never a call to the network. Changing one word of the prompt or one passage changes
the hash, so a stale answer can never stand in for a new question; the measure drops until the
answers are recorded again.

**2. "Your explanations cite passages. What stops the model inventing a source?"**

Two walls, measured here. The model may cite only the ids retrieval gave it, which the answer's
schema and a check after it enforce; `citation_resolution` then confirms that every citation is
a passage stored in the corpus and in force on the invoice's day: 93 of 93. Whether a real
passage is the *right* one is a different question, `citation_relevance`, which needs labels a
person wrote: 90 of 93, against a threshold of 90 %. The three misses are listed in the report
by rule and passage.

**3. "Why a database of the evaluations' own?"**

Because the explanations are measured as the API writes them: retrieval reads PostgreSQL, with
the trigram and full-text indexes the API uses. The runner makes a database on the tests'
server, migrates it, loads the repository's corpus without embeddings, measures, and drops it,
so retrieval depends on the code and the corpus alone, and a developer's own database is never
touched.

## The one concept to explain unaided

**Record once, replay always**: a cassette turns a slow, paid, non-deterministic dependency into
a fixture, as long as each request is named by everything sent and a missing answer fails
loudly instead of falling back to the network.

## Supporting facts worth remembering

- First recording, 2026-11-09, `groq/openai/gpt-oss-120b`: 47 rules of the mutations explained
  in Serbian, 47 of 47 explained, 93 of 93 citations resolved, 90 of 93 relevant.
- `sef-evals --unlabelled` lists passages a citation names that no label covers.
- Recording asks only what is missing, two seconds apart, and stops at a provider's daily limit
  keeping what it has; the next run continues.
