# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Every pull request adds its
line under **Unreleased**; the maintainer moves the section to a version heading when a milestone
is tagged.

## [Unreleased]

### Changed

- Dependabot proposes only minor and patch updates for Python and Node packages; major
  versions are planned migrations (CONTRIBUTING.md, "Dependency updates").

### Added

- `einvoice_core`: Schematron layer. The EN 16931 rules (official CEN XSLT) and the Peppol BIS
  Billing 3.0 rules run with Saxon-HE (`saxonche`); Schematron sources are compiled with the
  pinned ISO Schematron pipeline and cached; SVRL results become violations with canonical
  XPaths and source lines. Verified against every unit test CEN and OpenPeppol publish
  (ADR-0005).
- Rule-set fetcher: the ISO Schematron reference implementation (`iso-schematron`).
- `einvoice_core`: violation model shared by all validation layers, and UBL 2.1 XML Schema
  validation against the official OASIS schemas, with confined schema loading, canonical
  XPath locations and readable messages (ADR-0004).
- Rule-set fetcher: pinned ZIP archive sources (HTTPS URL + SHA-256) next to git tags; the
  OASIS UBL 2.1 package is now fetched into `third_party/ubl-2.1`.
- `einvoice_core`: typed invoice document model following the EN 16931 semantic model
  (`Decimal` amounts, BT/BG-named fields, canonical XPath per business group), hardened XML
  loading (no DTD, entities or network; size limit) and a UBL 2.1 Invoice / CreditNote parser
  verified against all official CEN and OpenPeppol example documents (ADR-0003).
- Project charter (`docs/BRIEF.md`), README with vision and architecture, contributor guide,
  security policy, backlog and session log.
- uv workspace with `packages/einvoice_core` (src layout, strict typing, 90 % coverage gate)
  and `apps/api` (FastAPI application factory with `GET /health` and `GET /ready`).
- `apps/web`: Next.js (App Router, TypeScript strict, Tailwind CSS v4) scaffold with Vitest
  and Testing Library; pnpm workspace with a one-day minimum release age and shared Prettier.
- `pre-commit` hooks: hygiene, ruff, uv.lock, mypy --strict, ESLint, Prettier, gitleaks and a
  Conventional Commits check with the project's fixed types and scopes.
- GitHub Actions CI: pre-commit on all files, test suites with coverage gates, web build,
  rule-set fetch, full-history gitleaks scan, dependency audits; Dependabot for uv, npm and
  actions.
- `infra/docker-compose.yml` with PostgreSQL 16 + pgvector and Redis; `.env.example`; Makefile.
- `scripts/fetch_rulesets.py` with `third_party/manifest.json` pinning EN 16931
  `validation-1.3.17` and Peppol BIS Billing 3.0 `3.0.21` by tag and commit.
- ADR-0001 "Monorepo and tooling", ADR-0002 "Deterministic validator is the source of truth",
  `docs/ARCHITECTURE.md`, first learning and interview notes, pull request and issue templates.

### Fixed

- The parser reads BT-11 (project reference) on credit notes, where UBL 2.1 carries it as an
  `AdditionalDocumentReference` with type code 50.
- The synthetic credit note satisfies EN 16931: one payment means code (UBL-SR-47) and no UBL
  extensions (UBL-CR-001).
- The core test suite passes on Windows: opening XML text as a file name fails there with
  `EINVAL` rather than `ENOENT`, and examples with an upper-case `.XML` extension are listed
  once instead of twice.
- Rule-set fetcher: archive member names are judged by POSIX and Windows rules on every host;
  backslashes, drive letters, NTFS streams and NUL bytes are refused, also in directory entries.

[Unreleased]: https://github.com/spasojewagner/sef-kopilot/commits/main
