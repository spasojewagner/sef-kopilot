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
  schematron.py EN 16931 and Peppol BIS Schematron run with Saxon-HE; sources compiled with the ISO
                pipeline and cached; SVRL reports turned into located violations
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

The business rules run on a schema-valid tree. `en16931` is CEN's official XSLT; a Peppol
BIS 3.0 invoice is checked with `en16931-peppol` (the EN 16931 version Peppol bundles) and
`peppol`:

```python
from einvoice_core.schematron import validate_schematron

for violation in validate_schematron(tree, ["en16931"]):
    print(violation.rule_id, violation.severity, violation.xpath, violation.message)
    # BR-CO-15 fatal /ubl:Invoice [BR-CO-15]-Invoice total amount with VAT (BT-112) = ...
```

## Development

From the repository root:

```bash
uv sync --all-packages
make rulesets                      # schemas, rule sets, the Schematron compiler, examples, unit tests
uv run pytest packages/einvoice_core --cov=einvoice_core
uv run pytest packages/einvoice_core -m "not conformance"   # quick run without the rule-set suite
uv run mypy
uv run ruff check packages/einvoice_core
```
