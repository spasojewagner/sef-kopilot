# 41. What the rules say is embedded once an embedding model, and kept

- Status: accepted
- Date: 2026-11-07
- Deciders: the team (the backlog's item, from the explanations kept by ADR-0040)
- Technical story: milestone M4, branch `perf/rag-rule-embeddings-kept`; the retrieval of
  ADR-0020 and ADR-0021

## Context and problem statement

An explanation finds passages by a rule's words and, with `EMBEDDINGS_PROVIDER=jina`, by what
the rule says (`meaning_text`): its rule set's message, its title or its statement, never what
the violation found. That text was sent to the embedder for every rule of every explanation,
though the rules are a few hundred and their texts never change, while invoices failing the same
rules are many. Each call costs a provider's request and up to a fifth of the explanation's
seconds. How should the vectors be reused?

## Decision drivers

- A vector is compared only with vectors of the same model.
- Nothing of an invoice may be kept outside its organization, nor sent to the embedder.
- An embedder that fails or is late never stops an explanation.

## Considered options

1. **A table of vectors keyed by the model and the text's digest, read before the embedder is
   asked and written in the explanation's transaction.** Chosen.
2. Embedding every rule's text when the corpus is ingested.
3. A cache in the API's memory.

## Decision outcome

**`rule_embeddings`** holds a vector a model and a text: the model's name, the SHA-256 of the
text, the vector and when it was made. The text is public, the rule's own words, so the row
belongs to no organization, as the corpus's passages do. Before an explanation asks the embedder,
the vectors kept for its model and its texts are read; it is asked only for the others, once a
text even when two rules say the same, and what it answers is kept in the transaction that reads
the passages, without overwriting a vector another request kept meanwhile. When it fails or is
late, nothing new is kept, and the rules whose vectors were kept still have them.

### Consequences

Good:

- Each text is embedded once a model, whatever the number of invoices and organizations.
- An explanation spends the embedding's share of its seconds only on texts never seen.
- A new model starts afresh by itself: its vectors are keyed apart.

Bad / accepted:

- A model whose vectors change under the same name, which providers avoid, would keep its old
  vectors; the table can be emptied by hand, and the next explanations fill it again.
- The table grows with the texts of the rules, a few hundred a model: no deletion is needed.

## Pros and cons of the options

### Embedding every rule's text at ingest

- Good: no embedding while explaining.
- Bad: the rule sets are not the corpus: their messages come from the validator's sources, which
  the ingest does not read, and every text would be embedded, most never asked about.

### A cache in the API's memory

- Good: no table and no migration.
- Bad: lost at every start, which the free plan does many times a day, and kept apart by each
  process and worker.
