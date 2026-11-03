# Invoice fixtures

Test documents for the validation engine. Two kinds live here:

- `synthetic/` — invoices written for this project. Every company, person, identifier and
  amount is invented; Serbian tax and registration numbers only satisfy the check-digit
  algorithms. They exist to pin exact parser and rule behaviour, so each file states its
  purpose in a comment at the top.
- official example and test files from CEN/TC 434 and OpenPeppol are **not** copied here: they
  are fetched into `third_party/` by `make rulesets` and used from there, under their own
  licenses.

Never add a real company's invoice, not even anonymised. The synthetic generator for mutation
fixtures (`scripts/make_fixtures.py`) arrives with the fixtures corpus in M1.
