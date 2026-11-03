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
