# M4 — `feat/mcp-search-rules`

## Three questions a senior engineer would ask

**1. "The statements are English and the users Serbian. How does a Serbian query find
anything?"**

Through the law rather than the rules. A search answers two lists: the rules whose ids, terms or
statements match, and the passages of the corpus that share the query's words, by the trigram
index the explainer already uses, among those that apply today. `kontrolni broj PIB` matches no
English statement, but finds the PIB rulebook's article on the check digit first; `BT-31`
finds the Serbian rules on the seller's PIB and the specification's row for the term. The
assistant then reads the rule with `get_rule`.

**2. "Why are the passages of `get_rule` found by building a violation?"**

So that a rule's passages are exactly those an explanation of a violation of it would cite:
the passages it is authored from, the rows of the terms it names, the words of its statement.
The retriever already ranks those ways and reads only stored passages; a second ranking for
rules alone would drift from what explanations cite.

**3. "Nothing is counted. Isn't that an open door?"**

Every request still needs a credential with `invoices:validate`; looking rules up validates no
invoice and asks no language model, which are what the limits protect: the catalogue is in
memory and the passages come from one indexed query. The answers are the rule sets' published
text and the corpus's public law.

## The one concept to explain unaided

**One path for one meaning**: a rule's passages are the passages of its violation, found by the
same code, so that the lookup and the explanation can never cite different law.

## Supporting facts worth remembering

- `GET /rules` and `search_rules` answer the same; `GET /rules/{id}` and `get_rule` too, with a
  day whose law applies.
- Without the rule sets, both routes answer 503, as validation does.
