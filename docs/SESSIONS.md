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

## 2026-11-04 — `feat/core-fixtures-corpus` (5 commits, stacked on `feat/core-cli`)

Outcome: the fixture corpus. The Ministry's 17 SEF examples are committed byte for byte with the
page, URL and SHA-256 of each (official materials, Article 6 of the copyright law), and a test
pins ADR-0008's evidence: 15 of 17 are valid under `srb` once the placeholder PIBs have valid
check digits. Two new synthetic bases settle an advance with the Serbian extension, in dinars
and in euro. `scripts/make_fixtures.py` generates 43 mutation fixtures, each with one realistic
mistake and the rules the SRB profile must report, every SRB-CIUS rule targeted;
`fixtures/invoices/verdicts.json` records the pipeline's verdicts on 93 documents (SEF,
synthetic, mutations, CEN and OpenPeppol examples), one test per document. ADR-0010, learning
note 05, interview notes.

Findings: BR-CO-25 is not in CEN's UBL Schematron (added to the M5 confirmations); CEN's BR-53
is satisfied by the RSD totals in the extension, so only SRB-028 reports a missing RSD
breakdown on an invoice that has one.

Verification: 1 473 tests green; core coverage 100 % (branches included).

Next: release `v0.1.0` (changelog section, version bump, annotated tag prepared).

## 2026-11-04 — `chore/release-0.1.0` (2 commits, stacked on `feat/core-fixtures-corpus`)

Outcome: milestone M1 released as 0.1.0. Every package moves from 0.0.0 to 0.1.0 (`uv.lock`
updated); the changelog's Unreleased section becomes `[0.1.0] - 2026-11-04`, opened by a summary
of the milestone, with links to the tag; the README roadmap marks M1 done and M2 next. The
annotated tag `v0.1.0` and the release notes are prepared for the maintainer.

Verification: 1 473 tests green; `einvoice --version` and `GET /health` report 0.1.0.

Next: M2, starting with `feat/api-skeleton-db-auth`.

## 2026-11-04 — `feat/api-settings-database` (3 commits, on `main` after `v0.1.0`)

Outcome: the API's persistence layer, the first of three branches that replace the backlog item
`feat/api-skeleton-db-auth`. Settings from the environment (pydantic-settings, `DATABASE_URL` as a
secret, required in production); one async engine per application, a session per request; Alembic
migrations shipped in the package, starting with organizations, users and memberships with the
roles owner, accountant and client; `/ready` checks the database and answers 503. Tests run on a
real PostgreSQL in a database of their own, rolled back per test; the migrations are tested in
both directions and against the models; CI gets a PostgreSQL 16 service and runs upgrade,
downgrade -1, upgrade. ADR-0011, learning note 06, interview notes.

Verification: 1 503 tests green (API 34, coverage 99 %); local PostgreSQL 16.15.

Next: `feat/api-auth-tokens`.

## 2026-11-04 — `feat/api-auth-tokens` (4 commits, stacked on `feat/api-settings-database`)

Outcome: accounts, sign-in and tokens. Registration creates an account, its organization and the
owner's membership; sign-in returns a 15-minute JWT access token (HS256, `at+jwt`, every claim
required) and a 30-day refresh token, stored as a SHA-256 digest, spent on use, whose replay
revokes the whole session; refresh re-reads the role and ends the session of a deactivated person
or a former member. Passwords: argon2id with OWASP's minimum parameters, in a worker thread,
rehashed when the parameters change, the same answer and timing for unknown addresses. Migration
`0002` adds the hashes and the refresh tokens. ADR-0012, learning note 07, interview notes,
`SECURITY.md` ticked where done.

Findings: coverage lost lines after awaited database calls until `concurrency = ["thread",
"greenlet"]` (SQLAlchemy's asyncio layer runs the ORM in greenlets); an empty `SEF_JWT_SECRET=`
copied from `.env.example` stopped the API until empty variables counted as unset.

Verification: 1 561 tests green with PostgreSQL (API 92, coverage 99 %).

Next: `feat/api-rbac-api-keys`.

## 2026-11-04 — `feat/api-rbac-members` (5 commits)

Outcome: authorization and the people of an organization.

- Endpoints ask for a permission that one table grants by role. The owner holds every
  permission, an accountant `members:read`, a client neither.
- `require()` reads the current membership on every guarded request, so removal, deactivation
  and role changes act at once. For `members:manage` it checks the role again under the
  organization's lock.
- `/members` lists, re-roles and removes members, and keeps at least one active owner.
- Invitations are one-time codes stored as digests, redeemed with
  `POST /auth/accept-invitation`. Redeeming creates the account or asks for its password. An
  invitation stops working when its issuer may no longer invite.
- One advisory lock per organization orders the work: exclusive for changes to the members,
  shared for sign-in, refresh and sign-out. The tokens of one session are then locked by id.
- A route audit with a pinned permission per endpoint, a refused-role test and a cross-tenant
  case for every guarded endpoint run in CI.
- Migration `0003`, ADR-0013 (amending ADR-0012), learning note 08, interview notes.

Findings:

- FastAPI 0.162 keeps an included router as a single route, so the audit walks into it and
  cross-checks against OpenAPI, to fail loudly should it ever see nothing.
- An independent review of the first version found five defects, each confirmed with a test:
  1. A removed or demoted owner could return through an owner invitation issued before. Such
     invitations are now withdrawn, and accepting checks the issuer again.
  2. A replayed refresh token deadlocked with a removal.
  3. A refresh during a removal minted a token that survived it.
  4. A demotion between the permission check and the change let the change through.
  5. The last-owner rule counted deactivated owners.
  Defects 2 and 3 led to share mode for sessions; defect 4 to the check under the lock.
- The review also found test gaps:
  - A weaker permission on one route passed the audit.
  - Mounted applications were invisible to the audit.
  - Removing a lock or a `commit()` left the suite green, because every request shared one
    rolled-back transaction.
  The fixes are pinned permissions, refused-role tests, a check for unknown route types, and
  tests on real committing sessions that hold one request at a gate. Each seeded fault now
  fails the suite.
- The review of the fixes confirmed all five and found three more problems:
  - The tokens of one session still raced each other. This was left from
    `feat/api-auth-tokens`: a sign-out or a replay during a refresh let the new token survive,
    and two replays deadlocked.
  - Shared row locks could starve a change to the members, because PostgreSQL does not queue
    `FOR SHARE` behind a waiting `FOR NO KEY UPDATE`.
  - Listing invitations took the exclusive lock.
  These led to session tokens locked by id, an advisory lock granted in arrival order (a test
  shows row locks fail it), no lock for tokens that can do nothing, and a lock only for
  endpoints that change the members.

Verification: 1 671 tests green with PostgreSQL (API 202, coverage 99 %).

Next: `feat/api-invoices-validate`, then `feat/api-keys`, so that an API key has something to be
allowed to do.

## 2026-11-04 — `fix/core-hostile-documents` (7 commits)

Outcome: the validator survives the documents the two reviews of the invoice endpoint built
against it.

- `canonical_xpath` and the SVRL resolver read each element's children once per validation
  (`sibling_index()`, a context-scoped index) instead of all siblings for every element.
- A number of more than 28 digits is a `MODEL` violation. The SRB-CIUS and arithmetic checks
  compute in a 128-digit context, where sums and products of such numbers are exact.
- The parser drops comments and processing instructions, so every layer reads a value whole.
- The set-aside list of a report is cut at the violation limit, and the rest counted.
- Saxon's processor is made from a configuration file that sends its error stream to the
  null device, and without one, with a warning, where that device cannot be opened.
- Tests pin that the parser expands no entity, reads no DTD and opens no socket.
- ADR-0014 (which amends ADR-0008), interview notes.

Findings:

- The first review of `feat/api-invoices-validate` measured the problems and confirmed each
  one:
  - 8000 lines took 39 s, 8000 empty document references 73 s;
  - an amount of 10^27 made the pipeline raise `InvalidOperation` under every profile;
  - a seller with two VAT identifiers made Saxon print their country prefix on stderr.
- A profile found the quadratic part: `canonical_xpath`, 3.3 s of 5.7 s at 3000 lines. After
  the fix, 8000 lines take 5 s and 8000 references 22 s. The rest is inside the published
  rule sets, whose cost grows faster than linearly with failing elements.
- Python's default decimal context also rounded sums beyond 28 digits silently; a test of
  28-digit amounts that add up shows it, failing BR-CO-10 without the exact context.
- Saxon ignores its error-stream setting once the processor exists. Only a configuration
  file read when the processor is made works, which a test proves on the file descriptors.
- Saxon holds the GIL while it transforms: the main thread stalled 1.7 s during a 2 s run.
  That is for the API to handle; the branch records it in ADR-0014.
- The second review found what the first version of this branch still let through:
  - A comment inside a value split it into two text nodes, and the model read only the
    first. `14400<!-- -->1` was 14400 to the arithmetic layer and 144001 to the schema and
    to CEN's rules, whose BR-CO-16 is set aside for ours, so an invoice due ten times its
    total was valid under two profiles. Put in the middle of every value of the corpus,
    comments changed 87 of 91 verdicts. Choosing the parser's flags over reading the string
    value at each of eleven places also covers the Peppol rules, which read `text()` and
    stopped with an error on a split identifier.
  - The set-aside list had no limit: 8000 empty elements in an extension, 144 KB, made
    16 005 set-aside reports and a report of 7.6 MB, now 0.5 MB.
  - `\d` accepted Arabic-Indic and full-width digits in the Serbian extension, which
    `Decimal` reads as 0 to 9.
  - Saxon refuses a configuration whose file it cannot open, which would have stopped all
    validation where the null device cannot be opened.
  - Mutations that left the suite green: DTD loading turned on, a layer's entry point
    without its index, SRB rules outside the exact context. Each now fails a test.
  - Fetching an external DTD is stopped twice over: the bundled libxml2 has no HTTP client,
    and `no_network` is set. No test can show the second here.
- On Linux, a configuration naming `nul`, as `os.devnull` does on Windows, made Saxon create
  a file of that name in the working directory. On Windows that name is the null device; the
  maintainer's run of the core tests there has to show that Saxon opens it as such.

Verification: 1 795 tests green with PostgreSQL (core 1 530, coverage 100 %); without it
1 649 pass and 146 are skipped. Every commit was checked on its own.

Next: `feat/api-invoices-validate`, stacked on this branch.

## 2026-11-04 — `feat/api-invoices-validate` (4 commits, stacked on `fix/core-hostile-documents`)

Outcome: the validator behind the API, bounded, with nothing stored.

- `POST /invoices/validate` takes the invoice as the request body (`application/xml`) and
  answers with the validator's own report for `?profile=` (`srb` by default). Nothing is
  stored, and the answer is marked `Cache-Control: no-store`.
- Limits:
  - bytes: 413 beyond `SEF_MAX_INVOICE_BYTES`, declared or counted while read;
  - time: 408 for a body that has not arrived within `SEF_UPLOAD_SECONDS`;
  - elements: 413 beyond `SEF_MAX_INVOICE_ELEMENTS`, counted before any validation;
  - type: 415 for anything but XML.
- The validator runs in a child process, warmed up with the application, one invoice at a
  time. It is killed at `SEF_VALIDATION_SECONDS` (422) and replaced, as is a child that dies.
  Admission turns away the ninth validation in flight (503, `Retry-After`).
- A turn, once begun, ends whole even when its request is cancelled, and every answer names
  the message it answers.
- Every role holds `invoices:validate`; the route audit pins it, with a cross-tenant case.
- ADR-0015, learning note 09, interview notes. ADR-0013 and its notes now call the
  organization's lock the advisory lock it is.

Findings:

- The first version validated in a worker thread. An independent review of it measured:
  - one client stalling every other request, sign-ins included, for 5 s with one document
    and 42 s with seven;
  - schema-valid documents that crashed the validator, or made Saxon print invoice data;
  - a half-installed rule set crashing the startup while `/ready` said "ok";
  - tests that passed with the parser's hardening switched off, or with the body read whole.
  The core's share became `fix/core-hostile-documents`; this branch now bounds what remains.
- Saxon holds the GIL: a 2 s transform stalled the main thread for 1.7 s. Hence a process,
  not a thread. With it, `/health` answered within 5 ms while a validation ran into its limit.
- Memory, not bytes, sets the limits: a warm child holds about 210 MiB, and a document near
  20 000 elements adds 80 MiB, or 210 MiB if every line breaks a rule.
- The endpoint first held its database connection while it read the body and validated.
  Fifteen slow uploads would have used up the pool; the transaction now ends right after the
  permission check, and a test watches the pool.
- uvicorn on Windows with `--reload` runs a selector event loop, which cannot start
  subprocesses. So the child is started with `multiprocessing`, and its pipe is read in a
  thread.
- A second review, of the child process, found one leak and five tests that could not fail:
  - A request cancelled while the child worked released the lock, and the turn's settling
    (the kill at the time limit) never ran. The child's late answer stayed in the pipe, and
    the next request, of any organization, read it as its own; every answer after it was one
    behind. Nothing in the shipped stack cancels a request, but a timeout around the call
    would. The turn now runs in a shielded task, and messages are numbered.
  - Mutations that left the suite green: no admission check before the body is read; the
    error's message logged for any error; the child without its silenced streams; a counter
    that keeps what it counts; Saxon without its configuration, seen through the API. Each
    now fails a test.
  - Peak memory read with `getrusage` in a child process includes the peak of the process it
    was forked from, so the counter's memory test reads `VmHWM` from `/proc` instead (Linux).
  - The residual cost is the published rule sets': a document within the element budget can
    still run into the time limit (8000 empty extension elements take 15 s), so one member can
    keep the validator busy until `feat/api-rate-limits`.

Verification: 1 879 tests green with PostgreSQL (API 286, coverage 100 %); without it 1 700
pass and 179 are skipped. Every commit was checked on its own.

Next: `feat/api-invoices-store`, then `feat/api-keys`.

## 2026-11-04 — `feat/api-invoices-store` (6 commits)

Outcome: an organization keeps its invoices, each with the validator's report on it.

- `POST /invoices` validates the body as `/invoices/validate` does and stores the document
  byte for byte with the report and what the validator read: 201 and `Location`. An unreadable
  document is stored with the report that says why.
- `GET /invoices` lists the newest first, a page at a time with an opaque keyset cursor;
  `GET /invoices/{id}` adds the report; `GET /invoices/{id}/content` downloads the document as
  an attachment with `nosniff`; `DELETE /invoices/{id}` deletes it.
- Owners and accountants see every invoice of the organization (`invoices:manage`), a client
  the ones they submitted (`invoices:submit`); anything else answers 404.
- An organization stores at most `SEF_MAX_STORED_BYTES` (100 MiB) of documents and reports
  together, under an advisory lock on its invoices; 507 beyond.
- Migration 0004, ADR-0016, learning note 10, interview notes.

Findings:

- A list needs what the validator read, so the child now sends a summary with its report:
  built from the model, only for a schema-valid invoice, each text cut at 200 characters.
- A report can be many times its document: an invoice that breaks a thousand rules has a report
  of hundreds of KiB. A quota on documents alone would leave reports unbounded, so it counts
  both.
- Adding up and storing is a check-then-act race. A test makes two uploads add up at the same
  moment: without the lock both are stored, with it one.
- The upload and the validation outlast the transaction of the permission check, so it is
  made again where the invoice is stored; a test removes the member during the validation.
- PostgreSQL's `now()` is the start of the transaction, so invoices can share a time. The
  cursor carries the id as well, and a test reads three invoices of one moment one per page.
- The core's report models are strict, and a report read back from JSONB has lists where they
  have tuples: it is validated in lax mode.
- Since the parser drops comments (ADR-0014), the API's log test hid its marker where the
  validator never sees it; the marker now sits in a note.

Verification: 1 925 tests green with PostgreSQL (API 332, coverage 100 %); without it 1 707
pass and 218 are skipped. Every commit was checked on its own.

Next: `feat/api-keys`, then `feat/api-rate-limits`.

## 2026-11-04 — `feat/api-keys` (8 commits)

Outcome: machine clients such as ERPs authenticate with API keys that act for a member.

- `POST /api-keys` issues a key, `sefk_` and 256 random bits, shown once and kept as a SHA-256
  digest. It holds chosen invoice permissions that the member's role grants. `GET /api-keys`
  lists the keys that work and `DELETE /api-keys/{id}` revokes one: a member manages their
  own, an owner every key of the organization.
- `Principal.may()` asks both the role at that moment and the key. A demoted member's keys
  shrink, a deactivated account's are refused, and a removed member's are deleted with the
  membership.
- A key administers no one and issues no keys. Every guarded endpoint has a cross-tenant case
  with another organization's key, and the endpoints no key may use refuse it.
- A member has at most 20 keys that work, counted under a lock. Storing an invoice checks
  again that the key still works.
- Every answer that carries a credential is `no-store`, and `.gitleaks.toml` recognizes a key.
- Migration 0005, ADR-0017, learning note 11, interview notes.

Findings:

- Checking the membership when a key is used would not be enough: a member removed and invited
  back would find their old keys working again. A key belongs to its membership by a composite
  foreign key and is deleted with it.
- The answers with tokens (registration, sign-in, refresh, accepting an invitation) and with an
  invitation's code had no `Cache-Control: no-store`, which RFC 6749 requires. Fixed in its own
  commit.
- The check made again before storing an invoice looked at the membership only, so an upload
  with a key revoked meanwhile would have been stored. It checks the key too.
- The invoice scope read the role table directly. It now asks the principal, so a key without
  `invoices:manage` sees its member's invoices only, even an owner's key.
- Keys issued in one test transaction share `now()`, so the tests that order keys set their
  times.

Verification: 2 001 tests green with PostgreSQL (API 408, coverage 100 %); without it 1 715
pass and 286 are skipped. Every commit was checked on its own, and every rule a key obeys was
checked by seeding the fault that breaks it.

Next: `feat/api-rate-limits`, then `feat/api-jobs-sse`.

## 2026-11-04 — `feat/api-rate-limits` (5 commits, stacked on `feat/api-keys`)

Outcome: the API limits how often a client may sign in, register, refresh, accept invitations
and validate, and says when to try again.

- A rate limiter in the API's process uses GCRA: one moment per key, a burst and a pace,
  integer nanoseconds of a monotonic clock, at most 100 000 keys.
- Per address: sign-in 30 a minute, registration 10 an hour, refresh and sign-out 60 a minute,
  accepting an invitation 10 a minute.
- Per e-mail address: 10 wrong passwords in 15 minutes, counted before the next password is
  checked, for addresses without an account alike, at sign-in and when an invitation is
  accepted.
- Per caller (a member, or one API key) and per organization: `SEF_VALIDATIONS_PER_MINUTE`
  (60) and `SEF_ORGANIZATION_VALIDATIONS_PER_MINUTE` (300), storing included, counted before
  the body is read.
- 429 with `Retry-After` and a detail that names the limit, documented in OpenAPI.
- ADR-0018, learning note 12, interview notes.

Findings:

- A limit per address alone would not stop a guess at one account from many addresses; the
  count per e-mail address does, and it has to come before the password check to reveal
  nothing and cost no hash.
- Accepting an invitation checks an existing account's password. Without the shared guard, a
  code would have let anyone guess at that account where sign-in holds them back.
- A thread test passed without the limiter's lock, because nothing interleaved. A limit whose
  arithmetic sleeps makes the threads interleave, and the test now fails without the lock.
- `X-Forwarded-For` is the client's to write. The limiter keys on the address the server saw,
  and a test checks that the header changes nothing.

Verification: 2 038 tests green with PostgreSQL (API 445, coverage 100 %); without it 1 733
pass and 305 are skipped. Every commit was checked on its own, and every limit was checked by
seeding the fault that breaks it.

Next: `feat/api-jobs-sse`, then `feat/rag-corpus-ingest`.

## 2026-11-05 — `feat/api-jobs-sse` (7 commits)

Outcome: work that outlasts a request runs as a job that survives its worker, a member follows
it as server-sent events, and the first job validates stored invoices again.

- `jobs` (migration 0006): the row is the truth; `version` for readers, `attempts` as a
  fencing token, and a partial unique index that allows a member one unfinished job of each
  kind.
- Running a job: taking it on counts an attempt, and every later write requires the attempt to
  be the latest. An attempt sees the progress of those before it, and may write its progress in
  the transaction of the work it counts, so that it continues where they stopped and a
  superseded attempt leaves nothing behind.
- `POST /invoices/revalidations`: the invoices the caller may see, stored by the time the job
  started, one per transaction with its count; a larger report held to the quota under the
  upload lock; 409 while one is under way. `validated_at` (migration 0007) amends ADR-0016.
- `GET /jobs/{id}` and `GET /jobs/{id}/events`: the stream reads the job once a second without
  holding a connection, numbers its events with the job's version for `Last-Event-ID`, answers
  404 before it begins, and ends with the finished job or after five minutes.
- Runners: inline by default, resumed when the API starts and cut short when it stops;
  `SEF_JOBS=arq` with `REDIS_URL` and `python -m sef_api.jobs.worker`, ids taken once, no
  results kept, a sweep when a worker starts and every minute, attempts of at most an hour.
  CI runs the worker tests on Redis.
- ADR-0019, learning notes 13 (SSE vs. WebSockets) and 14 (idempotent jobs), interview notes.

Findings:

- A fence on the progress alone would not have stopped a superseded attempt's report: the
  invoice's update would have been committed on its own. The report and the count are one
  transaction, and a test makes the two attempts judge the invoice differently.
- arq keeps a job's result for an hour by default, and takes no id again while it does: a job
  cut short by its time limit could not have gone back on the queue. Results are not kept, and
  a test cuts an attempt short and lets the next worker continue it.
- A stream's dependencies last as long as the stream. Without committing first, every open
  stream would hold a pooled connection; a test counts the connections checked out while a
  stream waits.
- The invoices deleted before the job reached them never turn up, so `done` would have ended
  short of `total`; the result counts them as deleted.
- httpx's ASGI transport hands a response over only once it is complete. The stream tests use a
  small ASGI client that sees each event as it is sent.
- Render's free web service has no background worker: a free deployment runs jobs inline.

Verification: 2 108 tests green with PostgreSQL and Redis (API 515, coverage 100 %); without
them 1 744 pass and 364 are skipped. Every commit was checked on its own, and the guards were
checked by seeding the faults that break them: 51 seeded, 50 caught, and the one left is a
second tenant filter behind the first.

Next: `feat/rag-corpus-ingest`.

## 2026-11-05 — `feat/rag-corpus-ingest` (8 commits)

Outcome: the corpus that explanations will cite: the five official documents the SRB-CIUS
rules are authored from, as passages that know the days they apply, loaded into PostgreSQL
with a trigram index and, when configured, embeddings.

- `corpus/`: the Law and the Rulebook on Electronic Invoicing in two editions each, the PIB
  rulebook, the SRB-CIUS specification (its sections and the rows of its two tables) and the
  Ministry's tax categories: seven editions, 385 dated passages. `manifest.toml` pins each
  source by URL and SHA-256 and records the day each edition applies from, the passages its
  amending act defers and the articles it renumbers.
- `scripts/build_corpus.py` (`make corpus`, `make corpus-check`): the Legal Information
  System's consolidated texts and the Ministry's two PDFs as Markdown editions, without what
  the publishers added; a source whose digest changed is refused.
- `sef_api.rag.corpus`: editions compared key by key give each passage a half-open interval
  of days and an id that names its first; a file the converter would not write is refused.
- `sef_api.rag.citations`: every reference of the 29 rules resolves on any day.
- `corpus_documents` and `corpus_passages` (migration 0008), without `organization_id`:
  `search_text` folded to Latin letters without diacritics under a trigram index, and
  `embedding vector(1024)` under an HNSW index.
- `python -m sef_api.rag.ingest` (`make ingest`): the tables made to hold exactly the corpus;
  with `EMBEDDINGS_PROVIDER=jina`, what has no embedding of the model is embedded, 32 to a
  request and a transaction, so an interrupted ingest resumes.
- ADR-0020, learning note 15, interview notes. The Langfuse and Sentry wiring moves to M4.

Findings:

- The 2027 amendment moves the import list from Article 4b to 4v on 1 January and gives 4b to
  the recording of purchases from farmers from 1 July, so between the two days no Article 4b
  applies. Without the renumbering in the manifest, the import list would have been cited as
  the farmers' article.
- The Legal Information System writes Latin letters inside Cyrillic words ("Члaн" with a Latin
  "a"), and the specification Cyrillic ones inside identifiers ("BТ-121"): a search would have
  missed them, and a rule's reference would not have resolved.
- The specification prints `BT-64` for `BT-65` and `BT-31` for the group `BG-31`. The two are
  corrected, each with its reason; typing errors in the text are kept as printed.
- An embedding is stored only while the passage's digest is the one embedded. Without that, a
  passage changed by another ingest while this one embedded it would have kept the vector of
  its old words.
- pdfplumber brings in cryptography, which narrows PyJWT's types: a test that signed with no
  key now signs with an empty one.
- Seeding faults found nine that no test caught: a changed label, heading or part of an
  otherwise unchanged passage, the wait `Retry-After` names and its bound, the 32 texts to a
  request, a key without `EMBEDDINGS_PROVIDER=jina`, a document's changed columns, a passage
  two references name, and the lock itself. Two ingests of one corpus also wait for each other
  on its documents' rows, so the test of two at once passed without the lock; a test now holds
  the lock and sees the ingest wait. Each has a test, and the tables' checks, key and cascade
  have tests of their own.
- This environment cannot reach the official sites, and CI does not download them. The
  sources were downloaded in a browser and their digests checked, and the converter's downloads
  were tested against a stand-in for the network; `make corpus` against the live sites is the
  maintainer's to run.

Verification: 2 241 tests green with PostgreSQL, Redis and the downloaded sources (API 622,
coverage 100 %); without them 1 853 pass and 388 are skipped. The corpus ingested twice into
an empty database: 385 passages added, then 385 unchanged; "sifra vrste fakture" finds BT-3
first through the trigram index. Every commit was checked on its own, and the guards were
checked by seeding the faults that break them: 88 seeded, 87 caught. The one left gives the
corpus's lock the first key of the invoice storage's, which would only make an ingest wait for
an upload; the two corrected identifiers are checked only with the sources downloaded.

Next: `feat/rag-explain-citations`.

## 2026-11-05 — `fix/rag-corpus-sources` (1 commit)

Outcome: `make corpus` downloads the Legal Information System's texts. The maintainer's first
run against the live sites kept only the two PDFs of the Ministry.

- `corpus/manifest.toml`: the five digests of the system's texts are those of a download, which
  begins with a line that names the system; a comment says why.
- The converter already left that line out, with everything before the first article; the
  test text has it now, so a reader that kept it would fail. Interview notes for the branch.

Findings:

- The system starts a text with "Преузето са https://pravno-informacioni-sistem.rs" unless the
  request comes from its own web application, by its `Referer`. The sources had been pinned as
  the browser received them inside the application, so a download from anywhere else failed
  its digest. Sending the application's `Referer` would have returned the pinned bytes, but it
  would have passed the converter off as the application; the digests follow what a plain
  client receives instead.
- Either form is the same on every request: three downloads of each text gave the same bytes.

Verification: the five sources, rebuilt from the pinned ones with the line added, have the
digests of the system's answers; `build_corpus.py --check` says the corpus is what they make,
and the converter's tests pass.

Next: `feat/rag-explain-citations`, stacked on this branch.

## 2026-11-05 — `feat/rag-explain-citations` (5 commits)

Outcome: the second layer. `POST /invoices/explain` validates an invoice and explains each rule
its report names, in Serbian or English, citing the corpus's passages that apply on the
invoice's issue date; every citation is a stored passage.

- `sef_api.llm`: `LLMClient` and `GroqClient` (`openai/gpt-oss-120b`, strict structured
  outputs, temperature 0, brief reasoning that is not sent back); `LLM_PROVIDER=none` by
  default, `GROQ_API_KEY` required with `groq`.
- `sef_api.rag.retrieval`: the rule's references, the BT and BG terms, the place, the tax
  codes, then words and meaning fused by reciprocal rank; six passages at most, all applying
  on the day.
- `sef_api.rag.explainer`: the question as delimited data within 6 000 characters, a schema
  whose citations are an enum of the ids given, the answer checked again and sent back with
  the reason, three answers at most; each rule once, fatal first, five at most, in 30 seconds.
- The endpoint counts as a validation and against limits of its own, answers 503 without a
  model before it reads anything, stores nothing, and logs nothing of the invoice.
- ADR-0021, learning note 16, interview notes; SECURITY.md marks the no-store mode, the rate
  limits and the citation guard done for explanations.

Findings:

- The embedder would have been sent the invoice. The messages of the SRB-CIUS rules, the
  arithmetic and the schema quote PIBs, amounts and dates, and embedding them to search by
  meaning would have made Jina a second party that sees invoices, where ADR-0020 accepted it
  for public text only. It came up while SECURITY.md was being written. The meaning is now
  searched with what the rule says: a Schematron rule's message, an SRB-CIUS rule's title, an
  arithmetic rule's statement; a test checks that none of the 2 128 messages of the pinned
  rule sets is computed from the document.
- Embedding was outside the time limit: Jina's client waits up to 60 seconds, four times,
  before it gives up. It now has a fifth of the request's time, after which the words find the
  passages alone.
- A message can quote any text of the invoice, a buyer reference among them, so one could
  close the tag it is sent in. Its angle brackets are escaped.
- The schema's messages name elements (`cac:Party`) that every row's path shares, so their
  words found every party; the place finds them better. English messages find the Serbian
  rows because the rows' headings carry the English term: `BR-CO-15`'s message finds BT-109,
  BT-112 and BT-110 at 0.75, 0.70 and 0.60.
- The lists of tax categories run to 8 500 characters. Passages are cut to 2 000 and 6 000 in
  all, which keeps a question near 2 000 tokens, a quarter of the free tier's minute.
- `reasoning_effort` and `include_reasoning` belong to the GPT-OSS models: another model that
  `SEF_LLM_MODEL` names is not sent them.
- Seeding faults: 87 seeded, 73 caught at first. The test of the fusion passed whatever the
  fusion did, because its rule (SRB-008) found both passages by its references first; it now
  uses no rule and checks that a passage second in both lists comes before one first in one.
  Also missed: the bounds of the day for references and meaning, a code another category's
  code begins with (PDV-RS-6 and PDV-RS-6-1-1), a rule that names categories it does not cite
  (SRB-020), the bound of the backoff, the lengths of the texts, the prompt's "never invent",
  and the endpoint's time and embedder. Each has a test now; the one left changes nothing, as
  the specification's paths always go below the root.
- Not measured here, for want of a key and a route to Groq: the latency and the quality of a
  live explanation. The PR's test measures the latency; the evaluation set of M6, the quality.

Verification: 2 320 tests green with PostgreSQL, Redis and the downloaded sources (API 701,
coverage 100 %); without them 1 899 pass and 421 are skipped. Every commit was checked on its
own, and the guards by seeding the faults that break them: 87 seeded, 86 caught. A smoke run
against the scratch database with a stand-in model answered in 100 to 170 ms.

Next: `feat/api-invoices-by-verdict` (stored invoices listed by verdict, finished jobs deleted
after a period), then the scheduled check of the corpus's sources and the release `v0.2.0`.

## 2026-11-05 — `feat/api-invoices-by-verdict` (2 commits)

Outcome: `GET /invoices?valid=false` lists the stored invoices whose latest report is invalid,
and `valid=true` the valid ones, a page at a time: after a revalidation, the invoices it found
invalid. The invalid ones are read through an index of their own.

- `store.page_of` and the route take `valid`; the cursor continues a filtered list as it
  continues the whole one, and a client still sees only what they submitted.
- Migration 0009: `(organization_id, created_at, id) WHERE NOT valid`, built and dropped
  `CONCURRENTLY` inside Alembic's `autocommit_block`, after dropping what a failed build left.
- Learning note 17 (partial indexes), interview notes. Deleting finished jobs and the retention
  of stored invoices are split off in the backlog: how long accounting documents are kept is
  the maintainer's decision.

Findings:

- SQLAlchemy writes a comparison with Python's `False` as the constant `valid = false`, which
  the planner simplifies to `NOT valid`, so the partial index serves the listing in a custom
  plan and in the generic plan of a prepared statement alike. `EXPLAIN` of a statement with
  parameters plans with their values, so a bound parameter would pass a test of the plan; the
  test checks the statement's text as well.
- `alembic check` compares an index's name and columns with the model's, not its predicate: a
  model that said `WHERE valid` passed it. A test compares the model's predicate with the
  database's.
- The upgrade's drop of what a failed attempt left also hid a downgrade that kept the index: a
  test now undoes 0009 and looks for it.
- One run in seven of the whole suite had a failure the others did not repeat. The likeliest
  cause was the test of the plan, which then rested on the table's statistics to choose
  between the listing's two indexes. It rests on nothing now: it turns sequential scans off
  and drops the other index inside its own transaction, so that the plan reads the partial
  index exactly when the planner may.

Verification: 2 326 tests green with PostgreSQL and Redis (API 707, coverage 100 %); without
them 1 899 pass and 427 are skipped. Every commit was checked on its own, and the guards by
seeding the faults that break them: 12 seeded, 10 caught at first, the other two by the tests
added for them.

Next: `ci/corpus-sources-check`, a scheduled job that downloads the corpus's sources and
reports a digest that changed; then the release `v0.2.0`, once the latency of a live
explanation is noted.

## 2026-11-05 — `ci/corpus-sources-check` (1 commit)

Outcome: a workflow downloads the corpus's sources afresh each Monday, and by hand, and fails
when one is not what the manifest pins or the corpus not what they make.

- `.github/workflows/corpus-sources.yml`: `--fetch --check` with `contents: read`, no cache of
  the sources, and the actions pinned to the commits `ci.yml` uses.
- `corpus/README.md` says how a failure is reported, and that in a public repository GitHub
  stops scheduled workflows after 60 days without activity. Interview notes.

Findings:

- The converter's errors already tell a site that did not answer ("cannot download …") from a
  text that changed (its new SHA-256), so the job needs nothing of its own to say which.
- Not run here: the build environment has neither GitHub's runners nor a route to the official
  sites. pre-commit checks the workflow against its schema; its first run, started by hand from
  the Actions tab after the merge, is the test.

Verification: pre-commit on all files, the workflow's schema included; no code changed, and the
2 326 tests of the branch below pass.

Next: the release `v0.2.0` once the four branches are merged and the latency of a live
explanation is noted; then deleting finished jobs and the retention of stored invoices, with the
period the maintainer chooses.

## 2026-11-06 — `chore/release-0.2.0` (2 commits)

Outcome: milestone M2 released as 0.2.0. Every package moves from 0.1.0 to 0.2.0 (`uv.lock`
updated); the changelog's Unreleased section becomes `[0.2.0] - 2026-11-06`, opened by a summary
of the milestone, with links comparing the tags; the README roadmap marks M2 done and M3 next,
and the architecture's status says so. The annotated tag `v0.2.0` and the release notes are
prepared for the maintainer.

- Decided with the maintainer: the release goes out now, and retention moves to M3. Finished
  jobs are deleted 30 days after they end; stored invoices are kept until their organization
  sets a period of its own, none by default. The SEF internal technical instruction moves to M5,
  beside the SEF demo.
- The weekly check of the corpus's sources, run by hand on `main`, passed in 46 seconds: the
  official sites answer GitHub's runners.
- The first live explanation, by the maintainer with Groq's free tier: `SRB-009` for the
  synthetic invoice whose PIB has a wrong check digit, in 1.5 s for the whole request, against
  a budget of 6 s. It cited the PIB rulebook and the specification's BT-31 and named the right
  check digit (4, not 5). Its fix, though, gave a corrected PIB "for example", which the prompt
  forbids: a deterministic check of the values an answer names is now in the M3 backlog.
- Windows PowerShell 5.1 showed the answer garbled: it reads a JSON body without a `charset` as
  ISO-8859-1, so `č` became `Ä` and the model's „RS“ quotation marks, read as C1 control codes,
  hid the letters between them. The bytes are right; declaring `charset=utf-8` is in the
  backlog.

Verification: 2 326 tests green; `einvoice --version` and `GET /health` report 0.2.0.

Next: M3, starting with `feat/repair-patch-engine` (the patch model and the forbidden-field
guard).

## 2026-11-06 — `fix/api-json-charset` (1 commit)

Outcome: every JSON answer says `application/json; charset=utf-8`, through a small ASGI
middleware (`sef_api.charset.DeclareUTF8`) that covers FastAPI's own answers too: validation
errors, unknown paths and the OpenAPI document.

Findings:

- The maintainer's first live explanation came out garbled in Windows PowerShell 5.1, which
  reads a body without a `charset` as ISO-8859-1. The bytes were right; the client guessed.
- A response class with the charset in its media type would have missed FastAPI's own handlers
  and written `application/json; charset=utf-8` as the content key of every operation in the
  OpenAPI document.
- Seeding faults: four seeded (no middleware, every type rewritten, any header rewritten, the
  lifespan wrapped), four caught.

Verification: API 710 tests, coverage 100 %.

Next: a deterministic check of the values an explanation names, the other finding of the live
test; then `feat/repair-patch-engine`.

## 2026-11-06 — `fix/rag-explanations-invent-no-values` (1 commit)

Outcome: an explanation names no date, amount, rate or identifier that its question does not
contain (ADR-0022, amending 0021). An answer that does goes back to the model with the values it
named, within the three answers allowed; the prompt says "not even as an example, and do not
compute one"; the model's non-breaking hyphens and spaces become plain ones.

Findings:

- The first live answer to `SRB-009`, which the maintainer asked for before the release, gave
  a corrected PIB "for example" in its fix, although the prompt forbade inventing an
  identifier: the one rule of the model that only words held.
- Comparing values as written would refuse the model's Serbian notation: the message says
  `1200.00` and the model `1.200,00`, the question `2026-10-05` and the model `5. 10. 2026`.
  Dates are compared as ISO 8601 and numbers as their digits; short plain numbers (a check
  digit, the 7064 of ISO 7064) are not values at all.
- Seeding faults: seven seeded (no check, every number a value, dates or numbers compared as
  written, hyphens kept, ten digits for an identifier, the prompt's new sentence); six caught at
  first, the seventh by a test of the prompt added for it.

Verification: 2 334 tests green with PostgreSQL and Redis (API 715, coverage 100 %); without
them 1 907 pass and 427 are skipped.

Next: `feat/repair-patch-engine`, the patch model and the forbidden-field guard, with its ADR.

## 2026-11-06 — `test/api-worker-sweep-race` (1 commit)

Outcome: the worker test of an attempt cut short no longer depends on the minute it runs in.
The tests' workers keep the sweep at startup and move the sweep at second 0 of every minute
half an hour away, everything else of the production schedule kept; a test pins that schedule
as `worker.options` gives it.

Findings:

- The maintainer's CI for `fix/api-json-charset` failed in
  `test_an_attempt_cut_short_is_swept_back_and_the_next_one_continues`: the job had succeeded
  after the first worker, where the test expects it still running.
- arq queues a cron job whose next run is less than a second away, deferred until then, and a
  burst worker runs until its queue is empty, deferred jobs included. A first worker alive in
  the last second before a minute waited for that minute's sweep, which put the job cut short
  back on the queue, and the second attempt ran in the first worker.
- Reproduced at will: started three seconds before a full minute, the test failed twice out of
  twice. With the fix it passed at the same moment, its first worker ending before the minute
  instead of waiting for it.

Verification: 2 334 tests green with PostgreSQL and Redis, the commit on its own. Three faults
seeded into the production schedule (no sweep at startup, second 30, minutes 0 and 30), three
caught by the test that pins it.

Next: `feat/repair-patch-engine`, the patch model and the forbidden-field guard, with its ADR.

## 2026-11-06 — `feat/repair-patch-engine` (7 commits)

Outcome: the deterministic half of layer 3 (ADR-0023). A patch `{xpath, op, value, reason}`
names its place with the canonical path a violation reports, read by a grammar and walked step
by step; it replaces a value, adds a basic component with the aggregates on its way where the
UBL 2.1 schema orders it (the order read from the fetched schemas, 671 elements), or removes an
element or an attribute, and leaves no element empty. The guard refuses a patch that touches
an amount, VAT, a tax or company identifier, a date or the document's number, as needing a
person's decision. `repair()` validates the patched invoice under the same profile and diffs
copies indented alike; `einvoice patch` runs it from the command line.

Findings:

- Adding an empty aggregate for the next patch to fill left `<cac:Delivery/>` behind when that
  patch was refused: harmless to the `srb` profile, refused by Peppol (`PEPPOL-EN16931-R008`).
  An `add` now names a basic component and brings the aggregates on its way; a removal takes
  the aggregates it empties.
- lxml invents a prefix (`ns0`) for an element whose namespace the document does not declare;
  such an element now declares `cac` or `cbc` itself.
- Pydantic refuses a lone surrogate before the patch's own check of the characters XML allows,
  which still catches control characters, U+FFFE and U+FFFF that lxml would raise on.
- `changed` is whether the document differs, not whether a patch applied: writing the value
  that is there already applies and changes nothing.
- A file of patches saved by Notepad (UTF-8 with a byte order mark) or redirected by Windows
  PowerShell 5.1 (UTF-16) was "Invalid JSON" at its first character; `einvoice patch` reads
  both.
- Seeding faults: twenty seeded across the grammar, the schema's order, the guard, the
  operations, the repair and the command; twenty caught.

Verification: each of the seven commits on its own green with PostgreSQL and Redis, 2 377
tests at the first and 2 532 at the last (the core's 1 728 at 100 % coverage). A repair of a
small invoice takes 11 ms warm, validation included.

Next: `feat/repair-loop-audit`: the model proposes patches for a report's violations, the
person approves them, and every step goes to the audit log.

## 2026-11-06 — `feat/repair-proposals` (5 commits)

Outcome: repairs of stored invoices (ADR-0024). `POST /invoices/{id}/repairs` takes patches from
a member or an API key, applies them to a copy of the invoice in the validator's child process,
and keeps the repair with what it did: outcomes, the diff, the report, the digests of the
document before and after. Each proposal is committed with an event in a new audit log that
holds no invoice content (migration 0010). Every request body other than an invoice is now
bounded (`SEF_MAX_BODY_BYTES`). The backlog's `feat/repair-loop-audit` is split in three: this
branch, `feat/repair-approval` and `feat/repair-model-loop`.

Findings:

- FastAPI reads a JSON body whole before validating it, so any JSON endpoint, the sign-in
  included, would hold a body of any length in memory; the new middleware reads at most 1 MiB
  and answers 413, whether or not the length was declared.
- Two requests made in one test transaction get the same `now()`, so listing repairs "latest
  first" was ordered by their random ids; the test moves the first repair back a minute, as a
  request of a minute earlier would have stored it.
- Seeding faults: thirteen seeded (values in the audit log, a proposal without its event, a
  stale proposal kept, no limit on waiting repairs, the order, the scope, the count, a repair
  found through another invoice, an unreadable invoice as a server error, the child ignoring
  patches, three in the body limit). Twelve were caught at first. The thirteenth, a declared
  length over the limit no longer refused before reading, was caught by a test added for it.

Verification: each of the five commits on its own green with PostgreSQL and Redis, 2 545
tests at the first and 2 581 at the last; the new modules of the API at 100 % coverage.

Next: `feat/repair-approval`, a person's decision on a repair, and the invoice replaced by the
document they approved.

## 2026-11-06 — `feat/repair-approval` (3 commits)

Outcome: a person decides on a repair (ADR-0024). `POST .../approval` applies the patches again
and replaces the invoice with the document they leave, only if the invoice is still the document
they were proposed for and the result is the one proposed, within the storage quota; the other
repairs that waited for the invoice are superseded. `POST .../rejection` leaves the invoice as
it is. An API key may propose but is refused a decision (403). Both decisions go to the audit
log.

Findings:

- Proposing kept the repair without checking the proposer again after the validator's work,
  which storing an invoice does: a member removed meanwhile, or a key revoked, could leave a
  repair behind. Fixed, with the two tests that the merged branch lacked.
- The first draft of approval locked the repair before the organization's storage lock, so
  approving two repairs of one invoice at once could deadlock over the repair the first one
  supersedes; the storage lock comes first now, as replacing a report takes it.
- Seeding faults: twelve seeded (a key deciding, no superseding, the result or the invoice not
  compared, the quota, a decided repair decided again, events missing or wrong, the approver
  not checked again, an empty repair approved, the scope); twelve caught.

Verification: each of the three commits on its own green with PostgreSQL and Redis, 2 583
tests at the first and 2 602 at the last; the repairs' routes and store at 100 % coverage.

Next: `feat/repair-model-loop`, the model proposing patches for a report's violations through
the same repairs.

## 2026-11-06 — `feat/repair-model-loop` (8 commits)

Outcome: the brief's layer 3 is whole (ADR-0025). `POST /invoices/{id}/repairs/suggestion` has
the language model propose patches for a stored invoice's fatal violations. The model is sent
the violations and the invoice's fields around them, by canonical path (`einvoice_core.fields`),
and nothing else of the invoice. Every answer is checked before anything is applied: a strict
schema, the patch engine's own model and path grammar, and no value the model was not given.
The validator's process applies the patches and tells the model what became of each, for two
rounds within 20 s. What is left is kept as a repair of the caller's, which a person decides on
like any other; the repair names its model, and the audit event adds the model and the rounds.

Findings:

- The API never parses an invoice it holds, so the fields come from the validator's process: a
  request to apply patches may ask for the fields around the violations that remain.
- Held to the question alone, the check of values would refuse a reason that names the standards
  (EN 16931 has five digits, UBL 2.1 a decimal). The model's prompt is part of what it was sent.
- A repair needs more tokens than an explanation, about a hundred a patch, so a question may now
  let the model write 2 048 instead of 1 024.
- A patch that fails changes nothing, so it can be dropped from a repair without changing its
  document, difference or report. Each round applies every patch kept so far to the invoice as
  stored, so that approval can apply the repair again to the document it was proposed for.
- A round that the validator's process could not apply, because it was busy, would have thrown
  away the repair an earlier round kept, after the model's work; it now leaves that repair.
- Seeding faults: thirty-seven seeded across the fields, the child's message, the repairer and
  the route. Thirty-six were caught at first. The thirty-seventh, a walk into elements of
  another namespace inside an aggregate, was caught by a test added for it.
- Without the model's answers, a suggestion for a synthetic invoice takes about 40 ms through
  the child process, with one round or two (median of eight); the rest of the 20 s is the
  model's. The live timing with Groq is the maintainer's to take (the PR's How to test).

Verification: each of the eight commits on its own green with PostgreSQL and Redis, 2 602
tests at the first and 2 681 at the last; the fields, the repairer and the repairs' store at
100 % coverage.

Next: `feat/web-bootstrap`, the Next.js application's shell: shadcn/ui, TanStack Query and
`next-intl` with Serbian (Latin) first.

## 2026-11-06 — `feat/web-bootstrap` (6 commits)

Outcome: the web application has its shell (ADR-0026). Every page is in Serbian (Latin) and in
English, with the language as the first segment of its path, and is rendered once per language
when the application is built; a path without a language goes to the one the browser asks for,
or to Serbian, and no cookie is set. A header leads home and to the page in the other language,
and a footer carries the notice that the project is not a certified validator and whether the
API answers, with its version. The components are shadcn/ui's (style `new-york`, on Radix), in
the repository; dark mode follows the operating system; the pages ask the API through TanStack
Query. The API answers CORS for the web application's origins (`SEF_WEB_ORIGINS`).

Findings:

- pnpm 12 ignores `ignoredBuiltDependencies`, and an install that meets an install script
  nobody ruled on fails. The rules moved to `allowBuilds`, with none allowed to run.
- With `next/root-params` (Next.js 16.3 and later) the root layout reads the language itself,
  and `next-intl` needs no `setRequestLocale`. Under Cache Components a catch-all route that
  renders the localized 404 needs `instant = false`, and `next dev` writes an `AGENTS.md` of
  its own into the application unless `agentRules` is `false`.
- `Intl` writes dates in Cyrillic for `sr` alone; the tag is `sr-Latn`.
- The shadcn CLI could not reach its registry from the build environment. The button and the
  badge were copied from the registry's source at the tag `shadcn@4.23.0`, as its manual
  installation describes, and `components.json` validates against the CLI's own schema. Since
  4.x the registry imports `cn` from the `cn` package, and `shadcn/tailwind.css` comes with the
  CLI, which is therefore a development dependency.
- The CLI adds a class-based `dark` variant to a stylesheet that declares none, so the media
  query is declared explicitly.
- Safari has `AbortSignal.any` only since 17.4; the client's timeout uses a controller of its
  own.
- An unexpected failure (500) leaves the API without CORS headers, because Starlette answers it
  outside every middleware: a page sees a network error. Recorded in the backlog.
- Once, a production build kept the previous stylesheet after the dependencies changed; a build
  from an empty `.next` was right, and the sequence did not happen again.
- Seeding faults: thirty-eight seeded, twenty-seven in the web application (the client, the
  retries, the status, the messages, the navigation, the home page) and eleven in the API's
  CORS and its origins. Thirty-six were caught at first. The other two, a query that does not
  pass its signal on and the tests' stub of `fetch`, were caught by tests added for them.
- End to end, with a browser against a running API: the footer gives the version; with the API
  stopped it says "API ne odgovara" after one more try, and the same when the page's origin is
  not allowed.

Verification: each of the six commits on its own, the Python suites with PostgreSQL and Redis
(2 698 tests from the first) and the web application's lint, types, tests (2 at the first, 37
at the last) and production build.

Next: `feat/web-upload-report`, stacked on this branch: upload, the report, a violation's
detail with its citations.

## 2026-11-06 — `feat/web-sign-in` (3 commits, stacked on `feat/web-bootstrap`)

Outcome: a visitor registers, signs in and signs out (ADR-0027). Registration creates the
account with its organization; a member of several organizations chooses one at sign-in; an
error is said in the visitor's language, with the seconds to wait after too many attempts. The
access token stays in the tab's memory, and the refresh token with whose it is in local
storage, so that a reload or another tab stays signed in. The tabs take turns to refresh with
the Web Locks API, because the API's strict rotation ends a session whose spent token comes
back. The header shows who is signed in, as `GET /auth/me` confirms it, and signing out, here or
in another tab, forgets the visitor's cached answers.

Findings:

- Every endpoint of invoices needs a token, so `feat/web-upload-report` was split: sign-in first,
  and the upload and the report next, on top of it.
- With strict rotation, two tabs that refresh at the same moment would end the session. Each
  refresh runs under a lock and reads the token only once it holds it; requests of one tab share
  one refresh. Against the real API, two tabs reloaded at the same moment refreshed one after
  the other, and the session survived.
- A tab learns from the `storage` event that another signed out or that another visitor signed
  in. Which visitor a tab's access token belongs to has to be kept with it: comparing the
  session the tab last rendered missed a sign-in that had not been rendered yet.
- Next.js puts a route announcer with `role="alert"` on every page, so a browser test that looks
  for the form's error by its role finds the announcer first.
- Seeding faults: twenty-nine seeded in the session, the keys of the cache, the forgetting, the
  header, the forms and the messages of errors; all twenty-nine caught.
- End to end against the API: registration, the session kept across a reload and two tabs,
  sign-out in one tab reaching the other, a wrong password refused in Serbian, an address already
  taken in English. Local storage held no access token.

Verification: each of the three commits on its own, the web application's lint, types, tests (62
at the first, 80 at the last) and production build; the Python suites (2 698 tests) at the last.

Next: `feat/web-upload-report`, stacked on this branch: upload an invoice, read its report, and a
violation's detail with its explanation and citations.

## 2026-11-06 — `feat/web-upload-report` (4 commits, stacked on `feat/web-sign-in`)

Outcome: a signed-in visitor sends an invoice, reads the validator's report on it, and finds it
again in the organization's list (ADR-0028). The invoices' page sends the XML under the profile
chosen and opens the report. The report shows what the validator read, the verdict, every rule
the invoice fails, the errors first, with each place, and what each layer did; the list shows
the newest invoices first, twenty at a time. The web application takes the API's answers from
the API's own OpenAPI document, which the repository now keeps and tests hold to the API's code,
and the types are generated from it.

Findings:

- The OpenAPI document depended on the machine: the export read the environment and `.env`, and
  `LLM_PROVIDER=groq` without a key stopped it. It builds the API with settings of its own now,
  and a test changes the environment and expects the same document.
- A page whose address the build cannot know, in an application built ahead: with
  `cacheComponents`, the build refused to read the id outside `<Suspense>`, and refused the
  header's language switcher, which reads the path, on that page. The id is awaited inside a
  boundary and streamed into a prerendered shell; the browser fetches the report.
- Chromium writes `14.400 RSD` where Node writes `14.400,00 RSD`: their data give the dinar 0
  and 2 decimals. Amounts are formatted from the API's decimal string, with every decimal it
  has and at least two, and never pass through a floating-point number.
- A file input marked `required` left the form's data empty under jsdom, and browsers check it
  differently; the form reads the input's files and says itself when none was chosen.
- The two generated files, 7 500 lines, are marked `linguist-generated`, so that the pull
  request's diff is the hand-written one; the document can still be expanded to review the
  contract.
- Seeding faults: forty-seven seeded in the web application (amounts and dates, the rules, the
  requests, the upload, the list, the report, who sees the invoices, the generated types) and six
  in the export. Twenty-nine of the web application's were caught at first; the other eighteen
  found gaps, which tests now close: a day and a moment written from west of Greenwich (Belgrade
  and CI's UTC both hid the wrong zone), a minute for an upload, the list asked for again, an
  empty file, one upload at a time, the keys of a visitor's invoices, an id kept to one segment of
  the path, a rule's errors apart from its warnings, an address that is no invoice's, what the
  report could not place, left out or did not run, and nothing shown before the session is known.
  All fifty-three are caught now.
- What the pages show comes from an uploaded document, the rules' messages included, which quote
  it. It is rendered as text; a lint rule (`react/no-danger`) now forbids setting HTML from
  data, and a test renders a seller whose name is markup.
- End to end against the API: a valid synthetic invoice ("Nema grešaka, nema upozorenja"), a
  mutation that fails `SRB-001`, the report after a reload and in English, the list with its
  amounts, and a text file kept as an unreadable document.

Verification: each of the four commits on its own, the web application's lint, types, tests (81 at
the first, 117 at the last) and production build; the Python suites (2 702 tests) at the first and
the last.

Next: `feat/web-explanations`, stacked on this branch: each violation's explanation, in Serbian
or English, with its dated citations, on the report's page.

## 2026-11-06 — `feat/web-explanations` (5 commits, stacked on `feat/web-upload-report`)

Outcome: on an invoice's report, the visitor may ask for the rules to be explained, in the page's
language; each rule's card then shows the explanation, what to change, and the passages cited,
dated and linked to their sources (ADR-0029). The API gains
`POST /invoices/{invoice_id}/explanations`, which explains the stored report without validating
the invoice again and counts as one request to the language model.

Findings:

- The page has a stored invoice's id and report, not its document; reusing
  `POST /invoices/explain` would have carried the document through the browser and back and
  validated it again, possibly into another report than the one on the page. A route of its
  own explains the stored report with the same `explain_report()`. Counting took a refactor,
  in a commit of its own, so that a request can ask the model without being a validation.
- The tests' cache treated every answer as stale where the pages keep one fresh for a minute,
  so a test that a page did not ask again passed only because it looked before the page had
  asked. The cache has the pages' defaults now, and such tests wait a moment.
- A Serbian date ends with a period of its own (`5. 11. 2026.`); a message that put one after it
  wrote two. The message now names the day mid-sentence.
- The check in a browser served the API with a stand-in for the language model, from a script of
  its own. The validator's processes import the main module again, so a script that starts the API
  with the process validator serves only under `if __name__ == "__main__"`; without it, each
  process tried to serve too.
- Seeding faults: forty-four, thirteen in the API (the route, what it counts, the refactor of
  counting) and thirty-one in the web application (the request, the query's key and its policy,
  the panel, the citations). Eight were missed at first, and tests now catch them: the most rules
  one request explains and the time the model is given (whose test checks the embedder too), a key
  for each language under the invoice's, the query never asking again by itself, and a heading in
  Cyrillic. All are caught now.
- In a browser against the API, with a stand-in for the language model: nothing asked before the
  button, SRB-009 explained with Article 2 of the PIB rulebook and BT-31 of SRB-CIUS, once in
  Serbian and once in English, the same explanations after going to the list and back without a
  new request, and a server without a model saying so.

Verification: each of the five commits on its own: ruff, mypy and the Python suites (2 702 tests
at the refactor, 2 713 from the route on), and the web application's lint, types, tests (117 up to
the explanations, 136 with them) and production build.

Next: `feat/web-diff-approve`, stacked on this branch: a repair's proposals as a diff of the
invoice, approved or rejected one by one, and the report of the repaired copy.

## 2026-11-07 — `feat/web-repairs` (5 commits) and `fix/web-header-phone` (1 commit), both on `main`

Outcome: the report's page lists a stored invoice's repairs, and each repair has a page of its
own: who proposed it and who decided on it, what became of each patch and why, the difference
it makes to the invoice as the API keeps it, and the validator's report on the copy it leaves
(ADR-0030). A separate fix makes the signed-in header fit a phone, its languages in the footer
below 640 px, and keeps their place while their links stream in. Both branches start from
`main` and merge in either order.

Findings:

- The API diffs the invoice indented anew, two spaces a level, so its hunks' numbers are lines
  of that copy, not of the file sent nor of the report: SRB-001's type code is line 16 of the
  file and line 7 of the diff. The first draft showed the numbers; reading how the core writes
  the diff, for the parser's commit, showed what they count, and the report and the repair's
  page side by side confirmed it. The parser now drops them and marks a gap where unchanged
  lines are left out.
- A patch the guard keeps for a person carries the guard's reason as its problem ("it touches a
  tax identifier (cac:PartyTaxScheme): a person decides it"); the tests' repair had none. The
  fixtures now word the problems as the validator does.
- "Predložio vi." does not agree in Serbian. Who proposed and who decided are now facts under
  the heading, as the report's seller and buyer are, which reads as a label and its value.
- The box that scrolls a wide line is a named group, not a region: the section around it is
  the landmark, and two landmarks of one name would be noise.
- Checking in a browser: Next.js keeps the page just left in the DOM, hidden (React's
  `Activity`), so a CSS locator found two headers; and React reveals the streamed language links
  a moment after the rest of a page rendered when it is asked for, so a picture taken at once
  had none.
- At 390 px the signed-in header did not fit: the name broke over two lines and the account's
  button stood past the edge (by up to 51 px at 360 px in English). Measured, smaller did not
  fit; the languages moved to the footer below 640 px. That fix is a branch of its own from
  `main`, which touches other lines of the changelog, the backlog and the interview index, so
  that the two merge cleanly in either order.
- Seeding faults: sixty-three in the repairs (the parser, the diff's view, the page, the
  history, the keys, the API's paths). Nine were missed at first, and tests now catch them: an
  id the API refuses (422), the guard's note where no patch waits, "nothing" before an added
  value and after a removed one, the history's counts (every row had 1, 1 and 1), and the three
  keys under the invoice's. Eight in the header fix, all caught. All are caught now.
- Process: PR #45 had been merged into `feat/web-sign-in` instead of `main`, because the handoff
  gave a stacked branch's base, which a merge does not change. PR #47 brought everything to
  `main`; from now on a handoff gives `--base main` once the branch below is merged.

Verification: each commit on its own, with the web application's lint, types, tests (136 at the
refactor, 141 with the parser, 153 with the repair's page, 158 with the list; 138 for the header
fix) and production build, and the Python suites at the tip, which the branches do not touch.

Next: `feat/web-repair-suggestion`: ask the language model for a repair from the report's page,
and open the repair it writes.

## 2026-11-07 — `feat/web-repair-suggestion` (3 commits, stacked on `feat/web-repairs`)

Outcome: the report of an invalid invoice offers a repair written by the language model; the
page says first what the model is sent, asks nothing until the visitor asks, and opens the repair
it writes, its reasons in the page's language. Every 409 of the repairs names its reason beside
the English detail, so that the page, and any other client, tells the refusals apart
(ADR-0031).

Findings:

- Three refusals of a suggestion share 409: a valid invoice, too many repairs waiting, an invoice
  changed meanwhile. Only the last is worth asking again, and the body said which in prose. The
  reason is now part of the contract, for all four routes, raised as one `ConflictError` and
  answered by one handler, as the login answers its 409 with the organizations to choose from.
- A suggestion creates a repair, so the page asks with a mutation, not a query: a query may run
  again by itself, and each run would create another. The answer goes into the cache under the
  repair's key, and the navigation runs only while the report is still on screen.
- A server without a model and one without a validator both answer 503 without `Retry-After`;
  the page names both rather than guess.
- Every test that renders the report now needs a router, since the report may navigate to the
  repair it asked for.
- Checking in a browser, with a stand-in model that patches the type code of every invoice: on
  SRB-009's mutation, whose type code is already 380, the repairer kept a repair whose only patch
  rewrote 380 with 380. It changes nothing and waits for a decision that cannot approve it; the
  backlog has the repairer drop such patches. The stand-in then answered no patch for other
  rules, and the page showed the 422 with a new try.
- Seeding faults: thirty-seven, twelve in the API (each conflict's reason, the handler and its
  body, the OpenAPI document) and twenty-five in the web application (the request, reading the
  reason, the XML check, the panel, where it is offered). All were caught the first time.

Verification: each commit on its own, with ruff, mypy and the Python suites, and the web
application's lint, types, tests (158 at the API's commit, 178 from the suggestion on) and
production build.

Next: `feat/web-diff-approve`: approve or reject a repair on its page, in person, and read the
invoice, its report and its repairs again.

## 2026-11-07 — `feat/web-diff-approve` (2 commits, stacked on `feat/web-repair-suggestion`)

Outcome: a person approves or rejects a repair on its page. An approval says what it does and
asks a second time; a rejection takes one press; a repair that changes nothing offers only its
rejection. Afterwards the invoice, its report, its repairs and the list's verdicts are read
again when shown, and when the page cannot know whether the decision was recorded it reads the
repair again rather than send it twice (ADR-0032). With this branch the web half of M3's repair
loop is done: upload, report, explanation, suggestion, diff, decision.

Findings:

- A timeout, a dropped connection or a 500, 502 or 504 may come after the API recorded the
  approval. Saying "try again" would have the person send it twice and see a 409 for a decision
  that went through; the page reads the repair and shows where it stands instead.
- Writing the answer into the cache must follow the invalidation of the invoice's key, which
  holds the repair too; the other way round, the repair just answered is marked stale, and read
  again as soon as the window regains focus.
- The second press for an approval moves the keyboard's focus with it: the button pressed goes
  away with the question, and focus would otherwise fall to the page's start.
- In a browser against the API: the approval after the second press, the report valid
  afterwards and its other repair superseded, the list's verdict changed, a rejection leaving
  the invoice as it was, and a repair that changes nothing offering only its rejection.
- Seeding faults: thirty-one, in the request, the panel, the cache and the messages. One was
  missed at first: nothing said what was under way while the decision was being made. A test
  catches it now, and all thirty-one are caught.

Verification: each commit on its own, with the web application's lint, types, tests (200) and
production build; the branch changes no Python, whose suites pass on the branch below.

Next: `chore/infra-deploy`, the public demo; then the Playwright smoke test of the golden path
and the release of v0.3.0.

## 2026-11-07 — `test/web-golden-path` (4 commits, stacked on `feat/web-diff-approve`)

Outcome: the brief's one Playwright smoke test (ADR-0033). A browser walks the golden path in
Chromium, in Serbian: a person registers, uploads an invoice whose type code SEF does not
accept, reads its report, again after a reload, finds it invalid in the list, has the language
model suggest a repair, reads its diff, approves it with the second press, and finds the invoice
valid on its report and in the list, with no error in the console. It runs against the web application's production build
and the API as it runs, which `scripts/serve_e2e_api.py` starts on a database made anew for each
run, with a scripted model that repairs SRB-001 and nothing else, so that no key is needed. A CI
job runs it on every pull request and keeps the report and the trace of a failure.

Findings:

- `Settings.model_validate` reads the environment and `.env` as the constructor does, so the
  API's test applications are not independent of a developer's `.env`, as `settings_for` says
  they are. The launcher builds its settings from the values it gives alone, as
  `scripts/export_openapi.py` does; the test suite's fix is in the backlog.
- The footer's API status is a `role="status"` too, so the test reads the decision's status
  within the repair's article; and a role's name matches as a substring unless it is exact, so
  "Odobri" is pressed by its exact name, beside "Da, odobri".
- The commit-msg hook refuses a `fixup!` subject (`--strict`): a change to an unhanded commit
  below the tip is tidied with `git reset --soft` and the commits made again.
- The API is ready in about 4 s, even with the compiled stylesheets of the rule sets removed, as
  in CI; the test itself takes about 2 s, and with the build and both servers about 15 s.
- Seeding faults: twenty-six at first, one at a time, in the API's CORS, the build's address of
  the API, the session, the upload, the registration, the report's offer, the opening of the
  repair, the diff, the decision, the cache after an approval, the approval's commit, a page's
  hydration, and the launcher. One was missed: an approval that leaves the list of invoices
  marked fresh, because the upload had marked it stale and the test had not opened it since.
  The test now opens the list between the upload and the repair. With one more, a refresh that
  names its token otherwise, all twenty-seven are caught: twenty-two by the end-to-end test
  (the page that hydrates otherwise only by the console's error), and every fault of the
  launcher by its own tests.

Verification: each commit on its own, with ruff, mypy, the Python suites (2 722 tests), and the
web application's lint, types, tests (200) and production build; the end-to-end test at each
commit that has it, eight times in a row at the tip, and three times with every processor kept
busy.

Next: the two repairs the backlog holds for M3 (the repairer's patch that changes nothing, the
test applications' settings), then `chore/infra-deploy`, the public demo, prepared for the
maintainer's accounts, and the release of v0.3.0.

## 2026-11-07 — `fix/repair-patches-that-change-nothing` (1 commit, stacked on `test/web-golden-path`)

Outcome: the repairer keeps no patch that writes at its place the value already there. Such a
patch applied and changed nothing, and a suggestion of it alone was kept as a repair the page
could only offer to reject. It is now dropped as a failed patch is, so that a suggestion of
nothing else answers 422, and the model is told in its second round that the patch changed
nothing. A patch a person decides is kept as before.

Findings:

- The patch engine's outcome already said it: `before` and `after` are equal. The repairer kept
  patches by their status alone.
- Both new tests failed before the change, the repairer's and the route's (201 instead of 422).

Verification: the Python suites, with ruff and mypy; the branch changes no web code.

Next: `test/api-settings-without-the-environment`, the API's test applications built from the
values given alone; then `chore/infra-deploy`.

## 2026-11-07 — `test/api-settings-without-the-environment` (2 commits, stacked on `fix/repair-patches-that-change-nothing`)

Outcome: the API's test applications are built from the values their tests give, and from
neither the developer's environment nor `.env`. `Settings.from_values()` reads settings from
given values alone, checked as ever, and replaces the subclasses the OpenAPI exporter and the
end-to-end test's launcher each held.

Findings:

- `Settings.model_validate(values)` builds a pydantic-settings class from every source, the
  given values winning, so `settings_for` took whatever else the machine held: a `.env` with
  `LLM_PROVIDER=groq` and a key gave the test applications Groq's client.
- With such an environment (a provider and embeddings with keys, an origin, a lower limit, the
  validator's other mode), eight of the existing tests failed and the suite took twice as long;
  with the change, all 876 pass under it.

Verification: each commit on its own, with ruff, mypy and the Python suites; the branch
changes no web code.

Next: `chore/infra-deploy`, once the maintainer has said whether the web application goes to
Vercel; then the release of v0.3.0.

## 2026-11-07 — `build/api-container` (3 commits, stacked on `test/api-settings-without-the-environment`)

Outcome: the API as an image (ADR-0034), the first part of the public demo. The build installs
the lock file's dependencies of the API alone, checks the rule sets against their pins (fetching
them when it is given none), compiles every profile's stylesheets and copies the corpus in; a
container applies the migrations and then serves on `PORT`, as a user that owns no file. A CI
job builds the image, starts it on an empty database and validates an invoice through it.

Findings:

- The free instance the demo will run on has 512 MB. Started with `--memory 512m --cpus 0.1`,
  the image was ready in about 40 s on an empty database and 35 s on a migrated one, validated a
  typical invoice in 0.1 to 0.4 s and one of 11 800 elements in about 5 s, and peaked at about
  330 MB with the validator in its child process. Compiling the stylesheets at start would add
  about 11 s to each wake; the migrations' check, a second interpreter's start, takes about 10 s.
- The build environment reaches neither Docker Hub nor GHCR, so the image was built from mirrors
  of the base images: an Ubuntu 24.04 root with Python 3.12, and the uv binary. Both bases are
  build arguments; CI builds from the official images.
- gitleaks took an example signing key in the README for a secret: the example now generates one
  (`openssl rand -hex 32`).
- Behind Render's proxy the rate limits would have counted the proxy, not the clients:
  `FORWARDED_ALLOW_IPS` names whom uvicorn trusts for `X-Forwarded-For`.

Verification: each commit on its own, with the Python suites, the web application's checks and
the end-to-end test; the image built, started on an empty and on a migrated database, its health
check healthy, and stopped cleanly by SIGTERM.

Next: `chore/infra-deploy`: the Render blueprint, the web application on Vercel, the steps for
the maintainer's accounts; then the API's waking-up state on the pages.

## 2026-11-07 — `chore/infra-deploy` (3 commits, stacked on `build/api-container`)

Outcome: the public demo's configuration and runbook (ADR-0035, `docs/DEPLOY.md`). The API runs on
Render's free plan from `render.yaml`, the image of ADR-0034 in Frankfurt, deployed from `main`
once CI has passed and only when the image changes; its database is Neon's free plan in the same
region, through the direct connection; the web application runs on Vercel's Hobby plan, with
Node.js 22 and no build for a commit that changes nothing of it. No secret is in the repository.

Findings:

- The maintainer chose Vercel over the brief's Cloudflare Pages: the report's page needs a server
  for its id, which on Cloudflare means the OpenNext adapter, whose Worker the free plan limits to
  3 MiB compressed. Vercel's Hobby plan is non-commercial, which a portfolio demo is.
- Render's free plan has no pre-deploy step, no shell and no one-off jobs: the image's start
  migrates, and the corpus is loaded from a developer's machine.
- asyncpg takes `ssl=require`, not Neon's `sslmode` and `channel_binding`, and needs the direct
  connection: the runbook says how to rewrite the URL Neon gives.
- Render's 750 free hours a month are shared by every free service of the workspace, where the
  maintainer has others.

Verification: the Blueprint's fields checked against Render's specification, `vercel.json` and
`package.json` formatted and parsed, the frozen install unchanged, every hook and the secret scan.

Next: the first deploy with the maintainer, then `feat/web-api-waking-up`; then the release of
v0.3.0.

## 2026-11-07 — `fix/api-image-fetches-rule-sets` (3 commits)

Outcome: the API's image builds from a clone of the repository. The first deploy, from Render's
Blueprint, failed at the build's fetch of the rule sets: a clone holds none, so the build fetched
them, and three of them need git, which the build's stage lacked. The stage now installs it; the
image still copies `/app` alone from there. CI's container job no longer restores the rule sets
from the cache before the build, and fails if the build would be given any untracked file under
`third_party`.

Findings:

- CI had passed on every change because its build never took the fetch: a warm cache hid the
  cold path (learning note 32).
- The web application is live on Vercel at `sef-kopilot.vercel.app`, public, built in 28 s with
  Node.js 22 from `apps/web`; previews are behind Vercel's sign-in.

Verification: the failure reproduced from a fresh clone of `main` (no git); the fixed image built
from a fresh clone whose `third_party` held the UBL schemas alone, which this environment's proxy
cannot download, so its build fetched the other three with git; it then started on an empty
database, answered `/ready` and validated the synthetic final invoice as valid. The guard passes
in a clone and fails in a workspace with fetched rule sets. Hooks and the secret scan clean.

Next: the maintainer merges; Render deploys once CI passes; the corpus is loaded; then
`feat/web-api-waking-up`.

## 2026-11-07 — `feat/web-api-waking-up` (3 commits)

Outcome: the pages wait for a sleeping API (ADR-0036). When the API has not answered the tab for
ten minutes, a request first asks `/health` until it answers, for up to two minutes, and is then
sent once, with its own timeout from there; the requests that wait share one wake-up. After
three seconds of waiting, the footer says that the API is waking up, and a notice above every
page says why and that what is sent will go once it answers.

Findings:

- The first deploy went live at 15:34 after the image's fix: `/ready` answers `ready` with the
  database (Neon) and the validator `ok`, and the web application's footer reads the API's
  version across origins. The corpus is still to be loaded, from the maintainer's machine.
- Forgetting that the API was awake after any failed request would have made a second click
  wait for a wake-up, but would also have called an API that is down "waking" after every error;
  the API is taken to be awake for ten minutes after its last answer, and no longer.
- Waiting is safe only before a request is sent: a write is never sent twice, as ADR-0032 and
  learning note 29 require.

Verification: 218 web tests (16 new: the wait, its timing, the shared wake-up, an aborted wait,
a refusal, the notice and the footer), `tsc --noEmit`, ESLint and Prettier clean, each commit on
its own with the production build and the golden path's end-to-end test; eleven seeded faults,
each caught (see the pull request); screenshots of the notice from a build whose `/health` was
held, in Serbian and English, light and dark, and on a phone.

Next: `docs/infra-first-deploy` (what the first deploy needed, in the runbook); the upload
notice; the release of v0.3.0.

## 2026-11-07 — `docs/infra-first-deploy` (3 commits, stacked on `feat/web-api-waking-up`)

Outcome: what the first deploy needed is in the runbook, in the steps where it was met, and the
README links the live demo, <https://sef-kopilot.vercel.app>.

Findings:

- Vercel's and Render's GitHub apps had access to some of the maintainer's repositories only;
  GitHub asked for a code by e-mail before either could be given this one, which only the
  maintainer could enter. Connecting Render to GitHub opens GitHub's own window, which the
  maintainer opened and authorised too.
- Neon's Connect dialog offered the pooled host. The runbook now says how to tell it apart, and
  rewrites the URL in three edits.
- The corpus's step typed the database's URL into the command, where the shell's history and a
  screenshot keep it; it is now read with `Read-Host -AsSecureString`.
- The new Vercel project's default Node.js was 26; `engines.node` (22.x) decides, and the
  project's setting says 22.x as well. Its production domain is public under the team's default
  protection, checked from outside.

Verification: every hook on the changed files, the secret scan; the runbook's steps checked
against what was done on 2026-11-07.

Next: the upload notice; the release of v0.3.0.

## 2026-11-07 — `feat/web-demo-upload-notice` (5 commits, stacked on `docs/infra-first-deploy`)

Outcome: the public demo asks for synthetic invoices only (ADR-0037). `SEF_PUBLIC_DEMO`, false by
default and set in `render.yaml`, makes `GET /health` report `public_demo`; the upload reads the
footer's answer and, on the demo, says that what is uploaded is stored there and that
explanations and repairs send the rules' messages and the invoice's fields to the model's
provider, with a link to the repository's synthetic invoices.

Findings:

- The fact belongs to the API, which stores the invoice and calls the model: a variable of the
  web application's build would have been a dashboard setting outside the repository, and wrong
  for any other client of the demo's API.
- Reading the health answer with the query disabled keeps the upload's requests as they were:
  the existing tests that count them did not change.

Verification: the API's 973 tests, ruff, mypy; the OpenAPI document and the web application's
types regenerated, and their test in step; 221 web tests (3 new), `tsc --noEmit`, ESLint and
Prettier clean; seeded faults caught (see the pull request); screenshots of the note from a
production build whose API answered as the demo, in Serbian and English, light and dark, and on a
phone.

Next: the release of v0.3.0.

## 2026-11-07 — `fix/api-unexpected-errors-readable` (2 commits, stacked on `feat/web-demo-upload-notice`)

Outcome: an unexpected failure answers a 500 that a page can read. A middleware inside every
other one answers an exception that no handler took with a JSON 500, which the charset and CORS
middlewares then dress like any other answer, and raises it again for the server's log; an
answer that had begun is not replaced.

Findings:

- Starlette gives a handler of `Exception` to its outermost layer, so registering one would not
  have helped: where the answer is made decides what it carries (learning note 34).
- The web application's error messages already said "failed" for a 500 it could read; until now
  it never could, and said that the API does not answer.

Verification: four tests (the readable 500, the exception still raised, an answer that had begun,
a 404 as before), each fault seeded against them caught: no middleware, one that swallows the
exception, one that replaces an answer that had begun, one outside the CORS middleware; the API's
suites, ruff, mypy.

Next: the release of v0.3.0, with what remains of M3 decided by the maintainer: retention, and
explanations kept with a stored invoice's report.

## 2026-11-07 — `chore/release-0.3.0` (2 commits, stacked on `fix/api-unexpected-errors-readable`)

Outcome: release preparation for milestone M3. Every package moves from 0.2.0 to 0.3.0; the
changelog's Unreleased section becomes `[0.3.0] - 2026-11-07`, opened by a summary of the
milestone, with a link that compares it with 0.2.0; the README's roadmap marks M3 done and M4
next, and the architecture's status follows. After the merge, the maintainer tags `v0.3.0` on
the merge commit and publishes the release notes.

Findings:

- The maintainer chose to release now, and to move retention and the explanations kept with a
  stored invoice's report to M4, as its first items: the milestone's goal is met and live, and
  neither shows on the demo.
- The OpenAPI document names the API's version, so the bump regenerates it.

Verification: `einvoice --version` says 0.3.0; the versions match the packages' metadata (their
tests); the lock file checked; every hook and the secret scan.

Next: M4, beginning with retention.

## 2026-11-07 — `feat/api-job-retention` (2 commits, stacked on `chore/release-0.3.0`)

Outcome: the first item of M4. A finished job is deleted 30 days after it ends
(`SEF_JOB_RETENTION_DAYS`, ADR-0038), with its parameters, progress and result or error; a job
under way never is, since the deletion asks for an end it does not have. The deletion runs where
the jobs run: the API's process with `SEF_JOBS=inline`, at its start and every six hours; each
worker with `SEF_JOBS=arq`, at its start and every day at 03:17.

Findings:

- On the free plan the process starts many times a day, so its start alone keeps the table near
  the period; the six-hour loop is for a process that runs for weeks.
- `create_app` reached the linter's limit of statements: the deletion's task lives in a context
  manager of its own, entered on an exit stack in the lifespan.

Verification: the API's tests, the worker's with Redis among them; seven seeded faults, each
caught (see the pull request); ruff, mypy.

Next: the retention of stored invoices, with the page where an owner sets it.

## 2026-11-07 — `feat/api-invoice-retention` (4 commits, stacked on `feat/api-job-retention`)

Outcome: the second item of M4. An organization keeps its stored invoices until it sets a
retention period, none by default (ADR-0039). An owner sets it with `PATCH /organization`, from
1 to 3 650 days, or removes it with `null`; every member sees it with `GET /organization`. A
change is checked again under the organization's lock and recorded in the audit log with what
the period was. One statement deletes, for every organization, the invoices past their period,
in the processes that delete old jobs, which moved into one module first.

Findings:

- The law keeps e-invoices in SEF, or with an intermediary engaged to keep them (Article 15 of
  the Law on Electronic Invoicing, in the corpus); what SEF Kopilot stores are working copies,
  which is what lets an organization delete them.
- Written as `created_at + period < now`, the deletion read every invoice of an organization;
  with the time of storing alone on one side, the existing index finds the old ones (the plans
  compared on 200 000 invoices).
- Undoing migration 0012 has to delete the audit events of the new action before the audit
  log's list of actions can shrink again; a test undoes it with such an event in place.

Verification: the API's tests, the migrations' and the worker's among them; the seeded faults,
each caught (see the pull request); ruff, mypy; the OpenAPI document and the web application's
types regenerated.

Next: the page of the organization's settings, where an owner sets the period.

## 2026-11-07 — `feat/web-organization-settings` (3 commits, stacked on `feat/api-invoice-retention`)

Outcome: the page where an owner sets the retention period of ADR-0039. `/organization`, linked
from the header, shows every member the organization's name, their account, the role the API
reports and how long invoices are kept. The owner chooses a period from a month to ten years,
or none; a choice that deletes invoices is saved only after a second press that names the day
up to which stored invoices go.

Findings:

- The phone's header had no room for another word: the way to the organization is an icon
  there, with the word kept for screen readers. The icon still took the header past 320 px, so
  its gaps and the account's buttons narrow on a phone; at 320 px in English the last button
  ends 16 px from the edge rather than 24, and nothing scrolls.
- A form that remounted when the period changed lost the outcome of its own save; the card
  holds the change, so its outcome outlives the form, a refusal included.
- The page's guard that a choice is a period hid a fault in the rule that says which changes
  delete; the rule has tests of its own.

Verification: the web application's tests, lint, types and build; the seeded faults, each
caught (see the pull request); screenshots in Serbian and English, light and dark, and on a
phone.

Next: the explanations of a stored invoice, kept with its report.

## 2026-11-07 — `feat/api-explanations-kept` (2 commits, stacked on `feat/web-organization-settings`)

Outcome: the third item of M4. The explanations of a stored invoice's report are kept with it,
one set a language, by the digest of the report and the day whose law they cite (ADR-0040,
migration 0013). A later request reads the kept set without asking the model or counting a
request, a server without a model included, until the invoice's report is another; `GET
/invoices/{invoice_id}/explanations` reads it alone. Only whole sets are kept.

Findings:

- The backlog planned a job; the request already has a deadline and the visitor waits either way,
  so the explanations are written in it, and the ADR records why.
- Keying by the document's digest would miss a revalidation under new rule sets, and keying by
  when the invoice was validated would discard good sets: the report's digest is what they
  explain.
- Finding the invoice now comes before counting a request to the model, so that reading a kept
  set counts nothing.
- `GET` answers 204 when none is kept, not 404: the report's page reads it as it opens, and a
  browser logs a 404 as an error. The end-to-end test, which fails on any error in the console,
  found it once the page was built on this branch.

Verification: the API's tests, the migrations' included; the seeded faults, each caught (see the
pull request); ruff, mypy; the OpenAPI document and the web application's types regenerated.

Next: the report's page shows the kept explanations at once.

## 2026-11-07 — `feat/web-explanations-kept` (2 commits, stacked on `feat/api-explanations-kept`)

Outcome: the report's page shows the explanations the API keeps (ADR-0040) as it opens, read
with `GET`, which asks the language model nothing; the offer to ask the model appears only when
none are kept. The kept and the written explanations share one cache key.

Findings:

- A read the page cancels must not be taken for "none kept", or a visitor who leaves and comes
  back would see the offer for a report whose explanations are kept; any other failure is taken
  for none, since asking reads the kept set too.
- The panel said that the model was writing while the page only read: it shows nothing until
  the read is done.
- A test's stand-in for a silent API never rejected for a signal aborted before the request;
  the test aborts once the request is sent, as a browser would.
- The API answered 404 when none was kept, and a browser logs every 404 as an error: the
  end-to-end test, which fails on any error in the console, caught it on the first report it
  opened. The API's `GET` answers 204 instead (ADR-0040), and the page reads that as none.

Verification: the web application's tests, lint, types and build, and the end-to-end test; the
seeded faults, each caught (see the pull request).

Next: the embeddings of what the rules say, kept for reuse.

## 2026-11-07 — `perf/rag-rule-embeddings-kept` (2 commits, stacked on `feat/web-explanations-kept`)

Outcome: what each rule says is embedded once an embedding model and its vector kept (ADR-0041,
migration 0014). An explanation reads the vectors kept for its model, asks the embedder only for
the texts it has not seen, once a text, and keeps the answers in the transaction that reads the
passages.

Findings:

- Writing inside the embedder's time limit would let a timeout interrupt a statement and leave
  the session's transaction to roll back: the vectors are read before and written after it.
- When the embedder fails, the rules whose vectors were kept now keep them, where before a
  failure left every rule to its words.

Verification: the API's tests, the explainer's and the migrations' included; the seeded faults,
each caught (see the pull request); ruff, mypy.

Next: the MCP server, the milestone's own work.

## 2026-11-07 — `feat/mcp-server` (3 commits, stacked on `perf/rag-rule-embeddings-kept`)

Outcome: M4's MCP server, at `/mcp` in the API's process (ADR-0042). Streamable HTTP without
sessions answers clients of the protocol's 2026-07-28 revision and earlier ones, and an API key
admits a client until the OAuth 2.1 step. The first tool, `validate_invoice`, does what
`POST /invoices/validate` does, with the same permission and the same limit.

Findings:

- The SDK configures the root logger when a server is made (`logging.basicConfig`, at INFO):
  left alone, it would have printed every library's INFO lines in production. The application
  puts the logger back; the test empties the root's handlers first, since pytest's would hide
  the change.
- The SDK's guard against DNS rebinding compares `Host` with a list of hosts, which a server
  behind the platform's proxy does not know; the endpoint checks `Origin` instead.
- Left to the SDK, a GET opens an event stream that never ends, since a server without sessions
  has no messages of its own to send: the endpoint answers 405.
- The application's lifespan holds the SDK's task group, which must be left in the task that
  entered it: the tests run the lifespan in a task of its own.
- The backlog's one item became four: the tools on stored invoices, `propose_fix` and
  `search_rules` follow, one reviewable change each, and `send_to_sef_demo` moves to M5 with
  the client it calls.

Verification: the API's tests, the MCP server's compared with the routes they stand for; the
seeded faults, each caught (see the pull request); ruff, mypy; the lock file.

Next: the MCP tools on stored invoices.

## 2026-11-07 — `feat/web-brand` (4 commits)

Outcome: at the maintainer's request, the web application has a visual identity (ADR-0043):
ink navy and one teal accent as tokens under shadcn/ui's names, in light and dark, with their
contrast measured by a test; Onest and JetBrains Mono, served with the pages; a mark of its own,
a compass bezel whose needle is a check, with the favicon and the home-screen icon; and a header
on the navy, with a member's sections beside the logo and a link past it to the content.

Findings:

- Reading the path in a client component stopped the production build: with
  `cacheComponents`, a page whose path is known only when asked for (an invoice's report)
  cannot read it while it is rendered at build time. The section links read it only once a
  member is signed in, which such a page never knows, and under `Suspense`, as the languages do.
- `next/font/local` declares no character ranges, so it could not serve the packages' files
  split by range; the packages' own CSS does.
- Every page rendered its own `main`; a link to the content needs one target on every page, so
  the root layout renders it now and the pages are its content.
- Listing the pairs to measure on the navy showed that it inherited the light theme's warning
  and error colours, which read there at 3.4:1 and 3.2:1: the surface sets them again.

Verification: the web application's tests, the contrast of every pair of tokens in each mode
among them; ESLint, TypeScript, the build; the end-to-end test, which now checks the typeface
the pages load, the favicon and the link past the header; the seeded faults, each caught (see
the pull request).

Next: the home page as the product's page (`feat/web-landing`).

## 2026-11-07 — `feat/web-landing` (4 commits, stacked on `feat/web-brand`)

Outcome: the home page is the product's page. Its first screen, on the brand's navy, says what
the product does beside an example of a report that tells its story once as the page opens,
with its end shown without motion; below it, the course an invoice takes, the rule sets, the
HTTP API and the MCP server, and the synthetic invoices to try it on. A shared link shows the
brand's image.

Findings:

- A CSS module was compiled as global CSS, its class names unscoped: the Turbopack rule that
  runs Tailwind on every stylesheet gives it the plain type. The story's styles are in the global
  stylesheet, under a prefix; the README says so.
- The phone's page was wider than its screen: a grid's implicit column took the width of the
  example's longest line of XML. The columns are `minmax(0, 1fr)`, and a phone shows the one
  line that matters.
- A shared link's image is named by its whole address, which a page rendered at build time
  takes from Vercel or, elsewhere, from `localhost:3000`: `SITE_URL` gives it. Next.js serves
  the image of a dynamic segment at `/-/opengraph-image.png`.
- Next.js reads an image's alt text whole, final newline included: the end-of-file hook and the
  editor settings leave `*.alt.txt` alone.
- The headline broke after "e-" and the tagline after "SRB-": such names stay whole.

Verification: the web application's tests, ESLint, TypeScript, the build; the end-to-end test,
which now fetches the image a shared link shows; the seeded faults, each caught (see the pull
request); screenshots in light and dark, on a desktop and a phone.

Next: the application's pages in the brand's look (`feat/web-app-restyle`).

## 2026-11-07 — `feat/web-app-restyle` (4 commits, stacked on `feat/web-landing`)

Outcome: the application's pages wear the brand. States are their colour on a tint of it; a
report and a repair open with a summary under the way back, and the validator's layers are a
checklist beside the rules; the upload's field and the list of invoices are drawn as the
page's, with an empty state; signing in and registering stand beside the navy; the 404 shows
the mark off its course.

Findings:

- The token test, given the states' tints, failed all six light pairs (4.0:1 to 4.45:1): the
  light theme's error, warning and success colours are a step deeper, and the learning note on
  colour says how a tint is mixed.
- The way back to the list was at a report's foot; it is above the summary, and once only.

Verification: the web application's tests, ESLint, TypeScript, the build; the end-to-end test;
the seeded faults, each caught (see the pull request); screenshots of every page in light and
dark.

Next: a short film of the golden path, then M4's OAuth 2.1 steps, rebased on these.

## 2026-11-07 — `feat/mcp-explain-errors` (3 commits, stacked on `feat/web-app-restyle`)

Outcome: the MCP server's second tool, `explain_errors`, does what `POST /invoices/explain`
does: the report, and an explanation of each rule it names with the passages it cites, in
Serbian or English, counted as a validation and a request to the language model, storing
nothing. A refactor first gives the tools one way to validate the invoice they are given.

Findings:

- The tool's description tells the client's model to quote the server's citations rather than
  add law of its own: the guardrail of ADR-0021 holds on the server, and the client's prose is
  the client's.
- A server without a model refuses before counting anything, as the route does, so a refusal
  spends none of the caller's validations (tested).
- The explanations kept with a stored invoice (ADR-0040) wait for the tools on stored invoices;
  this tool explains the document it is given.
- OAuth 2.1 moves ahead of the remaining tools: the assistants that sign in their users, the
  milestone's demo among them, connect only with it.

Verification: the API's tests, the tool's answer compared with the route's in both languages;
the seeded faults, each caught (see the pull request); ruff, mypy.

Next: OAuth 2.1 for the MCP server.

## 2026-11-07 — `feat/mcp-oauth-clients` (4 commits, stacked on `feat/mcp-explain-errors`)

Outcome: the first step of the MCP endpoint's OAuth 2.1 authorization server (ADR-0044), which
answers once `SEF_PUBLIC_URL` names the API's address. MCP clients register themselves with
`POST /oauth/register` (RFC 7591, migration 0015), always as public clients, with the redirect
URIs OAuth 2.1 allows, counted by address. Two preparations come first: a test that every
variable the settings read is listed in `.env.example`, and the application's routers
included from one list.

Findings:

- Neither Authlib (synchronous, Flask and Django) nor the MCP SDK's authorization server fits:
  the SDK's registration mints a secret and compares the stored one, so secrets would be kept
  in clear, and neither has client ID metadata documents or the issuer in the authorization
  response. The server is the API's own, for public clients only; the ADR records the
  departure from the brief.
- The protocol's 2026-07-28 revision prefers client ID metadata documents and keeps dynamic
  registration for compatibility; clients still use it, so it comes first, and the documents
  come last.
- `create_app` had one statement too many for the linter once the authorization server's
  routes joined; the routers became one list, in a commit of its own.
- The pre-commit hook's type check reads files not yet added, so a commit of part of the work
  was made with the rest set aside.
- The settings say their variables are the ones in `.env.example`, and nothing checked it;
  `SEF_PUBLIC_URL` was missing from it until a test compared the two.

Verification: the API's tests, registration's against the RFC's requirements; the seeded
faults, each caught (see the pull request); ruff, mypy; the OpenAPI document and the web
application's types regenerated.

Next: the authorization endpoint and the request a person decides on.

## 2026-11-07 — `feat/mcp-oauth-authorization` (2 commits, stacked on `feat/mcp-oauth-clients`)

Outcome: the second step of OAuth 2.1 for the MCP endpoint (ADR-0044). `GET /oauth/authorize`
checks what a client asks before anyone is asked: PKCE with S256, a registered redirect URI, the
MCP endpoint as the resource, known scopes. A request that will do waits ten minutes on the web
application's page (`SEF_WEB_URL`) for a signed-in person, who approves it, for the scopes their
role grants, or refuses it (migration 0016). An approval issues a code valid for two minutes,
kept as its SHA-256, and is recorded in the audit log; every answer to the client names the
issuer (RFC 9207).

Findings:

- An unknown client or redirect URI is answered where it asked, never redirected: otherwise the
  endpoint is an open redirector with the server's name on it.
- A decision is one conditional update, on a request still undecided and unexpired, so two
  people deciding at once cannot both win, and an approval after a refusal issues nothing.
- The audit log's list of actions is a check constraint, so a new action is a migration, whose
  downgrade forgets the events it no longer has a place for, as 0012's does.

Verification: the API's tests, the authorization's against OAuth 2.1 §4.1, RFC 8707 and RFC
9207; the seeded faults, each caught (see the pull request); ruff, mypy; the OpenAPI document
and the web application's types regenerated.

Next: the web application's page where a person decides.

## 2026-11-07 — `feat/web-oauth-consent` (5 commits, stacked on `feat/mcp-oauth-authorization`)

Outcome: the web application's page where a person decides on an MCP client's request,
`/oauth/consent?request=…`: what the client asks, the name it gave itself marked as unchecked,
the host it takes them back to (an application on their own computer said as such), and the
organization and account it will work in; Allow or Deny takes them back to the client with its
answer. A visitor who is not signed in signs in on the page and stays. Before it: no page of the
application may be framed by another site (RFC 9700 §4.16), the end-to-end test's API is its own
authorization server, and the language links keep the address's query. The golden path ends
with a client registering, the person allowing it, and the client's code, state and issuer.

Findings:

- The language links dropped the query, so switching language on the consent page would have
  lost the request. `useSearchParams` would have taken the links out of every page built ahead
  of time; the query is read in the browser instead, empty on the server.
- A preview whose server still held an older build sent a registration as the browser's own GET
  of the form, with the password in the address. Any visitor who submits before the script has
  loaded would do the same; `fix/web-credentials-post` is in the backlog.
- Running every commit's suite again caught a test the registration commit of
  `feat/mcp-oauth-clients` had left behind, the limits by default; the commit now counts the
  clients' registrations there too, before the stack is handed off.

Verification: the web application's tests, the consent page's in both languages, signed in and
not, with each answer the API may give; the end-to-end test with the new step; the seeded
faults, each caught (see the pull request); each commit checked on its own.

Next: `fix/web-credentials-post`, then the token endpoint and the metadata documents
(`feat/mcp-oauth-tokens`).

## 2026-11-07 — `fix/web-credentials-post` (2 commits, stacked on `feat/web-oauth-consent`)

Outcome: a password never goes into a page's address. The sign-in and registration forms are
sent by the page's script only: their button waits until it has taken over (`useHydrated()`),
and the forms are posted, so that one sent anyway carries its password in the body.

Findings:

- The pages are built ahead of time, so their forms work before React attaches its handlers; a
  form without a method is then the browser's own GET. A preview whose server held an older
  build showed it: its script never loaded, and the registration's password was in the address.
- A POST to a page built ahead of time is answered with the page (checked against
  `next start`): posting the forms needs no route of its own.

Verification: the web application's tests, the forms' markup as the server sends it among them;
the seeded faults, each caught (see the pull request); the end-to-end test; each commit checked
on its own.

Next: the token endpoint and the metadata documents (`feat/mcp-oauth-tokens`).

## 2026-11-08 — `feat/mcp-oauth-tokens` (4 commits, stacked on `fix/web-credentials-post`)

Outcome: the token endpoint of the MCP endpoint's authorization server (ADR-0044),
`POST /oauth/token`. A consent's code is exchanged once, with the PKCE verifier that began the
authorization, for an access token for the MCP endpoint alone, a JWT whose audience is the
endpoint, signed with a key derived for these tokens; a client that registered the
`refresh_token` grant also gets a refresh token, spent once for the next pair. A code or a
refresh token presented again revokes the consent; the role is read again at each exchange
(migration 0017). A fix first: the authorization endpoint answered a resource that is no URI
with a 500, and repeated unknown scopes back.

Findings:

- The step had the review of its own ADR-0044 asked for, by a reader who had not written it.
  It found the registered grant types ignored (a client that asked for codes only got refresh
  tokens), no test of two exchanges or two refreshes at once (with the row locks removed, every
  test still passed), a resource that is no URI answered 500, a duplicate parameter slipping
  through when one was empty, and errors that repeated what the client sent. Each is fixed and
  tested; the race tests run on committing sessions, where the locks do the work.
- The redirect URI follows OAuth 2.1: optional at the exchange, since PKCE binds the code, and
  the one the code was sent to when given; the first draft's rule, keyed to the number of
  registered URIs, refused a client that OAuth 2.1 allows.
- Revoking a consent stops its refresh tokens at once; its access tokens stop when the MCP
  endpoint reads the consent on every request, which is the next step's.

Verification: the API's tests, the token endpoint's against OAuth 2.1 §4.1.3 and §4.3, RFC 7636,
RFC 8707 and RFC 9068, and two races on committing sessions; the seeded faults, each caught (see
the pull request); ruff, mypy; the OpenAPI document and the web application's types
regenerated; each commit checked on its own.

Next: the MCP endpoint accepting these tokens, and the metadata documents
(`feat/mcp-oauth-resource`).

## 2026-11-08 — `feat/mcp-oauth-resource` (4 commits, stacked on `feat/mcp-oauth-tokens`)

Outcome: the MCP endpoint takes the authorization server's access tokens, beside API keys. A
token is admitted when this server issued it for the endpoint and the consent behind it stands,
read on every request with the member's role; a tool needs its permission in the role and in
the token's scopes. A refusal names the endpoint's protected resource metadata and the scopes
(RFC 9728 §5.1), and the metadata documents (RFC 9728, RFC 8414) send a client to sign its
person in. `docs/DEPLOY.md` says how to turn it on in the demo and connect an assistant.

Findings:

- A signed token says who issued it, not whether its consent still stands: reading the consent
  by the token's `sid` on every request makes a revocation take effect at once, which the token
  endpoint's own review had asked of this step. The consent must also be the token's, its
  person, organization and client, in case the key ever signed one that is not.
- The guard in front of the endpoint is named for what it checks now, a credential of either
  kind, in a commit of its own before the change; the metadata documents come in one of their
  own too, so that each commit reads on its own.
- The step had a review of its own, by a reader who had not written it. It found two refusals
  without the challenge (a key that does not work, a member no longer active), an assistant
  told that its person had been deactivated, which the token endpoint withholds, and no test of
  a token naming another organization of its person's; each is fixed and tested. Its judgement
  calls are recorded in the backlog: what the first MCP tool that writes needs (a principal
  that says which credential it came with, requests counted per consent, scopes that step up),
  and clients in a browser, whose preflights the API's CORS settings refuse.
- The metadata documents are public: a page of any origin may read them with a plain GET; they
  hold nothing that is not in the API's OpenAPI document already. At the root of the well-known
  path, the protected resource's document names the MCP endpoint where RFC 9728 would name the
  origin, because MCP clients ask for a token for the resource it names.

Verification: the API's tests, the endpoint's with every kind of token and consent, the
documents' against RFC 9728 and RFC 8414; the seeded faults, each caught (see the pull
request); ruff, mypy; the OpenAPI document and the web application's types regenerated; each
commit checked on its own.

Next: turning it on in the demo and connecting Claude, then client ID metadata documents
(`feat/mcp-oauth-client-metadata`) and the tools on stored invoices.

## 2026-11-08 — `feat/web-upload-picture-or-pdf` (2 commits, stacked on `feat/mcp-oauth-resource`)

Outcome: a picture or a PDF chosen on the upload page is not sent; the page says that SEF
Kopilot checks the e-invoice itself, the XML that is sent to SEF, and where to get it. Asked for
after the maintainer tried a picture of an invoice on the demo.

Findings:

- The file picker's filter only suggests: a person may choose any file. Sent as XML, a picture
  would have been stored only to be reported as not well-formed, and on the public demo it might
  be a real invoice.
- Turning a PDF or a picture into an e-invoice stays a step of its own, in M7, after the
  evaluations that can measure it; the maintainer agreed, and pictures join PDFs there.

Verification: the web application's tests, lint, types and build; the seeded faults, each caught
(see the pull request); each commit checked on its own.

Next: client ID metadata documents (`feat/mcp-oauth-client-metadata`).

## 2026-11-08 — `feat/mcp-oauth-client-metadata` (3 commits, stacked on `feat/web-upload-picture-or-pdf`)

Outcome: an MCP client may be known by its metadata document, the MCP revision's preferred way
for a client to introduce itself: its `client_id` is an `https` URL, whose document the
authorization server fetches at each authorization request and reads as a registration. Only
where the operator allows it (`SEF_CLIENT_METADATA_DOCUMENTS`), as a self-hosted deployment
calls out to nothing it did not choose (ADR-0045).

Findings:

- The fetch is a request to an address a stranger chose, so it reaches only the public
  internet: every address the host resolves to is checked, and the connection goes to the
  address checked, with the host's name for TLS, so that a second resolution cannot send it
  elsewhere. No redirect is followed; time and size are bounded, and the answer is asked for
  uncompressed, which also keeps a small body from inflating.
- No cache: an authorization is rare and paced by a person, so fetching each time costs little
  and keeps the client as its document says now.
- With documents switched off, a client known by one is turned away even if its row remains
  from before, since the row would stay as its document once said.

Verification: the fetch against every kind of address, answer and document the tests could
name; the authorization of a document client, read again at each request, and one whose
document will not do; a document client through every step to a tool call; the count of
authorization requests; the seeded faults, each caught (see the pull request); ruff, mypy; the
OpenAPI document and the web application's types regenerated; each commit checked on its own.

Next: the consent page naming the host that published a client's document
(`feat/web-consent-client-host`), then clients in a browser (`feat/api-oauth-browser-clients`).

## 2026-11-08 — `feat/web-consent-client-host` (2 commits, stacked on `feat/mcp-oauth-client-metadata`)

Outcome: the page where a person decides on a client's request names, for a client known by its
metadata document, the host that published the description, beside the name the client gives
itself, which stays marked as unchecked.

Findings:

- The host is in the `client_id`, which the API sends already: the page derives it as it
  derives the host of the redirect URI, so the API needs no new field.
- A registered client has no publisher, and the page says nothing of one.

Verification: the web application's tests, lint, types and build; the seeded faults, each caught
(see the pull request); each commit checked on its own.

Next: clients in a browser (`feat/api-oauth-browser-clients`), then what the first MCP tool
that writes needs, and the tools on stored invoices.

## 2026-11-08 — `feat/api-oauth-browser-clients` (2 commits, stacked on `feat/web-consent-client-host`)

Outcome: an MCP client running in a browser, such as the MCP Inspector, may sign its person in.
The authorization server's metadata documents, registration and token endpoint answer a page of
any origin, its preflight included; the rest of the API answers the web application's origins
alone, as before.

Findings:

- None of the opened endpoints reads a cookie, so allowing every origin lends a page nothing it
  could not get by calling them from a server of its own.
- The consent's requests stay the web application's: a person decides on its own page.

Verification: the API's tests, preflights and answers for both policies and without an
authorization server; the seeded faults, each caught (see the pull request); ruff, mypy; each
commit checked on its own.

Next: what the first MCP tool that writes needs, then the tools on stored invoices.

## 2026-11-08 — `feat/mcp-client-credential` (2 commits, stacked on `feat/api-oauth-browser-clients`)

Outcome: an MCP client's acts are told apart from the person's. A caller says which credential
it came with: in person, an API key, or an MCP client under a consent. Only a person in person
decides on a repair or a client's request; work that outlasts its check reads the consent
again; the audit log names the client (migration 0018); the client's requests are counted
against its consent, apart from the person's own.

Findings:

- The checks that keep a person in charge read "no API key", which an MCP client's caller also
  has none of; no tool reached them yet, so this comes before the first tool that writes, as
  the review of `feat/mcp-oauth-resource` asked.
- The second scope's step-up and the tools listed by scope wait for that scope, with the tools
  on stored invoices.

Verification: the API's tests, the whole suite; the seeded faults, each caught (see the pull
request); the migration up and down; ruff, mypy; each commit checked on its own.

Next: the tools on stored invoices (`feat/mcp-invoice-tools`).

## 2026-11-08 — `feat/mcp-invoice-tools` (3 commits)

Outcome: an assistant keeps and reads invoices. `store_invoice`, `list_invoices` and
`get_invoice` do what their routes do, through the same services and with the same answers;
they need the new scope `invoices:submit`, which the consent page names and a client gets by
default with `invoices:validate`. No scope reaches every invoice of the organization, so an
assistant sees the invoices its person submitted.

Findings:

- The routes' presenters were private to the routes; they are named now and shared, so the
  tools cannot drift from the routes' answers.
- A client connected before this scope must connect again: a refresh never widens a consent.
- The backlog item was larger than one review: the explanations and revalidation of a stored
  invoice follow, then the step-up and the tools listed by scope.

Verification: the API's tests, the whole suite; the web application's tests, lint and types;
the seeded faults, each caught (see the pull request); ruff, mypy; each commit checked on its
own.

Next: the explanations and revalidation of a stored invoice (`feat/mcp-invoice-explanations`).

## 2026-11-08 — `feat/mcp-invoice-explanations` (3 commits, stacked on `feat/mcp-invoice-tools`)

Outcome: an assistant asks what is wrong with a stored invoice and checks the stored ones
against today's rules. `explain_invoice` answers the kept explanations first, so asking again
costs nothing; `revalidate_invoices` starts the route's job and `get_job` reads it. The logic
the routes held in their bodies is shared, so the tools cannot drift from them.

Findings:

- A revalidation's 409 names its job in `Location`, which a tool's caller cannot read; the tool
  names the job in its error instead.
- The read-only hint is about the person's data: explaining keeps what it answered and says it
  reads; revalidating replaces reports and says it writes.
- A test of the explanation's time limit (one second) failed once while the whole suite ran
  beside another; it passed on its own and in every later run.

Verification: the API's tests, the whole suite; the seeded faults, each caught (see the pull
request); ruff, mypy; each commit checked on its own.

Next: the step-up and the tools listed by scope (`feat/mcp-scope-step-up`).

## 2026-11-08 — `feat/mcp-scope-step-up` (2 commits, stacked on `feat/mcp-invoice-explanations`)

Outcome: a client the person let do less than a tool needs is asked to step up. The endpoint
reads a token holder's `tools/call` before the server runs the tool and answers 403
`insufficient_scope` with the scopes to ask for, the held ones too; a client that steps up asks
its person again on the consent page and repeats the call. Every tool stays listed (ADR-0046).

Findings:

- The backlog asked for `tools/list` filtered by the scopes; a hidden tool is never called, so
  never asked for, and the decision went the other way.
- A tool's error inside a 200 is read by the client's model, never by the client: only an HTTP
  status starts a re-authorization.

Verification: the API's tests, the whole suite; the seeded faults, each caught (see the pull
request); ruff, mypy; each commit checked on its own.

Next: `propose_fix` (`feat/mcp-propose-fix`).

## 2026-11-08 — `feat/mcp-propose-fix` (3 commits, stacked on `feat/mcp-scope-step-up`)

Outcome: an assistant proposes a fix of a stored invoice, and its person decides. `propose_fix`
has the server's model write the patches, or applies the assistant's own; either way they meet
the walls of ADR-0025 and the repair waits for a person, on the web application's page the
tool names (`decide_at`). `get_repair` reads whether they have decided. The logic of both
repair routes is shared, so the tool answers as they do.

Findings:

- No tool decides, and an assistant's access token, signed with a key of its own for the MCP
  endpoint, is refused on the routes; a test now says so for the approval.
- A signed-out person who opens `decide_at` is offered to sign in, but not brought back to the
  repair afterwards; the link works again once they are signed in.
- The repair's page says whether it came from an API key, not whether it came through an
  assistant; the audit log does name the client.

Verification: the API's tests, the whole suite; the seeded faults, each caught after a clean
baseline (see the pull request); ruff, mypy; each commit checked on its own.

Next: `search_rules` (`feat/mcp-search-rules`).

## 2026-11-08 — `feat/core-rule-catalogue` (2 commits, stacked on `feat/mcp-propose-fix`)

Outcome: the rules a profile applies, as data. `catalogue(profile)` reads the assertions of the
rule sets the validator runs, CEN's compiled XSLT and Peppol's sources, adds the arithmetic
layer's calculation rules and, for `srb`, the SRB-CIUS rules, and marks what the profile always
sets aside (ADR-0047). `search` finds rules by id, business term or words. It is the ground of
`search_rules`, split from it as a change of its own.

Findings:

- Every rule a validation of the fixtures and official examples reports, under every profile,
  is in the catalogue; a test keeps it so.
- Ordering ids by their numbers was dead weight: the published ids are padded. A seeded fault
  that no test caught showed it, and the plain order stayed.

Verification: the core's tests, coverage 100 %; the seeded faults, each caught after a clean
baseline (see the pull request); ruff, mypy; each commit checked on its own.

Next: `search_rules` over the catalogue and the corpus (`feat/mcp-search-rules`).

## 2026-11-08 — `feat/mcp-search-rules` (3 commits, stacked on `feat/core-rule-catalogue`)

Outcome: any rule can be looked up, broken or not. `GET /rules` and `search_rules` find the
rules of a profile by id, business term or words, with the passages that share the words;
`GET /rules/{rule_id}` and `get_rule` answer one rule with the passages an explanation of it
would cite on a day, found by the explainer's own retrieval.

Findings:

- The statements are English; a Serbian query finds the law in its own words, and the rules
  through it, which is why a search answers passages as well as rules.
- A rule's passages are found as those of a violation of it, so the lookup and an explanation
  cite the same law.
- The pinned test of every endpoint's guard failed for the new routes until they were pinned,
  with what another organization's owner finds there: the same rules, and no trace.

Verification: the API's tests, the whole suite; the seeded faults, each caught after a clean
baseline (see the pull request); ruff, mypy; the OpenAPI document and the web application's
types regenerated; each commit checked on its own.

Next: the demo from Claude and ChatGPT, documented with screenshots, then `v0.4.0`.

## 2026-11-08 — `feat/api-security-events` (2 commits, stacked on `feat/mcp-search-rules`)

Outcome: a deployment's log lines are JSON, each request's lines named by its id, and the
decisions about who may do what are logged as security events, without what a person wrote:
sign-ins, refused keys, reused tokens, consents and repairs decided.

Findings:

- Until now uvicorn configured its own loggers only, so the application's lines below warning
  never reached a deployment's log; the log configuration fixes that as well.
- A refused sign-in logs why and from where, not the address tried: a password typed into the
  wrong field would otherwise be logged.
- A key's use, and when each key was last used, were split off: they need a column and a page.

Verification: the API's tests, the whole suite; the seeded faults, each caught after a clean
baseline (see the pull request); ruff, mypy; each commit checked on its own.

Next: when each API key was last used (`feat/api-key-last-used`).

## 2026-11-08 — `feat/api-key-last-used` (2 commits, stacked on `feat/api-security-events`)

Outcome: a member sees when each of their keys was last used, in `GET /api-keys`, and a key's
use is a security event; both are written at most once a minute, by one conditional update
(migration 0019).

Findings:

- The web application has no page of API keys yet; the time is in the API's list, and the page
  waits for its own item.
- A request that only reads ends without a commit, so noting the use commits on its own, as
  the request's first work.

Verification: the API's tests, the whole suite; the migration up and down; the seeded faults,
each caught after a clean baseline (see the pull request); ruff, mypy; each commit checked on
its own.

Next: the demo from Claude and ChatGPT with screenshots, once the branches are merged and
deployed; then `v0.4.0`.

## 2026-11-08 — `feat/web-api-keys` (2 commits, stacked on `feat/api-key-last-used`)

Outcome: a member manages their API keys on the organization's page: what each allows and when
it was last used, a new key shown once with a copy button, and a revocation asked twice.

Findings:

- Keys could be issued only through the API, by someone who already held an access token: the
  page closes that gap for the people the keys are for, the accountants who connect an ERP.
- The API lists a key's permissions in the order of their names; the page says them in the
  form's order.

Verification: the web application's tests, lint and types; a key issued, used by a machine and
listed against a local API, in screenshots (desktop and phone); the seeded faults, each caught
after a clean baseline (see the pull request); each commit checked on its own, the end-to-end
test included.

Next: the demo from Claude and ChatGPT with screenshots, once the branches are merged and
deployed; then `v0.4.0`.

## 2026-11-08 — `feat/api-error-tracking` (2 commits)

Outcome: unexpected errors of the API and its workers are reported to Sentry where `SENTRY_DSN`
is set, with where they happened and nothing a person sent (ADR-0048). The maintainer opened
the accounts; the Sentry project `sef-kopilot-api` was created, and the organization requires
its data scrubbers and stores no IP address. The Langfuse project was named `sef-kopilot`.

Findings:

- `sentry-sdk` 2.74 deprecates `send_default_pii` for `data_collection`, a category at a time;
  every category that holds what a person sent is off.
- A test that started the SDK twice sent its reports to the network; the reports of the tests
  now go to a transport that keeps them in memory.
- `.env.example` named the variables of the observability services from the start
  (`SENTRY_DSN`, `LANGFUSE_*`); the settings read those names.
- The DSN and the Langfuse keys are entered by the maintainer: a key is never typed by the build
  environment.

Verification: the API's tests, the whole suite; the seeded faults, each caught after a clean
baseline (see the pull request); ruff, mypy, the lock file; each commit checked on its own.

Next: the model's requests traced to Langfuse, without the invoice (`feat/rag-model-traces`).

## 2026-11-08 — `feat/rag-model-traces` (2 commits, stacked on `feat/api-error-tracking`)

Outcome: each request to the language model is traced to Langfuse where both of its keys are
set, as a generation without the conversation: the schema, the model, the time, the tokens and
the outcome, the answers of one API request in one trace (ADR-0049).

Findings:

- Langfuse v4 takes spans as OpenTelemetry and asks clients to stop sending to its legacy
  ingestion endpoint; spans are sent as OTLP over HTTP in JSON, with `httpx`, and no new
  dependency.
- Groq reports the tokens of each answer; they reach the trace through a context variable, so
  the concurrent answers of one explanation never mix.

Verification: the API's tests, the whole suite; the seeded faults, each caught after a clean
baseline (see the pull request); ruff, mypy; each commit checked on its own.

Next: the maintainer enters the keys (Sentry's DSN, Langfuse's pair) on Render; then the demo
from Claude and ChatGPT, and `v0.4.0`.

## 2026-11-08 — `docs/repo-security-checklist` (1 commit, on `feat/rag-model-traces`)

Outcome: the security checklist's two items from the brief that the error reports and the
model's traces meet, left open beside the new items that said so, marked met. The commit was
made after `feat/rag-model-traces` was handed off, and that branch was merged without it, so it
went as a pull request of its own.

## 2026-11-08 — `chore/release-0.4.0` (3 commits)

Outcome: M4 released. The demo from Claude and ChatGPT, on the public demo through each
assistant's connector and OAuth, with a synthetic invoice whose PIB has a wrong check digit
(`docs/DEMO.md`); every package at 0.4.0; the changelog's section `[0.4.0] - 2026-11-08`; the
README's roadmap, the architecture's status and the backlog follow.

Findings:

- Both assistants called `explain_errors` first; Claude then read the rule with `get_rule` and
  validated again with `validate_invoice` before it answered.
- The local embedding model (BGE-M3) was left out at the maintainer's decision, with its reason
  in the backlog: keyword retrieval serves a self-hosted deployment, and the image stays small.

Verification: each commit checked on its own; the version checks unchanged and green.

Next: M5, whose first branches, the organization's SEF key and the SEF demo client, wait for
this tag.

## 2026-11-08 — `feat/sef-keys` (3 commits, stacked on `chore/release-0.4.0`)

Outcome: an owner gives the API the organization's key to SEF, which is sealed with Fernet under
`SEF_FERNET_KEY` for that organization alone and shown to no one; every member sees since when
one is set; `make rotate-sef-keys` seals every stored key again under a new secret (ADR-0050).
The first step of M5.

Findings:

- FastAPI's 422 repeats each value it refuses, and for a field missing the whole object around
  it, so a password too short came back in the answer; the API's answer now keeps the place,
  the reason and the limits, never the value.
- Fernet authenticates no data beside its message: the organization's id is sealed with the key,
  so that a token moved to another row does not open there.
- A CHECK on the column accepts a Fernet token only, so a key in the clear fails at the database.

Verification: the API's tests, the whole suite; 28 seeded faults, each caught after a clean
baseline (one first missed, the demoted owner's change in flight, then a test added); ruff,
mypy; each commit checked on its own.

Next: the SEF demo client over this key, sending an invoice and asking about its status
(`feat/sef-demo-client`).

## 2026-11-08 — `feat/sef-demo-client` (4 commits, stacked on `feat/sef-keys`)

Outcome: a stored invoice is sent to SEF's demo environment in its organization's name, only
when the validator passes it under SRB-CIUS, byte for byte as validated, and once, through the
`requestId`; what SEF answered is kept with it, and where it stands in SEF is asked where the
jobs run until SEF calls it final (ADR-0051).

Findings:

- SEF publishes its API as OpenAPI (`/swagger/public_v1/swagger.json`, read on the demo): the
  key goes in the header `ApiKey`, sales invoices are in version 1, and version 2 holds only VAT
  recording.
- The submission is committed before SEF is asked, so that an answer lost on the way leaves a
  row whose id is asked again, never a second invoice in SEF.
- Two sendings in one transaction share its `now()`; the time a submission was sent is taken
  from the clock, so that their order holds.
- The demo from Claude ran against the deployed API, through OAuth: `explain_errors`,
  `get_rule` and `validate_invoice` on a synthetic invoice with a wrong PIB check digit.

Verification: the API's tests, the whole suite; the seeded faults, each caught after a clean
baseline (see the pull request); ruff, mypy; each commit checked on its own.

Next: the MCP tool `send_to_sef_demo` with the scope `invoices:send`; the web application's
pages for the SEF key and for sending; after `v0.4.0`.

## 2026-11-09 — `feat/mcp-send-to-sef` (4 commits)

Outcome: an assistant sends a stored invoice of its person's to SEF's demo environment with
`send_to_sef_demo`, and reads where it stands with `get_sef_status`, as the routes do; sending is
the scope `invoices:send`, which a client is not told to ask for first and asks for through the
step-up when its assistant first sends; the consent page names what the person's role withholds
(ADR-0052).

Findings:

- The MCP revision's clients take the scopes to ask for from the challenge first, then from
  `scopes_supported`: listing a scope as supported and leaving it out of the challenge is how a
  server keeps it for later without a mechanism of its own.
- Every role held both scopes until now, so the consent page never had to say what approving
  does not give; `invoices:send` is the first scope a client of the office is denied.
- The application's SEF client is captured by its watching when it starts, so a test that speaks
  to a fake SEF sets it before the application starts.
- The maintainer's decisions for M6: the language model adapters are tested on recorded answers
  without a paid comparison, and billing is built and tested without a Stripe account, off in
  the public demo; the project stays free.

Verification: the API's tests, the whole suite; the web application's tests, build and
end-to-end test; the seeded faults, each caught after a clean baseline (see the pull request);
ruff, mypy, eslint, tsc; each commit checked on its own.

Next: `invoices:send` among the permissions an API key may hold, for an ERP that sends its
invoices (`feat/api-keys-send-to-sef`).

## 2026-11-09 — `feat/api-keys-send-to-sef` (4 commits, stacked on `feat/mcp-send-to-sef`)

Outcome: an API key may hold `invoices:send`, so that an ERP sends its organization's invoices
to SEF with an owner's or an accountant's key, through the route or the MCP tool; the keys page
offers it to them, unticked (ADR-0053, migration 0022).

Findings:

- The fault seeding of the branch before showed the tool's own permission check hidden behind
  the sending's check under the lock: both refuse with the same words. The test now sends an
  invoice the validator would not pass, which a late check would report as invalid instead.
- The MCP tests issued every key to the office's client, whose role granted all a key could
  hold; with sending, they issue the accountant's.
- Alembic's autogenerate does not compare CHECK constraints: a fault seeded into the model's
  list of permissions a key may hold went unseen while migration 0022 changed the table. The
  models now build a database of their own, and the checks PostgreSQL writes back for both
  compare.

Verification: the API's tests, the whole suite; the web application's tests, build and
end-to-end test; the seeded faults, each caught after a clean baseline (see the pull request);
ruff, mypy, eslint, tsc; each commit checked on its own; the migration undone and applied again.

Next: the organization's page, where an owner sets the key to SEF (`feat/web-sef-key`).

## 2026-11-09 — `feat/web-sef-key` (3 commits, stacked on `feat/api-keys-send-to-sef`)

Outcome: the organization's page shows every member since when the organization has a key to
SEF, and lets its owner set one, replace it, or remove it after a second press; the key is
typed into a password field that forgets it once saved, and one that cannot be a key is not
sent.

Findings:

- The key never reaches the query cache: the page writes the time the API answers into the
  cached organization, and empties the field.
- DEPLOY's step for the key now points at the page instead of a request by hand.
- The screenshots against a local API showed the key not saved: the browser refused PUT in the
  preflight, the first route the API answers with PUT and the first page that sends it. PUT
  joined the methods a page may send, and a test holds every method of the routes, read from
  the OpenAPI document, to them; the unit tests, which stub the API, could not see it.

Verification: the web application's tests, build and end-to-end test; the seeded faults, each
caught after a clean baseline (see the pull request); eslint, tsc; each commit checked on its
own; screenshots against a local API.

Next: the report's page, where an owner or an accountant sends a valid stored invoice to SEF
and sees what SEF answered (`feat/web-sef-send`).

## 2026-11-09 — `feat/web-sef-send` (3 commits, stacked on `feat/web-sef-key`)

Outcome: the report says where the invoice stands in SEF, read again every half a minute while
the API asks SEF, and an owner or an accountant sends a valid invoice from there, when the
organization has a key, after a second press that names the organization; a refusal is said by
its reason, and the page reads again what the reason concerns.

Findings:

- The page reads the submissions again only within the API's own window: imported, not final,
  less than thirty days old.
- Sending waits up to two minutes in the browser, as the API tries SEF three times; a lost answer
  leaves the submission the API committed before asking, which the page reads again.

Verification: the web application's tests, build and end-to-end test; the seeded faults, each
caught after a clean baseline (see the pull request); eslint, tsc; each commit checked on its
own; screenshots against a local API with a fake SEF.

Next: SEF's error codes mapped into the explanations (`feat/sef-error-mapping`), and the
release `v0.5.0`.

## 2026-11-09 — `chore/release-0.5.0` (2 commits)

Outcome: M5 released. Every package at 0.5.0; the changelog's section `[0.5.0] - 2026-11-09`,
opened by a summary of the round trip to SEF's demo; the README's roadmap, the architecture's
status, its course of an invoice and its repository map follow.

Findings:

- The client to SEF was built and tested against a stand-in that answers as SEF's OpenAPI
  document describes; signing in to the demo takes an eID and a company administrator's role.
  At the maintainer's decision the release goes without them, and the backlog moves to M7 what
  waits for an account: SEF's error codes in the explanations, SEF's technical instruction in
  the corpus, and the points the published documents leave open.

Verification: each commit checked on its own; the version checks unchanged and green.

Next: M6, the evaluation harness with golden sets and offline cassettes (`feat/evals-harness`).

## 2026-11-09 — `feat/evals-harness` (4 commits, stacked on `chore/release-0.5.0`)

Outcome: the evaluations' runner, `sef-evals`, a package of the workspace. It measures the
validator on every document of the corpus against golden labels and against the published rule
sets applied as published, judges the measures against `evals/thresholds.yaml`, and writes a
committed report that CI holds to the run (ADR-0054). Every threshold is met. The first step of
M6.

Findings:

- The first run missed two labels, not the validator: of the Ministry's examples,
  `faktura-sa-prilogom.xml` is not schema-valid, so SRB-009 never runs on it, and
  `faktura-sa-popustom.xml` has an allowance without a reason; each now has its own group.
- Under EN 16931 the validator, like the reference, reports rules inside the Serbian extension;
  the rule-level comparison leaves the extension out on both sides (ADR-0007).
- The published unit tests are fragments the schema refuses, so they stay with the Schematron
  conformance tests; the evaluations compare whole documents.
- `uv sync --frozen --package sef-kopilot-api`, as the API's image runs it, does not need the
  new member, so the image is unchanged.

Verification: the runner's tests (100 % coverage); seeded faults in the validator, each failing
the evaluations, and in the runner, each failing its tests, after a clean baseline (see the
pull request); ruff, mypy; each commit checked on its own.

Next: the model's measures, starting with the explanations and their cassettes
(`feat/evals-explanations`).

## 2026-11-09 — `feat/evals-explanations` (3 commits, stacked on `feat/evals-harness`)

Outcome: the explanations are measured as the API writes them, on a database of the
evaluations' own, with the model's answers recorded once against Groq's free tier and replayed
offline (ADR-0055). First recording: 47 of 47 rules explained, 93 of 93 citations resolved, 90
of 93 relevant; every threshold met.

Findings:

- Alembic runs its own event loop, so the runner migrates its database in a thread of its own.
- The recording first stopped before a request: Docker was not running on the maintainer's
  machine. `sef-evals` now names the server it cannot reach, without its password, and how to
  start it, instead of a traceback.
- The three citations labelled not relevant name a neighbouring field of the same table of
  SRB-CIUS (BT-129 for a unit code, BG-7 and BG-4 for a party's identifiers).

Verification: the runner's tests; the measures replayed from the cassette here are those the
recording wrote on the maintainer's machine; ruff, mypy; each commit checked on its own.

Next: the repairs' measures (`feat/evals-repairs`).

## 2026-11-09 — `feat/evals-repairs` (2 commits, stacked on `feat/evals-explanations`)

Outcome: repairs are measured on nine held-out invoices made at run time, which a repair must
leave the validator accepting (80 % at least), and on eleven whose mistake a person decides,
which no repair may make pass (none may), with the model's answers recorded once and replayed
offline (ADR-0056). The measures of the final recording are in `evals/reports/latest.md`.

Findings:

- The first recording left `repair_success` at 5 of 9: the four misses were invoice types SEF
  does not accept, for which the model proposed nothing. SRB-001 allows four codes and the
  invoice does not say which was meant, so those cases did not meet the set's own criterion;
  at the maintainer's decision they became cases a person decides, and four new held-out
  invoices took their places before the model saw them (ADR-0056 records why).
- The model did propose patches a person decides (a PIB's check digit, an amount due); the
  guard kept them as suggestions, and `overreach_rate` stayed at zero.

Verification: the runner's tests; the report replayed from the cassettes here; ruff, mypy;
each commit checked on its own.

Next: the stack above, from the providers' adapters to the evaluations' gate, rebased on these.

## 2026-11-09 — `feat/llm-openai-anthropic` (3 commits, stacked on `feat/evals-repairs`)

Outcome: OpenAI's and Anthropic's models answer through `LLMClient` beside Groq's, chosen by
`LLM_PROVIDER` with the operator's key, each asked for structured outputs and its answers checked
as Groq's; one retrying client for the three (ADR-0057). Groq's free tier stays the default.

Findings:

- Anthropic's API version `2026-10-21` refuses `temperature`, and OpenAI's reasoning models do
  too; the shared client sends it to Groq alone.
- The explanations' and repairs' schemas already keep within what Anthropic's structured outputs
  support (closed objects, string enums, no length constraints).
- The secret scan took a test's fake key for a real one; the tests now use keys that are
  plainly fake.

Verification: the API's tests, the whole suite; ruff, mypy; each commit checked on its own.
Each provider answers the tests as its API reference shows; no paid account is held, so the
adapters are not compared on the evaluations, at the maintainer's decision.

Next: the organization's own key to a provider (`feat/api-organization-model-key`).

## 2026-11-09 — `feat/api-organization-model-key` (4 commits, stacked on `feat/llm-openai-anthropic`)

Outcome: an organization's owner may set its own key to Groq, OpenAI or Anthropic, with a model
if not the provider's default; the key is sealed as the SEF key is, for that purpose alone, and
rotated with it. The organization's explanations and repairs, from the routes and from MCP, are
then written by its own model, made for the request and closed after it; a key the server
cannot open answers 503 rather than send the invoice to the server's model (ADR-0058).

Findings:

- Fernet authenticates the whole message, so the key's purpose sealed beside the organization's
  id keeps a model key from opening as a SEF key; the SEF keys sealed before read as SEF keys
  and need no new sealing.
- The server's model owned the Langfuse client; a model made for one request had to share it
  without closing it, so the traces are now the application's.
- The requests of one test share a transaction, and so the time their audit events record; the
  tests compare the events as a set.

Verification: the API's tests, the whole suite; seeded faults in the sealing, the rotation, the
permission, the choice of model and the closing of the traces, each failing a test; ruff, mypy,
tsc; each commit checked on its own.

Next: the organization page's form for the key (`feat/web-organization-model-key`).

## 2026-11-09 — `feat/web-organization-model-key` (2 commits, stacked on `feat/api-organization-model-key`)

Outcome: the organization page shows every member whose language model writes the
organization's explanations and repairs, the server's or its own provider's and model, and since
when; an owner chooses the provider (Groq, OpenAI or Anthropic), names a model if not the
provider's default, gives the key in a password field that forgets it once saved, and removes it
after a second press (ADR-0058).

Findings:

- The page already holds the key to SEF, whose buttons say "Save the key": the model's buttons
  name the model key, so that neither a person nor a test is left to guess which card a button
  belongs to.
- The page checks the key and the model's name by the API's own rules, kept beside them in
  `lib/organization.ts` and tested at the same boundaries; a 422 keeps its own message in case
  they ever drift.

Verification: the web application's tests, types, lint and build; the seeded faults, each
failing a test; each commit checked on its own; screenshots against a local API.

Next: credits and Stripe behind an interface, built and tested without an account
(`feat/billing-stripe-sandbox`), while the cassettes of the model's measures are recorded.

## 2026-11-09 — `feat/api-credits` (3 commits, stacked on `feat/web-organization-model-key`)

Outcome: where the operator turns billing on, each organization holds credits, starting with
`SEF_STARTING_CREDITS`, and storing an invoice, from the routes or from MCP, spends one or
answers 402; a balance and an append-only ledger in one transaction, never below zero;
`GET /billing` for whoever may store, the ledger for the owner, `make grant-credits` for the
operator (ADR-0059). Off by default and in the public demo. `feat/billing-stripe-sandbox` is
split: the credits here, buying them through Stripe's sandbox and the page next.

Findings:

- The entries of one transaction share their time: an identity column orders them as they
  were written.
- Spending before the invoice is added leaves nothing to undo when there is no credit, whatever
  the caller does with its session.
- `stripe-mock` is maintained (v0.206.0, October 2026), so the Stripe branch can test against
  it in CI.

Verification: the API's tests, the whole suite; seeded faults in the spend, the opening, the
check of the balance and the permissions, each failing a test; ruff, mypy; each commit checked
on its own.

Next: credits bought through Stripe's sandbox (`feat/api-stripe-checkout`).

## 2026-11-09 — `feat/api-stripe-checkout` (3 commits, stacked on `feat/api-credits`)

Outcome: an owner buys credits through Stripe Checkout, in Stripe's sandbox only, behind a
provider's interface: the packs of `SEF_CREDIT_PACKS`, `POST /billing/checkout`, and
`POST /billing/stripe-events`, whose events are read only when signed by Stripe less than five
minutes before; a paid checkout is counted once under its reference (ADR-0060). Live keys refuse
to start and live events add nothing. Built and tested without a Stripe account.

Findings:

- `stripe-mock` is maintained (v0.206.0, October 2026) and validates each request against
  Stripe's OpenAPI description: it refuses a misnamed parameter or a price that is not a
  number, which a test against a stub could not show.
- Stripe's current API version is `2026-10-28.endive`; requests pin it.
- A payment may be reported by two events (`completed`, then `async_payment_succeeded` for a
  delayed method): the unique reference counts it once either way.

Verification: the API's tests, the whole suite, with `stripe-mock` running; seeded faults in
the signature, the tolerance, the scheme, the counting once and the sandbox checks, each failing
a test; ruff, mypy; each commit checked on its own.

Next: the page that shows the credits and buys them (`feat/web-billing`).

## 2026-11-09 — `feat/web-billing` (2 commits, stacked on `feat/api-stripe-checkout`)

Outcome: the organization page shows the credits where the server counts them: the balance for
every member who stores invoices; for the owner, the latest changes and the packs on sale, each
bought on Stripe's page in its sandbox. Back from paying, the page says the payment is on its
way and reads the credits again for a minute. The upload page says when there is no credit
left. Where storing costs nothing, nothing changes.

Findings:

- The return from Stripe is read from the address with `useSyncExternalStore`: reading it in an
  effect would set state there, which the React rules refuse, and on the server there is no
  address to read.
- One reading again right after the return is not enough: Stripe tells the API a moment after it
  tells the visitor, so the page asks again every five seconds, a dozen times at most.

Verification: the web application's tests, types, lint and build; each commit checked on its
own.

Next: the evaluations as CI's gate (`ci/evals-gate`), once the repairs' cassette is recorded,
then `v0.6.0`.

## 2026-11-09 — `ci/evals-gate` (3 commits, stacked on `feat/web-billing`)

Outcome: the evaluations gate CI as a job of their own, which replays the cassettes offline and
fails on a missed threshold or a stale report; `sef-evals` writes the README's badge with the
report, and the README reads it through shields.io from the default branch (ADR-0061). The last
branch of M6 before `v0.6.0`.

Findings:

- The badge as a file of the report needs no token and cannot drift: `--check` holds it to the
  run like the rest.

Verification: the runner's tests; the workflow validated against GitHub's schema; the job's
command run here on the stack's tip, every threshold met.

Next: `v0.6.0`.

## 2026-11-09 — `chore/release-0.6.0` (2 commits, stacked on `ci/evals-gate`)

Outcome: every package moves to 0.6.0; the changelog's Unreleased section becomes 0.6.0, opened
by a summary that says which providers were not tried against real accounts and why; the
README's roadmap marks M6 done and M7 next.

Verification: the version checks; each commit checked on its own.

Next: M7, the PDF extraction beta and the SEF items that wait for a demo account.

## 2026-11-11 — `fix/evals-empty-database-url` (2 commits)

Outcome: an empty `SEF_TEST_DATABASE_URL`, as `.env.example` leaves it, is read by the
evaluations as not set, as the API's tests read it, and a value that is no database URL is
refused without being repeated. The SEF items that wait for a demo account move after `v1.0.0`,
at the maintainer's decision: the demo's sign-up takes an eID registration the project does not
have.

Findings:

- Shipping 0.6.0 on the maintainer's machine stopped on SQLAlchemy's traceback for an empty URL:
  the terminal of the first recording had named the server, the `.env` never had. The shipping
  script now names the server from the container it starts, and the runner says what is wrong.

Verification: the runner's tests, the new cases first failing; ruff, mypy.

Next: M7, PDF and picture extraction (beta).

## 2026-11-11 — `feat/api-invoice-extraction` (5 commits, stacked on `fix/evals-empty-database-url`)

Outcome: the API reads an invoice from a PDF or a picture, in two steps with a person between
them (ADR-0062). `POST /invoices/extract` opens the document (PDFium, Pillow, within limits,
pictures drawn anew without their metadata) and shows its pages, with a PDF's text layer, to the
provider's reading model, which answers an invoice's fields in a fixed form; `POST
/invoices/draft` writes the UBL of the fields a person confirmed, in code, nothing computed. A
language model may now be shown pictures; on Groq the reading model is Qwen 3.8, on the free
tier, since GPT-OSS reads none.

Findings:

- Groq's GPT-OSS models read no pictures; `qwen/qwen3.8-27b` does and keeps structured outputs
  in strict mode, with the same free limits (checked in Groq's documentation, 2026-11-11).
- PDFium is not thread-safe: PDFs are opened under one lock, in a worker thread.
- The fields of the synthetic invoices draft valid invoices and read back as the same fields:
  the draft and `fields_of` are each other's check, which the evaluations will use.

Verification: the new tests first failing; the API's suite with PostgreSQL, Redis and
`stripe-mock`; ruff, mypy, the OpenAPI document and the web application's types regenerated.

Next: the web application's side, the upload page that reads a PDF or a picture and shows it
beside the fields (`feat/web-invoice-extraction`).

## 2026-11-11 — `feat/web-invoice-extraction` (5 commits, stacked on `feat/api-invoice-extraction`)

Outcome: the upload page reads a PDF or a picture of an invoice (ADR-0062, beta). The API's
model reads the fields; the page shows them beside the document, every one editable, the ones
SEF cannot do without and the model did not find named and marked; the visitor corrects them
and has the invoice made of them, stored, validated and opened on its report, or downloads its
XML. Nothing is stored before that, and the document stays in the page.

Findings:

- The document has to stay in view while the fields are checked: on a wide screen it sticks
  beside them, below the header, and on a phone it opens at its full size in a tab.
- A browser without a PDF viewer of its own (a phone's, a headless one) shows what is inside
  the `<object>`: it is drawn as a notice with a link, not left as a bare one.
- The VAT categories' names are long: the category takes two thirds of a line's width beside
  its rate, so none is cut off. The fields set amounts in proportional figures; in tabular
  ones the font's narrow 1 leaves a gap that reads as a space.

Verification: the web application's suite (Vitest), ESLint, `tsc` and Prettier at every
commit; the pages walked in Chromium against the API with a stand-in
model, in Serbian and English, light and dark, on a desktop and a phone.

Next: the reading measured on PDFs, scans and photographs made from known invoices, against
thresholds (`feat/evals-extraction`).

## 2026-11-11 — `feat/evals-extraction` (6 commits and the recording, stacked on `feat/web-invoice-extraction`)

Outcome: the reading of invoices is measured (ADR-0063). Ten synthetic invoices, by the fields
they print, are printed three ways (a PDF with its text, a scan, a photograph) by
`scripts/render_documents.py`; each document is opened and read as the API reads an upload,
and the reading is measured field by field per form, with the fields it invents and the
documents it makes into a valid invoice, against thresholds set before the first recording.
The reading model's answers are recorded on the maintainer's machine and replayed offline in CI.

Findings:

- SRB-012 requires the buyer's registration number (MB): two golden invoices without one did
  not validate, and now have one, as the validator's check of the golden set caught.
- A page drawn from a PDF may differ in its last bits between platforms: a picture is named in
  a cassette's key by the document it was drawn from, not by its bytes, so that a recording
  made on Windows replays on Linux.
- A photograph is printed no larger than the API reads one (1600 pixels), as a phone's picture
  reaches the model.
- The first recording, on the maintainer's machine, read the thirty documents and then failed
  in drafting: PDFium gives a hyphen at a line break as U+0002, the model copied it into a
  field, and lxml refuses it. Fixed in the reading (the mark shown as a hyphen, every character
  XML cannot hold left out of a page's text and of the fields), and in the runner, which lost
  the half hour of answers: a failed recording now keeps them.

Verification: the evaluations' tests (99 % of the package covered), ruff, mypy; the runner
against the repository with no reading recorded, which says every document is not read, as a
missing answer must. The committed report and the evaluations' check wait for the recording.

Next: the brief's MCP tool `extract_from_pdf` (`feat/mcp-extract-invoice`), then the README
case study.
