# einvoice-core

Pure-Python validation engine for UBL 2.1 electronic invoices. It is the deterministic
"source of truth" layer of SEF Kopilot: XSD validation, EN 16931 and Peppol BIS Billing 3.0
Schematron, the Serbian SRB-CIUS rule set, arithmetic checks, the patch engine and the
command-line interface all live here. No language model is ever involved.

Module layout (modules marked *planned* arrive during milestone M1):

```text
einvoice_core/
  model.py      typed invoice document model following the EN 16931 semantic model (BT/BG terms)
  xml.py        hardened XML loading (no DTD, no entities, no network, size limit) and canonical XPath
  ubl.py        UBL 2.1 Invoice / CreditNote → model (EN 16931-3-2 syntax binding)
  violations.py the violation every layer reports: rule id, severity, message, canonical XPath, layer
  rulesets.py   locating the fetched rule sets (EINVOICE_RULESETS_DIR or the repository's third_party/)
  xsd.py        UBL 2.1 XML Schema validation with confined schema loading and located violations
  schematron/   planned: XSLT-based Schematron runner (Saxon-HE via saxonche), compiled once and cached
  rules/srb/    planned: SRB-CIUS rules, one rule per module, each referencing the specification paragraph
  arithmetic/   planned: EN 16931 BR-CO-* arithmetic checks implemented in Python
  patches/      planned: patch model, forbidden-field guard, apply + re-validate + diff
  cli.py        planned: `einvoice validate file.xml --profile srb`
```

## Usage

```python
from einvoice_core.ubl import parse_invoice

invoice = parse_invoice("fixtures/invoices/synthetic/srb-minimal-invoice.xml")
invoice.id  # 'RF-2026-000123'  (BT-1)
invoice.totals.payable_amount  # Decimal('14400.00')  (BT-115)
invoice.lines[0].xpath  # '/ubl:Invoice/cac:InvoiceLine'
```

Callers that also need the XML tree (Schematron, XPath-addressed violations, patching) use
`einvoice_core.xml.load_document` followed by `einvoice_core.ubl.build_invoice`. Schema
validation works on the same tree:

```python
from einvoice_core.xml import load_document
from einvoice_core.xsd import validate_xsd

tree = load_document(path)
for violation in validate_xsd(tree):  # empty when the document is valid UBL 2.1
    print(violation.xpath, violation.message)
```

## Development

From the repository root:

```bash
uv sync --all-packages
make rulesets                      # UBL 2.1 schemas and official example documents used by the tests
uv run pytest packages/einvoice_core --cov=einvoice_core
uv run mypy
uv run ruff check packages/einvoice_core
```
