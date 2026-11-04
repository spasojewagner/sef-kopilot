# Invoice fixtures

Test documents for the validation engine, and the verdicts the pipeline gives on them:

- `official/sef/` — the 17 example documents the Ministry of Finance publishes for SEF
  ([updated XML examples, 11 July 2025](https://www.efaktura.gov.rs/tekst/330/azurirani-primeri-xml-datoteka-po-ubl-21-standardu.php)),
  committed byte for byte: `manifest.json` records each file's source URL and SHA-256, and the
  tests check every file against it. Official materials of a state body are not copyright
  works (Law on Copyright and Related Rights of the Republic of Serbia, Article 6). Their PIBs
  are placeholders (123456789, 987654321) whose check digits are wrong, which SRB-009 reports.
- `synthetic/` — invoices written for this project. Every company, person, identifier and
  amount is invented; Serbian tax and registration numbers only satisfy the check-digit
  algorithms. They exist to pin exact parser and rule behaviour, so each file states its
  purpose in a comment at the top: a minimal Serbian invoice, final invoices that settle an
  advance in dinars and in euro (with the Serbian extension), and a credit note that uses
  almost every business group.
- `synthetic/mutations/` — 43 of those invoices with one deliberate mistake each, of the kind an
  ERP or an integration makes: a PIB with a wrong check digit, the general VAT rate from before
  October 2012, a date written the Serbian way, a bare ampersand. Every SRB-CIUS rule is the
  target of at least one. `scripts/make_fixtures.py` makes them from its catalogue, and each
  file's header states the mistake and what the srb profile reports; the tests check both.
  Never edit them: change the catalogue and run `make fixtures`.
- official example and test files from CEN/TC 434 and OpenPeppol are **not** copied here: they
  are fetched into `third_party/` by `make rulesets` and used from there, under their own
  licenses. Their 29 example invoices are part of the corpus below; their unit tests, 1 471
  test documents in 339 files, are run against the Schematron layer by
  `test_schematron_conformance.py`.
- `verdicts.json` — the pipeline's verdict on every document of the corpus (93) under each
  profile that applies to it: `srb` and `en16931` for the Serbian documents, `srb` alone for
  the mutations, `en16931` for CEN's examples and `peppol` for OpenPeppol's. It records
  validity and how often each rule was reported or set aside, not lines or messages.
  `make fixtures` rewrites it and the tests fail when a verdict changes, so a change in
  behaviour shows up as a diff to review.

Never add a real company's invoice, not even anonymised.
