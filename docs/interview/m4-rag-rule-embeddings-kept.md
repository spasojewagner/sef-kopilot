# M4 — `perf/rag-rule-embeddings-kept`

## Three questions a senior engineer would ask

**1. "Why is the model part of the key?"**

Because a vector means something only next to vectors of the same model: a vector from another
model, or another size, compared with the corpus's would find nonsense. Keyed by the model and
the text's digest, a new model starts with an empty set of its own, and nothing has to be
cleared when the setting changes.

**2. "These vectors are kept for every organization together. Isn't that a leak between
tenants?"**

What is embedded is the rule's own text: its rule set's message, its title or its statement,
never what the violation found in an invoice (`meaning_text`). It is public, like the corpus,
which belongs to no organization either. The text itself is not even kept, only its digest and
its vector.

**3. "What if the embedder fails halfway?"**

Nothing new is kept, and the explanation goes on: the rules whose vectors were kept have them,
the others are found by their words. The vectors are written in the transaction that reads the
passages, outside the embedder's time limit, so a timeout never interrupts a write.

## The one concept to explain unaided

**Memoize at the boundary you pay for**: keep the answers of the external call keyed by
everything that determines them, here the model and the text, and the call is made once.

## Supporting facts worth remembering

- `rule_embeddings`: the model, the text's SHA-256, the vector, when it was made.
- Two rules that say the same thing ask the embedder once.
