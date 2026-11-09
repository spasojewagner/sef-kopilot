<!-- Title = the branch's main commit subject, Conventional Commits format, e.g.
     feat(core): parse UBL 2.1 invoices into typed Pydantic models -->

## Summary

<!-- What and why, in 3–6 lines. Link the backlog item or issue (Closes #12). -->

## Changes

<!-- Bullet list by area: core / api / web / rag / repair / sef / evals / infra / ci / docs -->

-

## How to test

<!-- Exact commands and the expected output. A reviewer should be able to copy-paste. -->

```bash
make test
```

## Screenshots / recordings

<!-- For anything visual. Remove the section if nothing is visual. -->

## Interview notes

<!-- Three questions a senior engineer would ask about this change, with short answers. -->

1. **Q:**
   **A:**
2. **Q:**
   **A:**
3. **Q:**
   **A:**

**The one concept to explain unaided:**

## Checklist

- [ ] Tests added or updated; coverage gates hold (core ≥ 90 %, API ≥ 80 %)
- [ ] `make evals-check` passes: every threshold met, and a changed measure written with `make evals`
- [ ] `pre-commit run --all-files` clean (ruff, mypy --strict, eslint, prettier, gitleaks)
- [ ] Documentation updated (README / ARCHITECTURE / docs)
- [ ] `CHANGELOG.md` entry under `[Unreleased]`
- [ ] No secrets, no real invoice data, no invoice content in logs
- [ ] Database migrations reversible (`alembic downgrade -1`) — or not applicable
- [ ] ADR added for any architectural decision — or not applicable
- [ ] Interview notes copied to `docs/interview/`
