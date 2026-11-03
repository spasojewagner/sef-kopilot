# einvoice-core

Pure-Python validation engine for UBL 2.1 electronic invoices. It is the deterministic
"source of truth" layer of SEF Kopilot: XSD validation, EN 16931 and Peppol BIS Billing 3.0
Schematron, the Serbian SRB-CIUS rule set, arithmetic checks, the patch engine and the
command-line interface all live here. No language model is ever involved.

Planned module layout (delivered across milestone M1):

```text
einvoice_core/
  parser/       UBL 2.1 XML → typed Pydantic models (hardened lxml parsing)
  xsd/          XSD validation against the UBL 2.1 schemas
  schematron/   XSLT-based Schematron runner (Saxon-HE via saxonche), compiled once and cached
  rules/srb/    SRB-CIUS rules, one rule per module, each referencing the specification paragraph
  arithmetic/   EN 16931 BR-CO-* arithmetic checks implemented in Python
  patches/      patch model, forbidden-field guard, apply + re-validate + diff
  cli.py        `einvoice validate file.xml --profile srb`
```

## Development

From the repository root:

```bash
uv sync --all-packages
uv run pytest packages/einvoice_core --cov=einvoice_core
uv run mypy packages/einvoice_core
uv run ruff check packages/einvoice_core
```
