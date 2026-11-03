# M0 — `chore/bootstrap`

## Three questions a senior engineer would ask

**1. "You have a Python workspace and a Node workspace in one repository. What stops them from
drifting apart, and why not a build orchestrator?"**

One gate applies to both: `pre-commit` runs ruff/mypy for Python and ESLint/Prettier for the
web app from the same configuration file, and CI runs `pre-commit run --all-files` plus each
test suite. Versions are pinned in two lock files (`uv.lock`, `pnpm-lock.yaml`) that CI
installs with `--locked` / `--frozen-lockfile`, so a stale lock fails the build. A build
orchestrator (Nx, Turborepo) would add task graphs and caching, which pay off with many
packages; with two applications it would be a third tool to explain for no gain. The layout
does not prevent adding one later (ADR-0001).

**2. "Why is the EN 16931 Schematron fetched by a script instead of committed with the code?"**

Licensing and integrity. The CEN artefacts are EUPL-licensed and the Peppol rules carry
OpenPeppol's terms; the project is Apache-2.0, so they stay outside the tree and are never
redistributed. The manifest pins a *tag and the commit it must resolve to*: if upstream moves
the tag, the fetch fails loudly instead of silently changing which rules the validator runs.
The fetcher also learned a real lesson during M0 — the upstream repository has a branch and a
tag with the same release name, and `git clone --branch` picks the branch — so it fetches
`refs/tags/<name>` explicitly and verifies the commit.

**3. "The language model is part of the product. What exactly can it decide?"**

Nothing about validity. Layer 1 (XSD, Schematron, SRB-CIUS rules in code, arithmetic in
Python) is the only component that produces a verdict. The model may (a) explain a violation,
citing only regulation chunks that retrieval actually returned — a citation that does not
resolve to a stored chunk id fails the response — and (b) propose patches as data, which code
applies, layer 1 re-validates and a human approves; patches touching amounts, VAT, tax
identifiers or dates of supply are rejected before they are applied. These are tests, not
guidelines (ADR-0002).

## The one concept to explain unaided

**Why the deterministic validator is the source of truth and the model sits between two
deterministic walls** — including what each wall checks and why "the model edits the XML and
we validate afterwards" is not good enough (unbounded changes, nothing to forbid per field,
no per-change diff to approve).

## Supporting facts worth remembering

- EN 16931 artefacts pinned: `validation-1.3.17` (2026-10-09, EUPL 1.2); Peppol BIS Billing
  3.0 pinned: `3.0.21` (May 2026, mandatory from 2026-08-17). OpenPeppol publishes only
  Schematron sources, so Peppol rules must be compiled to XSLT by this project (M1 ADR).
- Coverage gates: core ≥ 90 %, API ≥ 80 %. Commit message check: types and scopes fixed.
- pnpm `minimumReleaseAge: 1440` keeps day-old releases out of the lock file.
