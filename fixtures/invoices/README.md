# Invoice fixtures

Test documents for the validation engine. Three kinds live here:

- `official/sef/` — the 17 example documents the Ministry of Finance publishes for SEF
  ([updated XML examples, 11 July 2025](https://www.efaktura.gov.rs/tekst/330/azurirani-primeri-xml-datoteka-po-ubl-21-standardu.php)),
  committed byte for byte: `manifest.json` records each file's source URL and SHA-256, and the
  tests check every file against it. Official materials of a state body are not copyright
  works (Law on Copyright and Related Rights of the Republic of Serbia, Article 6). Their PIBs
  are placeholders (123456789, 987654321) whose check digits are wrong, which SRB-009 reports.
- `synthetic/` — invoices written for this project. Every company, person, identifier and
  amount is invented; Serbian tax and registration numbers only satisfy the check-digit
  algorithms. They exist to pin exact parser and rule behaviour, so each file states its
  purpose in a comment at the top.
- official example and test files from CEN/TC 434 and OpenPeppol are **not** copied here: they
  are fetched into `third_party/` by `make rulesets` and used from there, under their own
  licenses.

Never add a real company's invoice, not even anonymised. The synthetic generator for mutation
fixtures (`scripts/make_fixtures.py`) arrives with the fixtures corpus in M1.
