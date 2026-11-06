# Contributing

Thank you for your interest in SEF Kopilot. This document describes how the repository is
worked on. The rules are deliberately strict: the git history is part of the product, and it
should read as the story of a careful engineering team.

## Development process

SEF Kopilot is built by its maintainer, Marko Spasojević, working with an AI coding assistant
as a pair-programming partner. The assistant follows the working agreement in
[`AGENTS.md`](AGENTS.md) (identical to `CLAUDE.md`), which is a distilled version of the
project charter in [`docs/BRIEF.md`](docs/BRIEF.md). The maintainer reviews every change,
pushes every branch, opens and merges every pull request and owns every line in the repository.
Commits carry the maintainer's identity and no tool attribution; the process is documented
here instead.

External contributions are welcome once the validator core is released (`v0.1.0`). Until then
the fastest way to help is to open an issue with a concrete, reproducible case (synthetic
invoices only — see [Data rules](#data-rules)).

## Prerequisites

- Git 2.40+
- Python 3.12 and [`uv`](https://docs.astral.sh/uv/)
- Node.js 22 LTS and `pnpm` (enable it with `corepack enable`)
- Docker (Docker Desktop on Windows/macOS) for PostgreSQL and Redis
- GNU `make` (optional; every target is a plain command you can run by hand — on Windows use
  Git Bash, `winget install GnuWin32.Make`, or run the commands from the `Makefile` directly)

## Branching model

GitHub flow with visible branches:

- `main` is always releasable and protected. Nobody commits to it directly after the initial
  commit; a pre-commit hook refuses commits on `main`.
- One branch per unit of work, named `type/scope-short-description`, lowercase, hyphens:
  `feat/core-srb-cius-rules`, `fix/api-upload-size-limit`, `docs/adr-schematron-runner`,
  `chore/ci-eval-gate`, `refactor/core-rule-registry`, `test/core-br-co-arithmetic`,
  `perf/validator-cache`.
- Branches start from the latest `main` (`git switch -c feat/x main`). A branch that depends on
  an unmerged branch is "stacked"; say so in the pull request and rebase onto `main` after the
  base merges.
- Pull requests are merged on GitHub with a **merge commit** (no squash, no rebase-merge) so
  `git log --graph` shows the branch structure. After a merge:
  `git switch main && git pull --ff-only && git branch -d <branch>`.
- A branch is small: one pull request is one reviewable change, ideally under ~400 lines of
  hand-written diff. Split larger work.
- There are no release branches; releases are annotated tags on `main`.

## Commits

Commits follow [Conventional Commits](https://www.conventionalcommits.org/) and are atomic,
buildable and written in English:

```text
type(scope): imperative summary ≤ 72 chars, no trailing period

Why this change exists and what it does that is not obvious from the diff.
Wrap at 72 characters. Reference issues: Closes #12 / Refs #7.
```

- `type` is one of `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`, `ci`, `build`,
  `style`. A breaking change adds `!` after the scope and a `BREAKING CHANGE:` footer.
- `scope` is one of `core`, `api`, `web`, `mcp`, `rag`, `repair`, `sef`, `evals`, `infra`, `ci`,
  `docs`, `adr`, `deps`, `repo`.
- One logical change per commit. A feature commit includes its tests and documentation. Never
  mix a refactor with a behaviour change. Never commit broken tests or failing lint.
- Subjects such as `wip`, `fix`, `update`, `changes`, `stuff`, `misc`, `final` are rejected.
- Aim for 3–10 commits per branch, each one buildable on its own.

Examples of good subjects:

```text
chore(repo): bootstrap monorepo with uv, pnpm and pre-commit
feat(core): parse UBL 2.1 invoices into typed Pydantic models
feat(core): run EN 16931 and Peppol BIS Schematron via saxonche
test(core): property-test BR-CO-10 line total arithmetic
feat(api): stream validation progress over SSE
fix(repair): reject patches that touch monetary fields
ci(evals): fail the build when repair success drops below 80%
docs(adr): 0003 deterministic validator is the source of truth
```

Every commit is made with the repository-local identity
`Marko Spasojevic <markospasojevic758@gmail.com>` and no co-author trailers.

## Pre-commit hooks

`pre-commit` runs on every commit: `ruff` (lint and format), `mypy --strict` on the core
package, ESLint and Prettier for the web app, `gitleaks` for secrets, generic hygiene checks,
and a Conventional Commits check on the commit message. Install the hooks once after cloning:

```bash
uv sync --all-packages
uv run pre-commit install --install-hooks
```

Hooks are never bypassed with `--no-verify`. If a hook is wrong, fix the hook.

## Pull requests

Every pull request uses [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md):

1. **Summary** — what and why, in 3–6 lines.
2. **Changes** — bullet list by area.
3. **How to test** — exact commands and expected output.
4. **Screenshots / recordings** — for anything visual.
5. **Interview notes** — three questions a senior engineer would ask about the change, with
   short answers, and the one concept a maintainer must be able to explain unaided.
6. **Checklist** — tests added, docs updated, `CHANGELOG.md` entry, no secrets, migrations
   reversible, ADR added if a decision was made.

The pull request title is the branch's main commit subject, in Conventional Commits format.

## Definition of done

- All tests pass locally and in CI; new behaviour has tests. Coverage: `packages/einvoice_core`
  ≥ 90 %, `apps/api` ≥ 80 %.
- `ruff`, `mypy --strict` (core), `eslint`, `tsc --noEmit` and `pre-commit run --all-files` are
  clean.
- No secrets, no real data, no invoice content in logs.
- Public API documented (OpenAPI descriptions and examples). After a change to the API's routes
  or answers, `make openapi` writes `docs/api/openapi.json` and the web application's types from
  it; the tests fail until it has run. Database migrations are reversible and
  `alembic downgrade -1` is exercised in CI.
- `CHANGELOG.md` updated under `[Unreleased]`; an ADR added in `docs/adr/` for every
  architectural decision (MADR format).
- Performance budget measured and noted where relevant: validate a typical invoice < 500 ms
  warm, explanation < 6 s, the whole repair loop < 20 s.

## Dependency updates

- Dependabot opens grouped pull requests every Monday for minor and patch updates of the Python
  (`uv`) and Node (`npm`) dependencies, and for GitHub Actions. They are merged when CI is green.
- Major versions of Python and Node packages are **planned migrations**, never automatic: they
  are done by hand in their own branch (`chore/deps-<package>-<major>`) once the frameworks
  that depend on them support the new major — for example a TypeScript or ESLint major waits
  for Next.js, and `@types/node` follows the Node 22 runtime, not the newest Node release. The
  migration branch reads the upstream changelog, updates code and configuration, and records
  anything surprising in its pull request.
- Security advisories are handled as soon as they are raised, whatever the version jump.

## Versions, tags and changelog

- [Semantic Versioning](https://semver.org/). `CHANGELOG.md` follows
  [Keep a Changelog](https://keepachangelog.com/).
- Each milestone ends with: the `[Unreleased] → [x.y.z] - date` move in the changelog, version
  bumps in `pyproject.toml` and `package.json`, an annotated tag (`git tag -a v0.1.0 -m "..."`)
  and a GitHub Release whose notes are the changelog section.

## Architecture decision records

Decisions that shape the system are recorded in `docs/adr/NNNN-title.md` using the
[MADR](https://adr.github.io/madr/) template. A decision record is immutable once merged; a
changed decision gets a new record that supersedes the old one.

## Data rules

- Fixtures contain only official example files and synthetic invoices (fake companies, fake
  tax identifiers that pass the checksum, obviously fake names). Never a real company's invoice,
  not even anonymised.
- The regulation corpus comes from official sources only and is stored as text with its source
  URL, fetch date and effective date.
- Nothing in the repository or in logs ever contains invoice content from a real party.

## Code of conduct

Be kind, be precise, assume good intent. Disagreements are settled with evidence (a failing
test, a benchmark, a paragraph of the regulation), not with volume.
