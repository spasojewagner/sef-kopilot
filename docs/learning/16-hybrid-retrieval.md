# Hybrid retrieval: from the rule outward, then words and meaning fused by rank

A violation is a rule id, an XPath and a short message, mostly English
(`[BR-CO-15]-Invoice total amount with VAT (BT-112) = … (BT-109) + … (BT-110)`). The passages
that explain it are Serbian, half of them in Cyrillic. Embeddings alone would guess what is
already known, and need a provider that is off by default; keywords alone would miss whatever
the message does not spell out. So retrieval starts with what is exact and ends with what is
similar.

## Five ways, most exact first

```text
violation ──► 1. rule id     ─► the passages an SRB-CIUS rule is authored from
          ──► 2. BT-/BG-     ─► the specification's row that defines each term
          ──► 3. XPath       ─► the row whose UBL path it is, or the nearest above it
          ──► 4. codes       ─► the tax categories named (S20, O), the category of PDV-RS-…
          ──► 5. message     ─► words (pg_trgm)      ┐
                 rule's words ─► meaning (pgvector)  ┴► fused by rank
                                    └─► first six distinct ids, read from the database
```

A passage keeps the place of the first way that found it. Every way filters on the day:
`valid_from <= day AND (valid_to IS NULL OR valid_to > day)`.

The meaning is searched with what the rule says (a Schematron message, an SRB-CIUS rule's
title, an arithmetic rule's statement), not with the violation's message, which may quote a
PIB or an amount: the embedder is an outside service, and it is sent public text only.

## Words across two languages

`search_text` is the passage's label, heading and text folded to Latin without diacritics, so
"šifra" and "шифра" are both `sifra`. The headings of the specification's rows carry the
English term beside the Serbian one ("Seller VAT identifier — ПИБ продавца"), which is why an
English message finds them.

`word_similarity(query, text)` compares the query's trigrams with the most similar *extent* of
the passage, not the whole passage: a short message against a long article. The `<%` operator
asks the same through the GIN index, above `pg_trgm.word_similarity_threshold` (0.3 here, set
with `set_config(…, true)` for the transaction only).

## Reciprocal rank fusion

Trigram similarity (0 to 1) and cosine distance (0 to 2) are not on one scale, so the lists are
fused by rank instead:

```text
score(p) = Σ over lists  1 / (k + rank(p)),    k = 60
```

A passage second in both lists (2/62 ≈ 0.0323) beats one first in only one (1/61 ≈ 0.0164).
`k = 60` (Cormack et al., 2009) keeps the first rank from outweighing agreement. Ties go by id,
so the order is stable.

## Why this order

- The rule's references are what the rule was written from: nothing is more relevant.
- Terms, places and codes are joins on what the validator already knows; they work with no
  embeddings and in either language.
- Words and meaning fill the rest. The XML parser's and the schema's messages skip the words:
  they name elements like `cac:Party`, which every row's path shares.

## In this repository

- `apps/api/src/sef_api/rag/retrieval.py`: `Retriever.passages`, `_fused`; `test_retrieval.py`
  has a test for each way, the day, the fusion and the limit.
- ADR-0021 records the decisions; note 15 explains the valid time the filter relies on.
