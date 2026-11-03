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

## 2026-11-03 — `chore/bootstrap` (8 commits on top of the initial commit)

Outcome: milestone M0 complete. Monorepo skeleton (uv workspace with `einvoice_core` and the
FastAPI `api`, pnpm workspace with the Next.js `web`), pre-commit gate with the Conventional
Commits check, GitHub Actions CI (pre-commit, tests with coverage gates, web build, rule-set
fetch, gitleaks history scan, dependency audits), docker-compose for PostgreSQL + pgvector and
Redis, the pinned rule-set fetcher (EN 16931 `validation-1.3.17`, Peppol BIS `3.0.21`),
ADR-0001 and ADR-0002, architecture map, first learning and interview notes.

Verification: 22 Python tests and 2 Vitest tests green; core and API coverage 100 %;
`mypy --strict`, ruff, ESLint, `tsc --noEmit`, Prettier and `pre-commit run --all-files` clean;
`next build` succeeds; `docker compose config` valid; real rule-set fetch verified against the
pinned commits; `gitleaks` finds nothing in the history.

Decisions: tags are fetched by full ref name because the EN 16931 repository has a branch and a
tag with the same release name; pnpm `minimumReleaseAge` set to one day; Prettier does not
format Markdown; `mypy --strict` applies to every Python package, not only the core.

Next: `feat/core-ubl-parser` (M1).
