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
  pipeline.py   one call for all layers under a profile (srb, en16931, peppol): the verdict, the
                violations, and the published rules a profile sets aside, with reasons
  arithmetic.py EN 16931 calculation rules BR-CO-10 to BR-CO-17 in Python, CEN's semantics,
                with the expected and the found amount in each violation
  patches/      planned: patch model, forbidden-field guard, apply + re-validate + diff
  cli.py        `einvoice validate` and `einvoice rules`: text or JSON, exit status 0 / 1 / 2
```

## Usage

From the command line (ADR-0009):

```bash
einvoice validate invoice.xml                   # SRB profile; exit 0 valid, 1 invalid, 2 error
einvoice validate a.xml b.xml --format json     # the full reports
einvoice validate invoices/                     # every .xml file under the directory
einvoice validate invoice.xml --show-set-aside  # with the EN 16931 rules the profile sets aside
einvoice rules --profile srb                    # rule sets, SRB-CIUS rules, set-asides
```

One call validates a document under a profile and returns the whole verdict (ADR-0008):

```python
from pathlib import Path

from einvoice_core.pipeline import validate

report = validate(Path("invoice.xml").read_bytes(), "srb")
report.valid  # False when any violation is fatal
for violation in report.violations:  # XSD, Schematron, SRB-CIUS, arithmetic, in that order
    print(violation.layer, violation.rule_id, violation.xpath, violation.message)
for item in report.set_aside:  # EN 16931 rules SRB-CIUS widens, with the reason
    print(item.violation.rule_id, item.reason, item.replaced_by)
```

The layers can also be used one by one:

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

## Calculation rules

`validate_arithmetic` recomputes BR-CO-10 to BR-CO-17 from the typed model with exact decimal
arithmetic and CEN's rounding and tolerance, so a violation can say what the amount should be
(ADR-0007). It reads the document totals, never the copies inside the Serbian extension:

```python
from einvoice_core.arithmetic import validate_arithmetic

for violation in validate_arithmetic(tree):
    print(violation.rule_id, violation.xpath, violation.message)
    # BR-CO-10 /ubl:Invoice/cac:LegalMonetaryTotal/cbc:LineExtensionAmount
    #   [BR-CO-10]-Sum of Invoice line net amount (BT-106) = ...: expected 12000.00, found 12000.01.
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
| SRB-015 | Seller, buyer and tax representative addresses name the city | BT-37, BT-52, BT-66 | fatal |
| SRB-016 | A resident seller and a tax representative give a post code | BT-38, BT-67 | fatal |
| SRB-017 | The buyer's address gives a post code | BT-53 | warning |
| SRB-018 | The actual delivery date is given when VAT is due on supply or on collection | BT-8, BT-72 | fatal |
| SRB-019 | A payment model in the remittance information is written (modNN) reference | BT-83 | fatal |
| SRB-020 | Every VAT category code is one SRB-CIUS allows | BT-95, BT-102, BT-118, BT-151 | fatal |
| SRB-021 | Categories S and AE are charged at 20 or 10 percent | BT-96, BT-103, BT-119, BT-152 | fatal |
| SRB-022 | A VAT exemption reason code is one of its own category's codes | BT-118, BT-121 | fatal |
| SRB-023 | A VAT exemption reason code is in the Ministry's list | BT-121 | warning |
| SRB-024 | Exempt and non-taxed VAT breakdowns give an exemption reason code | BT-118, BT-121 | fatal |
| SRB-025 | The reduced total with VAT is the total with VAT minus the paid amount | BT-E13, BT-112, BT-113 | fatal |
| SRB-026 | Every advance used names one of the invoice's preceding invoices | BG-E1, BT-E1, BG-3, BT-25 | fatal |
| SRB-027 | On a foreign-currency invoice the extension's VAT breakdowns are also in RSD | BG-E5, BG-E6 | fatal |
| SRB-028 | A foreign-currency invoice gives its VAT breakdown in RSD as well | BG-E7, BT-5 | fatal |
| SRB-029 | An invoice that uses the Serbian extension says so in BT-24 | BT-24 | warning |

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
