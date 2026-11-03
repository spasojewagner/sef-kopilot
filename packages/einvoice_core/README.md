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
  srb/          SRB-CIUS rules authored from the specification: the rule shape, the cited sources,
                identifier checks (PIB, JBKJS) and one module per rule in srb/rules/
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

## SRB-CIUS rules

The Serbian rules are authored from the specification (version of 06.06.2025), one module
per rule; each names the business terms it concerns and cites the passages it implements
(ADR-0006). Like Schematron, they run on a schema-valid tree:

```python
from einvoice_core.srb import validate_srb

for violation in validate_srb(tree):
    print(violation.rule_id, violation.xpath, violation.message)
    # SRB-009 /ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cbc:EndpointID
    #   [SRB-009]-The PIB 123456789 in the seller electronic address (BT-34) cannot exist: ...
```

| Rule | Requirement | Business terms | Severity |
| --- | --- | --- | --- |
| SRB-001 | The invoice type code is 380, 381, 383 or 386 | BT-3 | fatal |
| SRB-002 | The VAT accounting currency is RSD | BT-5, BT-6 | fatal |
| SRB-003 | The VAT point date (BT-7) is not used | BT-7, BT-8 | fatal |
| SRB-004 | An advance invoice has a payment due date | BT-3, BT-9 | fatal |
| SRB-005 | The specification identifier is the SRB-CIUS identifier | BT-24 | fatal |
| SRB-006 | A public-funds user has one JBKJS identifier of five digits, without a scheme | BT-29, BT-46, BT-60 | fatal |
| SRB-007 | Seller, buyer and tax representative have a VAT identifier RS followed by a PIB | BT-31, BT-48, BT-63 | fatal |
| SRB-008 | Seller and buyer electronic addresses are a PIB with scheme 9948 | BT-34, BT-49 | fatal |
| SRB-009 | Every nine-digit PIB has a serial number in range and a valid check digit | BT-31, BT-34, BT-48, BT-49, BT-63 | fatal |
| SRB-010 | A public-procurement buyer reference is JN-JBKJS: followed by five digits | BT-10 | fatal |
| SRB-011 | A preceding invoice reference gives the preceding invoice's issue date | BG-3, BT-26 | fatal |
| SRB-012 | Buyer, payee and a resident seller give a legal registration number, without a scheme | BT-30, BT-47, BT-61 | fatal |
| SRB-013 | The seller states its VAT registration status | BT-32 | warning |
| SRB-014 | The seller's VAT registration status is VAT or NO-VAT | BT-32 | fatal |

A test keeps this table identical to the rules.

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
