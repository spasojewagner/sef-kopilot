# The corpus

The official documents that SEF Kopilot's explanations cite, passage by passage, each passage
with the days it applies (ADR-0020). The validator's SRB-CIUS rules are authored from these
documents, and every reference a rule makes resolves to one of their passages.

| Document | Key | Editions | Source |
| --- | --- | --- | --- |
| Zakon o elektronskom fakturisanju | `e-invoicing-law` | from 2026-04-01 (… 109/2025), from 2027-01-01 (… 80/2026) | [Legal Information System](https://pravno-informacioni-sistem.rs/eli/rep/sgrs/skupstina/zakon/2021/44/3/reg) |
| Pravilnik o elektronskom fakturisanju | `e-invoicing-rulebook` | from 2026-04-01 (… 30/2026), from 2026-08-01 (… 71/2026) | [Legal Information System](https://pravno-informacioni-sistem.rs/eli/rep/sgrs/ministarstva/pravilnik/2023/47/1/reg) |
| Pravilnik o poreskom identifikacionom broju | `pib-rulebook` | from 2018-10-01 (… 44/2018) | [Legal Information System](https://pravno-informacioni-sistem.rs/eli/rep/sgrs/ministarstva/pravilnik/2003/57/1/reg) |
| SRB-CIUS specification | `srb-cius` | version of 06.06.2025 | [efaktura.gov.rs](https://www.efaktura.gov.rs/tekst/en/5370/updated-specification-for-the-adapted-implementation-of-the-en-16931-1-standard-for-electronic-invoices-in-domestic-trade-in-the-republic-of-serbia.php) |
| Poreske kategorije i šifre | `tax-categories` | from 2024-09-01 | [efaktura.gov.rs](https://efaktura.gov.rs/tekst/1382/poreske-kategorije-za-elektronske-fakture.php) |

## What is here

- `manifest.toml`: the documents and their editions, each edition's source by URL and SHA-256,
  the day it applies from, the passages it defers and the articles it renumbers. Written by
  hand and reviewed like code; its comments record how each amending act's final provisions
  were read.
- `<document>/<day>.md`: an edition's text, one passage under each `##`, as
  `scripts/build_corpus.py` writes it. **Never edited by hand**: loading the corpus refuses a
  file that is not exactly what the converter writes.
- `raw/` (ignored by Git): the downloaded sources.

The text is as the documents print it, in Cyrillic; what their publishers added (the Legal
Information System's editorial notes, the marks of deleted items, signatures, forms) is left
out. Laws, regulations and official materials of state bodies are not copyright works under
Article 6 of the Law on Copyright and Related Rights; the publishers' own editorial work is
not reproduced.

## Rebuilding and checking

```bash
make corpus          # uv run python scripts/build_corpus.py --fetch: download, check, write
make corpus-check    # uv run python scripts/build_corpus.py --check: compare, write nothing
make ingest          # uv run python -m sef_api.rag.ingest: load into the database
```

A source whose digest is not the manifest's is refused: the publisher changed it. Review the
new text, then record a new edition (or a new digest) in the manifest, rebuild, and read the
diff of the Markdown: it is the diff of the regulation.

## Adding an edition

1. Add an `[[documents.editions]]` entry with `valid_from`, `version`, `source_url`,
   `source_file`, `sha256` and `fetched_at`; with `deferred` and `renumbered` if the amending
   act's final provisions say so, and a comment saying how you read them.
2. `make corpus`, then review the new file against the published text.
3. The tests check that no two passages of one key apply on the same day and that every rule's
   reference still resolves; a document the rules cite in a new version means reviewing those
   rules (`packages/einvoice_core/src/einvoice_core/srb/sources.py`).

## Corrections

The converter corrects two identifiers the SRB-CIUS specification misprints, each with its
reason in `SPECIFICATION_ERRATA` (`scripts/build_corpus.py`): the second row printed `BT-64` is
`BT-65`, and the group printed `BT-31` on page 20 is `BG-31`. Typing errors in the text itself
(`#compliantt#`) are kept as printed.
