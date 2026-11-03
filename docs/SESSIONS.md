# Engineering sessions

One short entry per working session: date, branch, outcome, and what comes next. This file is
part of the project history, not a chat log — it records what was built and decided, so that
anyone (including the maintainer in six months) can follow how the project evolved.

Format:

```text
## YYYY-MM-DD — <branch> (<n> commits)
Outcome: ...
Verification: ...
Next: ...
```

Entries are added in the last commit of each branch.

## 2026-11-03 — `chore/bootstrap` (9 commits on top of the initial commit)

Outcome: milestone M0 complete. Monorepo skeleton (uv workspace with `einvoice_core` and the
FastAPI `api`, pnpm workspace with the Next.js `web`), pre-commit gate with the Conventional
Commits check, GitHub Actions CI (pre-commit, tests with coverage gates, web build, rule-set
fetch, gitleaks history scan, dependency audits), docker-compose for PostgreSQL + pgvector and
Redis, the pinned rule-set fetcher (EN 16931 `validation-1.3.17`, Peppol BIS `3.0.21`),
ADR-0001 and ADR-0002, architecture map, first learning and interview notes.

Verification: 22 Python tests and 2 Vitest tests green; core and API coverage 100 %;
`mypy --strict`, ruff, ESLint, `tsc --noEmit`, Prettier and `pre-commit run --all-files` clean;
`next build` succeeds; `docker compose config` valid; real rule-set fetch verified against the
pinned commits; `gitleaks` finds nothing in the history. The same sequence was then run on
the maintainer's Windows workstation: it caught one test that shelled out to `ls`, which
was made platform-independent (Python interpreter instead of a shell tool).

Decisions: tags are fetched by full ref name because the EN 16931 repository has a branch and a
tag with the same release name; pnpm `minimumReleaseAge` set to one day; Prettier does not
format Markdown; `mypy --strict` applies to every Python package, not only the core.

Next: `feat/core-ubl-parser` (M1).

## 2026-11-03 — `feat/core-ubl-parser` (7 commits)

Outcome: first slice of the validator core. `einvoice_core.model` (typed invoice document
following the EN 16931 semantic model, `Decimal` amounts, canonical XPath per business
group), `einvoice_core.xml` (hardened loading: no DTD, no entities, no network, byte limit;
`canonical_xpath`), `einvoice_core.ubl` (UBL 2.1 Invoice and CreditNote → model per the
EN 16931-3-2 binding). Two synthetic fixtures with invented parties and check-digit-valid tax
numbers. ADR-0003, learning note 02, interview notes.

Verification: 108 tests (86 new) green, core coverage 100 %, `mypy --strict` and ruff clean;
all 29 official CEN and OpenPeppol examples parse (~5 ms each) and every XPath in the resulting
models resolves to exactly one element; property-based test for the XPath invariant; each
commit verified green on its own in a throw-away worktree.

Decisions: semantic model over a syntax mirror; required-by-schema only; XPath on groups, leaf
addresses derived by rules; the lxml tree lives beside the model, not inside it.

Next: `feat/core-xsd-validation`.

## 2026-11-03 — `feat/core-xsd-validation` (9 commits)

Outcome: second slice of the validator core. `einvoice_core.violations` (the value every layer
reports), `einvoice_core.rulesets` (finding fetched rule sets), `einvoice_core.xsd` (UBL 2.1
schema validation: schemas compiled once, imports confined to the schema directory, libxml2
errors mapped to canonical XPaths after checking the element, readable messages, 500-violation
cap, thread-safe). The fetcher gained pinned ZIP archive sources and fetches the official OASIS
`UBL-2.1.zip`; CI caches rule sets by manifest hash. Fixed BT-11 on credit notes and made the
synthetic credit note schema-valid. lxml typing moved to types-lxml. ADR-0004, interview notes.

Verification: 204 tests green; core coverage 100 %; all 29 official examples and both synthetic
fixtures are valid against the real UBL 2.1 schemas; typical mistakes produce the expected
code, XPath and message; schema compile ≈ 150 ms, validation ≈ 0.2 ms per invoice.

Decisions: official archive pinned by SHA-256 over vendoring or a third-party mirror; one rule
id `XSD` with libxml2's error type as the detail code; `null` XPath rather than a guess.

Next: `feat/core-schematron-runner`.

## 2026-11-03 — `feat/core-schematron-runner` (10 commits)

Outcome: third slice of the validator core. `einvoice_core.schematron` runs CEN's official
EN 16931 XSLT and the Peppol BIS Billing 3.0 Schematron with Saxon-HE (`saxonche`); Schematron
sources are compiled with the pinned ISO reference pipeline (`iso-schematron`, new in the
manifest) and cached in `third_party/_compiled/`. SVRL reports become violations with canonical
XPaths and source lines. The synthetic credit note was made valid under EN 16931 (UBL-SR-47,
UBL-CR-001). ADR-0005, learning note 03, interview notes.

Verification: 897 tests green; core coverage 100 %. Conformance suite (marker `conformance`,
643 tests, ~11 s): all 277 CEN unit-test sets (1 131 tests) and all 62 Peppol sets (340 tests),
the 21 CEN and Peppol examples, both synthetic fixtures with zero violations; CEN's flattened
Schematron compiled by our pipeline reports exactly what CEN's XSLT reports on all 1 131 test
documents. Validation ≈ 3 ms per rule set per invoice; first use 0.3–0.9 s per rule set.

Decisions: execute the published rules in process (no JVM sidecar, no re-implementation); the
ISO pipeline for its lineage with the official XSLT; `null` XPath rather than a guess; no
per-layer violation cap (a pipeline concern).

Process note: the gitleaks pre-commit hook could not be installed in the build environment
used for this branch (no access to the Go module proxy). With the maintainer's approval it was
skipped for these commits, and the same gitleaks 8.30.1 scan ran on each commit's staged
changes; CI scans the full history on push.

Windows: the maintainer's runs of the suite on Windows found two portability problems in
older tests (an `EINVAL` instead of `ENOENT`, and official examples listed twice because of a
case-insensitive glob) and one in the fetcher: it judged archive member names after zipfile
had turned backslashes into `/` on Windows, and accepted drive letters on every host. All
three fixed in their own commits on this branch.

Next: `feat/core-srb-cius-rules`.

## 2026-11-04 — `feat/core-srb-cius-rules` (5 commits)

Outcome: fourth slice of the validator core. `einvoice_core.srb` turns SRB-CIUS (version of
06.06.2025), which the Ministry publishes as a table of usage notes without rule identifiers,
into executable rules: one module per rule with an `SRB-NNN` id, the business terms it
concerns and the passages it cites (source registry with document versions); findings become
`srb-cius` violations with canonical XPaths and source lines. Nine rules: invoice type code,
RSD VAT currency, unused BT-7, advance-invoice due date, specification identifier, JBKJS,
VAT identifiers, electronic addresses, PIB serial and check digit. The synthetic seller's PIB
moved into the rulebook's serial range. ADR-0006, learning note 04, interview notes.

Verification: 1 005 tests green; core coverage 100 % (branches included). On the 17 example
documents published with the specification (downloaded by the maintainer, not committed):
SRB-001 to SRB-008 report nothing, SRB-009 reports the four placeholder PIBs of each, and one
example is not schema-valid (its embedded PDF is abbreviated with "..."). EN 16931 rejects
eight of the sixteen schema-valid examples — Serbian code lists, category O next to S, RSD and
extension totals — which the SRB profile will have to set aside explicitly. Nine rules take
0.3–0.4 ms per invoice.

Decisions: rules in Python rather than our own Schematron or a rule DSL; PIB form and PIB
arithmetic as separate rules; severity policy (a stated requirement is fatal, one the official
examples contradict or the text leaves open is a warning until M5); the SRB-CIUS rule set v1
split over three branches (this one, party rules, VAT rules) to keep each reviewable. The
tightened cardinalities were read from the PDF's drawing layer, since text extraction loses
the struck-through values.

Process note: as on the previous branch, the gitleaks hook was skipped with the maintainer's
approval and the same gitleaks 8.30.1 scan ran on each commit's staged changes.

Next: `feat/core-srb-cius-party-rules`.

## 2026-11-04 — `feat/core-srb-cius-party-rules` (7 commits, stacked on `feat/core-srb-cius-rules`)

Outcome: ten more SRB-CIUS rules, SRB-010 to SRB-019: the public-procurement buyer reference
(BT-10), the preceding invoice's issue date (BT-26), legal registration numbers (BT-30, BT-47,
BT-61), the seller's VAT registration status (BT-32, presence and value), cities (BT-37, BT-52,
BT-66) and post codes (BT-38, BT-67, BT-53), the delivery date when BT-8 makes VAT due on
supply or on collection (BT-72), and the notation of payment models (BT-83). The synthetic
SRB invoice now states the seller's VAT status and writes its payment model as SRB-CIUS
prescribes. Interview notes.

Verification: 1 083 tests green; core coverage 100 % (branches included). On the official
examples: SRB-013 (warning) on all 16 schema-valid documents, SRB-017 (warning) on the eight
that omit the buyer's post code, SRB-009 on the placeholder PIBs; nothing else. 19 rules take
0.5–0.7 ms per invoice.

Decisions: the severity policy of ADR-0006 applied for the first time — a missing VAT status
and a missing buyer post code are warnings, a wrong VAT status is fatal, which is why those
requirements are rules of their own; residency read from the country code; SRB-019 fires only
on text that names a model.

Process note: gitleaks hook skipped with approval, scan run on each commit's staged changes.

Next: `feat/core-srb-cius-vat-rules`.
