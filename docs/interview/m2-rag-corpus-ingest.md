# M2 — `feat/rag-corpus-ingest`

## Three questions a senior engineer would ask

**1. "Every RAG tutorial chunks documents into 500 tokens with overlap. Why did you not?"**

Because a citation must be something a reader can look up and a test can check. The law cites
articles, the specification its numbered sections and table rows, the Ministry's list its tax
categories, and the validator's rules cite them the same way (`1.3, Table 1, BT-3`). So a
passage is that unit, and its key is the rule's own reference, which makes "every citation
resolves" a test rather than a hope: all 29 rules resolve, on five days. Fixed-size chunks cut
articles and rows in two, mean nothing to a reader, and move with every edition, so their ids
could never be stable. The largest passage is a few thousand characters, well inside the
embedding model's 32 000 tokens.

**2. "The law changes. Which text applied on a given day, and what happens to a citation
stored last year?"**

Each edition records the day it applies from, the passages its amending act defers, and the
articles it renumbers. Comparing editions key by key gives every passage a half-open interval
`[valid_from, valid_to)`: a repeated passage goes on, a changed one ends when the change
applies, a deferred change leaves the old wording in force until its day. The id names the
first day, `e-invoicing-law/article-4b/2027-07-01`, so a stored citation keeps meaning the same
words; the next amendment closes that passage and opens a new id. The 2027 amendment is a real
case: Article 4b, the import list, becomes 4v on 1 January, and the new 4b, recording purchases
from farmers, applies from 1 July, so between the two no Article 4b applies, and the test says
so.

**3. "How do you know the corpus is the official text and nobody edited it?"**

The manifest pins every source by URL and SHA-256. `build_corpus.py --fetch` downloads them,
refuses a digest that differs, and rebuilds the Markdown deterministically; `--check` fails if
the committed files are not what the sources make. Loading the corpus refuses any file that is
not exactly what the converter writes, so a hand edit is caught even without the sources. What
the publisher adds (editorial notes, deletion marks, signatures, forms) is left out; official
texts themselves are free to use under Article 6 of the Law on Copyright. The two corrections
the converter makes to misprinted identifiers are listed with their reasons.

## The one concept to explain unaided

**Valid time.** A passage applies over a half-open interval of days; an edition closes the
passages it changes and opens new ones; the id names the first day, so a citation never changes
meaning and "what applied on day D" is `valid_from <= D < valid_to`.

## Supporting facts worth remembering

- Five documents, seven editions, 385 dated passages, 369 of them applying on 2026-11-05.
- `corpus_passages` (migration 0008): `search_text` folded to Latin without diacritics (a
  trigram GIN index; "sifra vrste fakture" finds "шифра врсте фактуре"), `embedding
  vector(1024)` with an HNSW cosine index, and `embedding_model`, both or neither. No
  `organization_id`: public text, written only by the ingest command.
- Ingest is idempotent: adds, updates, deletes; drops the embedding when the words change;
  embeds 32 to a batch, each committed, so it resumes; stores a vector only for the digest it
  embedded; two ingests take turns on an advisory lock.
- `EMBEDDINGS_PROVIDER=none` by default, nothing leaves the server; `jina` with
  `JINA_API_KEY` uses `jina-embeddings-v5-text-small`.
