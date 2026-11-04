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

## 2026-11-04 — `feat/core-srb-cius-vat-rules` (3 commits, stacked on `feat/core-srb-cius-party-rules`)

Outcome: five VAT rules. SRB-020 VAT category codes (S, Z, E, AE, R, O, OE, SS, N) on
breakdowns, allowances, charges and lines, with hints for Cyrillic letters and for `AE20`
written as one code; SRB-021 S and AE at 20 or 10 percent; SRB-022 an exemption reason code
from another category's list (fatal); SRB-023 a code in no list (warning); SRB-024 a code
required for Z, E, R, O, OE, SS and N. The Ministry's list of 1 September 2024 is transcribed
into `einvoice_core.srb.vat` (124 codes, its own keys, PDF hash recorded). Interview notes.

Verification: 1 157 tests green; core coverage 100 % (branches included). On the official
examples the only new finding is SRB-023 on the placeholder exemption code of
`faktura-sa-oslobodjenjem-od-pdv.xml`. EN 16931 run on synthetic Serbian variants: AE at 20 %
fails BR-AE-05 and BR-AE-09, Z with a Serbian code BR-Z-10, S with `PDV-RS-OBJ` BR-S-10, and
every Serbian code BR-CL-22 — added to the SRB profile's set-aside list in the backlog. 24
rules take 0.8–1.2 ms per invoice.

Decisions: category = code + rate (AE with 20, not `AE20`); unknown codes warn because SEF's
copy of the list may be newer; only the invoice-currency breakdown is BG-23; the extension
rules (Table 2) moved to a branch of their own.

Next: `feat/core-srb-cius-extension-rules`.

## 2026-11-04 — `feat/core-srb-cius-extension-rules` (5 commits, stacked on `feat/core-srb-cius-vat-rules`)

Outcome: the extension table of SRB-CIUS. SRB-025 reduced total with VAT = total with VAT
minus paid amount (BT-E13); SRB-026 advances used are also preceding invoices (BT-E1 = BT-25);
SRB-027 the extension's VAT breakdowns also in RSD on foreign-currency invoices (BG-E5,
BG-E6); SRB-028 the RSD VAT breakdown of foreign-currency invoices (BG-E7); SRB-029 the
extended specification identifier when the extension is used (warning). `sbt` became a
canonical prefix for every layer. With this, SRB-CIUS rule set v1 is complete: 29 rules.
Interview notes.

Verification: 1 200 tests green; core coverage 100 % (branches included). On the official
examples the only new finding is SRB-029 on the two final invoices. 29 rules take 0.8–1.2 ms
per invoice.

Decisions: extension amounts parsed defensively (the UBL schema skips extension content);
both spellings of the advances element read; no rule for BT-E10, whose formula the text does
not give and the examples contradict.

Next: BR-CO arithmetic in Python, then `feat/core-fixtures-corpus` and `feat/core-cli`.

## 2026-11-04 — `feat/core-arithmetic-rules` (3 commits, stacked on `feat/core-srb-cius-extension-rules`)

Outcome: the arithmetic layer. `einvoice_core.arithmetic` recomputes BR-CO-10 to BR-CO-17
from the typed model with exact decimals and CEN's semantics — XPath rounding of halves towards
positive infinity, BR-CO-17's tolerance of one currency unit, the presence cases of BR-CO-11,
13, 15 and 16 — and reports the expected and the found amount with the amount's XPath. It reads
the document totals only, so the totals repeated in the Serbian extension, on which CEN's rules
misfire, are not judged as invoice totals. ADR-0007, interview notes.

Verification: 1 231 tests green; core coverage 100 % (branches included). Differential test
against CEN's XSLT: 400 generated invoices per run, no disagreement; a local run of 1 500 had
none either, with every rule firing 89 to 581 times. No arithmetic violation on the 17 Ministry
examples or the synthetic fixtures. 6–10 µs per invoice given the model.

Decisions: CEN's semantics rather than stricter arithmetic under the same rule ids; the model's
scope rather than CEN's relative contexts; per-category taxable amounts (BR-S-08 family) left to
the Schematron layer for now.

Next: `feat/core-fixtures-corpus`, then `feat/core-cli` with the validation pipeline and
profiles.

## 2026-11-04 — `feat/core-validation-pipeline` (3 commits, stacked on `feat/core-arithmetic-rules`)

Outcome: one call for the whole validator. `einvoice_core.pipeline.validate(source, profile)`
reads the document, checks the UBL schemas and, for a schema-valid document, runs the profile's
Schematron rule sets, the SRB-CIUS rules and the calculation rules, and returns a frozen report:
verdict, violations in layer order, which layers ran and why not, and the published rules the
profile set aside with their reasons. Profiles `srb`, `en16931`, `peppol`; CEN's BR-CO rules go
to the arithmetic layer in every profile; the SRB profile sets aside the EN 16931 rules SRB-CIUS
widens, partly by condition on the location (the extension, the RSD copy of the breakdown). The
violation model gained the layer `xml`. ADR-0008, interview notes. The fixtures corpus moves after
the CLI, because its golden results are the pipeline's verdicts.

Verification: 1 255 tests green; core coverage 100 % (branches included). The 17 Ministry
examples under `srb`: only the placeholder PIBs and two genuine problems are fatal; with valid
check digits 15 of 17 are valid with warnings only. Warm 6–12 ms per invoice for the whole
pipeline.

Decisions: set-asides as data with reasons, kept in the report; location conditions rather than
rule ids where a rule is right about the invoice and wrong only about a Serbian copy; stop after
schema errors; a violation limit that does not affect the verdict.

Next: `feat/core-cli`.

## 2026-11-04 — `feat/core-cli` (4 commits, stacked on `feat/core-validation-pipeline`)

Outcome: the `einvoice` command. `einvoice validate PATH ...` runs the pipeline under a profile
and prints each document's verdict with located violations (or, with `--format json`, the full
reports); `--show-set-aside` lists the EN 16931 rules the profile does not apply, with their
reasons. `einvoice rules` lists what a profile checks. Exit status 0 valid, 1 invalid, 2 error.
A path may be a directory or a pattern such as `*.xml`, which cmd and PowerShell leave to the
program. ADR-0009, interview notes, README quick start. Pipeline follow-up: a set-aside
calculation report names only its own rule as the one that checks the matter instead.

Verification: 1 279 tests green; core coverage 100 % (branches included).

Decisions: `argparse` rather than a CLI library; a missing file is an error (2), a malformed
document a verdict (1); JSON ASCII-escaped; streams that cannot encode a character replace it.

Next: `feat/core-fixtures-corpus`.
