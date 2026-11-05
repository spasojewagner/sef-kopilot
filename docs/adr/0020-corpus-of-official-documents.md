# 20. The corpus: official text as dated passages, made from pinned sources, kept in PostgreSQL

- Status: accepted
- Date: 2026-11-05
- Deciders: Marko Spasojević
- Technical story: milestone M2, branch `feat/rag-corpus-ingest`

## Context and problem statement

An explanation of a violation must cite the regulation the rule comes from, and every citation
must resolve to a stored passage (the brief). The rules are authored from five official
documents: the Law on Electronic Invoicing, the Rulebook on Electronic Invoicing, the Rulebook
on the Tax Identification Number, the SRB-CIUS specification and the Ministry's list of tax
categories. They change: an amending act applies from a day of its own, defers some of its
provisions further, and renumbers articles. Five things were open:

- what is kept of a document, how it is made, and how anyone can check it is the official text;
- what a passage is, and what names it;
- how a passage's days are known, when editions and deferrals overlap;
- where passages are kept and searched, and how they get their embeddings;
- how a rule's reference finds its passages.

## Decision drivers

- Official sources only, kept as text with where they came from and when they apply (brief).
- A citation names one passage, for ever: an id may not change its meaning.
- A reviewer must see what a new edition changed, as a diff.
- Free tiers and self-hosting: nothing leaves the server unless configured to.
- Boring, explainable choices; PostgreSQL is already there.

## Considered options

What is kept:

1. **Markdown files written by a converter from sources pinned by URL and SHA-256, committed;
   the sources downloaded, not committed.** Chosen.
2. The sources (HTML, PDF) committed and read when the corpus is ingested.
3. The sources fetched from the official sites when the corpus is ingested.

What a passage is:

1. **The unit the document cites: an article, a numbered section, a row of a table, a tax
   category.** Chosen.
2. Chunks of a fixed size, overlapping.
3. Paragraphs.

How its days are known:

1. **Editions, each with the day it applies from, its deferred passages and its renumbering;
   a passage applies from the day its wording does until the day a later edition changes it,
   and its id names that first day.** Chosen.
2. Every passage of every edition stored, valid for that edition's span.
3. The current text only.

Where passages are kept and searched:

1. **A table in PostgreSQL with pgvector (HNSW, cosine) and pg_trgm (GIN over folded text),
   shared by all organizations.** Chosen.
2. A vector database beside PostgreSQL.
3. PostgreSQL's full-text search instead of trigrams.

How passages are embedded:

1. **An `Embedder` adapter; none by default; Jina's v5 small model (1024 numbers) with a key;
   passages embedded when ingested, again only when their words or the model change.** Chosen.
2. Embeddings computed when a question is asked.
3. A local model now.

## Decision outcome

**The manifest and the converter.** `corpus/manifest.toml`, written by hand and reviewed like
code, lists the documents and their editions: for each edition the day it applies from
(`valid_from`), the version as the validator's sources name it, the URL of its source and the
SHA-256 of what that URL returned on `fetched_at`, and its `deferred` passages (with `partly`,
the passage applies from the edition's day and some of its provisions later) and `renumbered`
ones. `scripts/build_corpus.py --fetch` downloads the sources into `corpus/raw/` (ignored by
Git), refuses one whose digest differs, and writes each edition's Markdown,
`corpus/<document>/<day>.md`; `--check` fails when the committed files are not what the sources
make. Three readers: consolidated texts of the Legal Information System (HTML), the SRB-CIUS
specification and the tax categories (PDF, with pdfplumber, a development dependency). They
keep the document's text and leave out what its publisher added: the system's notes, the marks
of deleted items, signatures and forms; its footnotes on the last amending issue become an
article's `amended-by`. Letters a source writes in the wrong script ("Члaн" with a Latin
"a", "BТ-121" with a Cyrillic "Т") are put back. Two misprinted identifiers of the
specification are corrected, each with its reason, in `SPECIFICATION_ERRATA`.

**The files.** An edition is Markdown of one fixed form: `## <key>`, a list (`label`, and if
printed `heading`, `part`, `amended-by`), then the text. Keys are English identifiers as the
rules cite passages (`Article 4b`, `1.3, Table 1, BT-3`, `Tax category S20`, `80/2026,
Article 7` for an amending act's final provision); labels and texts are as printed, in
Cyrillic. Loading a file that is not exactly what the converter writes fails, so a hand edit
is noticed.

**Days.** A passage applies from its edition's day, or the later day its edition defers it to,
up to (not including) the day a later edition changes it, drops it or gives its number to
another passage; a passage a later edition repeats exactly goes on. A deferred change leaves
the earlier wording in force until it applies. A passage's id is
`<document>/<slug of key>/<day it began to apply>`, so a stored citation keeps naming the same
words after the law changes. The first edition of a document is where the corpus begins.
`Corpus.passage(document, key, day)` is the passage that applies on a day. The readings of the
two amending acts that defer provisions are recorded in the manifest: 80/2026 (the law)
applies from 1 January 2027, and its provisions on recording purchases from farmers and on the
customs list for exports from 1 July 2027; 71/2026 (the rulebook) from 1 August 2026, and its
provisions on the preliminary VAT return from 1 January 2027.

**The database.** Migration 0008 adds the `vector` and `pg_trgm` extensions, `corpus_documents`
and `corpus_passages`: the passage's metadata, its text, `search_text` (label, heading and text
folded to Latin letters without diacritics, so that "sifra vrste fakture" finds "шифра врсте
фактуре"), `text_sha256`, and `embedding vector(1024)` with `embedding_model`, set together or
not at all. Indexes: unique `(document, key, valid_from)`, HNSW with `vector_cosine_ops`, GIN with
`gin_trgm_ops`. The tables have no `organization_id`: the corpus is public text, the same for
everyone, written only by the ingest command.

**Ingesting.** `python -m sef_api.rag.ingest` (`make ingest`) makes the tables hold exactly the
corpus: it adds, updates and deletes documents and passages, leaves unchanged ones alone and,
when a passage's words change, drops its embedding. With an embedder it then embeds every
passage without an embedding of the embedder's model, 32 to a request and a transaction, and
stores a vector only if the passage's digest is still the one it embedded. Two ingests take
turns on an advisory lock. `EMBEDDINGS_PROVIDER=none`, the default, embeds nothing;
`EMBEDDINGS_PROVIDER=jina` with `JINA_API_KEY` calls `jina-embeddings-v5-text-small` with
`task=retrieval.passage`, 1024 numbers, normalized, retrying 429 and 5xx up to four times.

**Citations.** `sef_api.rag.citations` resolves a rule's `Reference(document, passage)` to the
passages that apply on a day: a key, several rows of one table (`1.3, Table 1, BT-95, BT-102,
BT-151`), or a whole list (`the list for each tax category`). A reference that resolves to
nothing raises `UnresolvedReferenceError`; a test resolves every reference of every rule on
five days, and checks that the documents the rules cite are the corpus's.

### Consequences

Good:

- Anyone can check the corpus: download the pinned sources, compare digests, rebuild, diff. A
  new edition is a reviewed diff of the regulation.
- Citations are stable and readable (`e-invoicing-law/article-4b/2027-07-01`), and an old one
  keeps resolving after the law changes.
- One database, one backup, transactions across the corpus and the rest; nothing leaves the
  server by default, and keyword search works in either script without embeddings.
- The rules and the corpus cannot drift apart unnoticed: a rule citing a passage the corpus
  lacks fails the tests, and so does a rule written against another version of a document.

Bad / accepted:

- The sources are fetched from the official sites, which the build environment and CI cannot
  always reach; `--check` is skipped without them, and the maintainer runs it.
- An article whose change mixes provisions that apply at once with deferred ones applies from
  the edition's day, marked `fully_from`; the corpus does not split the legal effect inside an
  article.
- An amending act's own final provisions apply, in the corpus, from the day of the edition that
  prints them, not from the act's entry into force.
- The first edition of each document is where the corpus begins; earlier wordings are not
  held.
- The Internal Technical Instruction for SEF is not in the corpus yet (backlog).
- The embedding size is fixed at 1024: another model of another size needs a migration.
- Jina's API is an external call when configured; the local model for self-hosting is backlog.

## Pros and cons of the options

### Sources committed

- Good: the corpus rebuilds offline, anywhere.
- Bad: the repository would redistribute the publishers' pages and PDFs, editorial matter
  included; the brief asks for text. Official texts are free to use (the Law on Copyright and
  Related Rights, Article 6), the publisher's editorial work is not ours to republish.

### Fetched when ingested

- Good: always the latest text.
- Bad: an ingest that depends on government sites being up, and a corpus that changes without
  review; the digests would stop meaning anything.

### Chunks of a fixed size

- Good: uniform, the usual tutorial default.
- Bad: a chunk is nothing a reader can look up; it cuts articles and table rows apart, and its
  boundaries move with every edition, so ids would not be stable.

### Paragraphs

- Good: finer for retrieval, and a deferral could name the paragraph.
- Bad: the law and the rules cite articles and rows, not paragraphs; mixed articles would still
  need a reading of the law.

### Every passage of every edition

- Good: simplest to load.
- Bad: an unchanged article would get a new id with every edition, so a citation would change
  meaning with each amendment; deferred passages and renumbering would still need dates.

### The current text only

- Good: least to keep.
- Bad: an explanation for an invoice of last month could cite a rule that did not apply yet,
  and the 2027 changes could not be shown before they apply.

### A vector database

- Good: built for vectors at scale.
- Bad: a second store to run, back up and keep in step, for a few hundred passages; pgvector
  is enough and runs on Neon's free tier.

### Full-text search

- Good: stemming and ranking built in.
- Bad: PostgreSQL has no Serbian dictionary, and Cyrillic and Latin spellings would need two
  configurations; trigrams over the folded text find either script, with typos.

### Embeddings when a question is asked

- Good: nothing to store.
- Bad: every question would embed every passage, a cost and a delay per request; vectors
  stored once are compared in milliseconds.

### A local model now

- Good: no external call at all.
- Bad: a model of several hundred megabytes in the image and the CI, before retrieval exists to
  use it; the adapter keeps the door open (BGE-M3 also gives 1024 numbers).
