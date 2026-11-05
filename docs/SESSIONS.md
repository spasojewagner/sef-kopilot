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
