# 1. Monorepo and tooling

- Status: accepted
- Date: 2026-11-03
- Deciders: Marko Spasojević
- Technical story: milestone M0 (`chore/bootstrap`)

## Context and problem statement

SEF Kopilot is one product with three deliverables: a pure-Python validation engine, a FastAPI
service and a Next.js web application. They evolve together (a new rule in the engine changes
API responses and UI texts in the same change), the team is one maintainer with an AI pair,
and the repository itself is read by hiring managers and senior engineers. The stack is fixed
by the project brief (`docs/BRIEF.md`, §3). What remains to decide is how the code is laid
out and which tools enforce the quality bar, and how to keep that enforcement identical on a
Windows laptop, in a Linux container and in CI.

## Decision drivers

- Cross-cutting changes must be atomic and reviewable in one pull request.
- Every check a reviewer relies on must run locally *before* a commit exists and again in CI,
  with the same configuration.
- A single, boring, well-understood tool per job; the maintainer must be able to explain each.
- Third-party rule sets carry their own licenses (EUPL, OpenPeppol terms) and must stay
  separable from the Apache-2.0 code.
- Windows is the maintainer's daily platform; CI runs on Linux.

## Considered options

1. **One repository (monorepo) with a uv workspace and a pnpm workspace** — chosen.
2. Separate repositories per deliverable.
3. Monorepo with a build orchestrator (Nx, Turborepo, Pants).
4. Vendoring the rule sets into the repository instead of fetching them.

## Decision outcome

Option 1. Concretely:

- **Python:** a uv workspace whose root `pyproject.toml` is a *virtual* project (no `[project]`
  table). It holds the shared development dependencies and the shared `ruff`, `mypy`, `pytest`
  and `coverage` configuration; members are `packages/einvoice_core` and `apps/api`, both in
  `src/` layout with `hatchling` as the build backend. One `uv.lock`, one `.venv`.
- **Node:** a pnpm workspace with `apps/web` as the only member for now, `packageManager`
  pinned, `minimumReleaseAge` of one day (a published package version must be at least a day
  old before it is resolved), and Prettier configured once at the root.
- **One local gate:** `pre-commit` runs hygiene checks, `ruff` (lint + format), `uv.lock`
  consistency, `mypy --strict` on every Python package, ESLint and Prettier for the web app,
  `gitleaks`, and a Conventional Commits check of the message with the project's fixed types and
  scopes. A hook refuses commits on `main`. CI runs the identical suite on all files, plus the
  test suites with their coverage gates, a full-history secret scan and dependency audits.
- **`mypy --strict` everywhere from day one.** The brief requires it for the core package; it
  is cheaper to keep two small packages strict from the first commit than to tighten later.
- **Makefile as a thin wrapper.** Every target is one plain command that can be copied on a
  machine without GNU make.
- **Third-party rule sets are fetched, not vendored** (`scripts/fetch_rulesets.py`,
  `third_party/manifest.json`): the manifest pins a tag and the commit it must resolve to.
- **Pinned supply chain:** GitHub Actions by commit SHA, hooks by tag, `ruff` by exact version
  so the hook and the local run agree; Dependabot keeps all three ecosystems current.
- **Line endings:** `* text=auto eol=lf` in `.gitattributes`, so files are LF on Windows too and
  hooks, diffs and Docker builds behave the same everywhere.

### Consequences

Good:

- One clone, one CI run and one set of configuration files describe the whole system.
- A change that spans engine, API and UI is one commit series and one review.
- Reviewers can trust that what CI checks is what every commit was checked against.

Bad / accepted:

- Two toolchains (Python + Node) are required even for a backend-only change.
- The first `pre-commit` run is slow: it builds hook environments, including a Go toolchain for
  `gitleaks`.
- "Virtual workspace root" and "src layout" are two concepts to explain to newcomers; the
  learning note `docs/learning/01-monorepo-uv-workspaces-and-pre-commit.md` covers them.
- `make` is optional on Windows; the README lists the underlying commands.

## Pros and cons of the options

### Separate repositories

- Good: smaller individual repositories, independent release cadence.
- Bad: cross-cutting changes become multi-repository choreography; three CI setups to keep in
  sync; harder for a reviewer to see the whole system.

### Build orchestrator (Nx, Turborepo, Pants)

- Good: task graph, remote caching, affected-only builds.
- Bad: a third tool to learn and explain for two small applications; the gain appears only
  with many packages. Can be added later without changing the layout.

### Vendoring the rule sets

- Good: no network needed to build.
- Bad: EUPL and OpenPeppol material mixed into an Apache-2.0 tree; several megabytes of XML
  in every clone; upgrades are large, noisy diffs instead of a two-line manifest change.
