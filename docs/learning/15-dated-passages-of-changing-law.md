# Law that changes: editions, valid time and ids that stay

A citation says "Article 4b of the Law on Electronic Invoicing". Which Article 4b? Until 2027
it is the list of customs declarations for imports; from 1 July 2027 it is the recording of
purchases from farmers, and the import list moves to Article 4v. A corpus that holds only
today's text cannot answer for last month's invoice, and one that numbers chunks cannot say
which words a citation meant. The answer is **valid time**: every passage carries the days it
applies, and its id names the day it began.

## Editions in, passages over time out

An **edition** is the document as consolidated at one point, with the day it applies from. The
corpus compares each edition with the one before, key by key:

| In the next edition the passage is | so the earlier passage | and the next one |
| --- | --- | --- |
| word for word the same | goes on, same id | — |
| changed | ends when the change applies | starts then, new id |
| changed, the change deferred | goes on until the deferred day | starts on the deferred day |
| gone, or its number given to another | ends when the edition applies | — |

```text
e-invoicing-law, Article 4b
  2026-04-01 ───────────────── 2027-01-01           2027-07-01 ────────────▶
  [ imports list   (…/article-4b/2026-04-01) )       [ farmers (…/article-4b/2027-07-01)
                                (renumbered to 4v)   (deferred: no 4b applies in between)
```

The interval is **half-open**: `valid_from ≤ day < valid_to`. Consecutive passages share a
boundary without overlapping, and `valid_to = NULL` means "until the corpus knows better".

## Why the id names the first day

`e-invoicing-law/article-4b/2027-07-01` is readable, and it never changes meaning: a stored
explanation that cites it still points at the same words after the next amendment, which
gives the passage a `valid_to` and a successor with an id of its own. A passage a new edition
repeats word for word keeps its id, so unchanged articles do not churn with every amendment.

## What the model does not do

- It does not split an article's legal effect. When one article mixes provisions that apply at
  once with deferred ones, it applies from the edition's day and says `fully_from`.
- It knows nothing before its first edition: that is where the corpus begins.
- Valid time is when the law applies, not when we learned of it (transaction time); the
  manifest's `fetched_at` is that second kind of time, kept for the record.

## In this repository

- `corpus/manifest.toml`: editions, deferrals and renumbering, written by hand and reviewed.
- `apps/api/src/sef_api/rag/corpus.py`: `_dated` turns editions into passages; tests in
  `test_corpus.py` cover each row of the table above.
- `corpus_passages` keeps `valid_from`, `valid_to`, `fully_from`, with a check that each ends
  after it starts; ADR-0020 records the decisions.
