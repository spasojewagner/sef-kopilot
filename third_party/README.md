# Third-party rule sets

This directory holds validation artefacts that other organisations publish under their own
terms. They are **fetched, not committed**: everything here except this file and
`manifest.json` is git-ignored.

```bash
make rulesets          # python scripts/fetch_rulesets.py
make rulesets-check    # python scripts/fetch_rulesets.py --check  (no network)
```

| Rule set | What it is | Pinned version | Terms |
| --- | --- | --- | --- |
| `ubl-2.1` | OASIS UBL 2.1 OS schemas for Invoice and CreditNote, with the common component schemas they import | `UBL-2.1.zip` (SHA-256 `60b80d76…`) | OASIS IPR Policy notices; xmldsig schema under the W3C Software License |
| `en16931` | CEN/TC 434 EN 16931 validation artefacts, UBL syntax binding (Schematron + official XSLT build, examples, unit-test invoices) | `validation-1.3.17` | EUPL 1.2 |
| `peppol-bis-billing-3` | Peppol BIS Billing 3.0 rules (Schematron sources), OpenPeppol examples and unit-test files | `3.0.21` | OpenPeppol AISBL copyright; CEN content reproduced with permission; no license file upstream |

The exact source (a git tag pinned by commit, or an archive URL pinned by SHA-256) and the
included paths are in [`manifest.json`](manifest.json).
After a fetch, each rule set directory contains a `SOURCE.json` provenance record and a
`NOTICE.md` with the terms.

## Why fetched and not vendored

- **Licensing.** The EN 16931 artefacts are EUPL-licensed and the Peppol rules carry
  OpenPeppol's own terms; keeping them outside the Apache-2.0 code base keeps the two cleanly
  separated and avoids redistributing them.
- **Integrity.** The manifest pins a tag *and* its commit, or an archive *and* its SHA-256. If
  upstream moves a tag or replaces a file, the fetch fails loudly instead of silently changing
  the rules the validator runs.
- **Reproducibility.** The same manifest produces the same files on a laptop, in CI and in a
  container; upgrading a rule set is a one-line change reviewed like any other.

## Updating a rule set

1. Read the upstream release notes.
2. Change `ref` and `commit` in `manifest.json` (`git ls-remote --tags <repository>` shows the
   commit behind a tag), or `url` and `sha256` for an archive (`sha256sum` of the downloaded
   file, compared with the publisher's checksum where one is published).
3. Run `make rulesets` and the validator test suite; fixture expectations may change.
4. Commit as `build(core): bump en16931 artefacts to validation-1.3.x` with the release notes
   linked in the body.

The files are never edited in place. If a rule has to be adapted (for example a national
profile that tightens a rule), the adaptation lives in `packages/einvoice_core`, not here.
