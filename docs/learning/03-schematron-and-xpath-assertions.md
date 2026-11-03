# Schematron and XPath assertions

XML Schema answers "is this document *shaped* like an invoice?". Business rules — "the total
with VAT equals the total without VAT plus the VAT", "a buyer in Serbia has a PIB" — are
statements about values, and the standards publish them in **Schematron** (ISO/IEC 19757-3).

## The language in four words: pattern, rule, assert, report

```xml
<pattern id="totals">
  <rule context="/ubl:Invoice/cac:LegalMonetaryTotal">          <!-- where: an XPath -->
    <assert id="EX-01" flag="fatal"                               <!-- what must hold -->
            test="xs:decimal(cbc:PayableAmount) ge 0">
      [EX-01]-The amount due for payment must not be negative.
    </assert>
  </rule>
</pattern>
```

- A **rule** selects nodes with its `context` XPath; every selected node is checked.
- An **assert** fails when its `test` is false; a **report** fires when its `test` is true.
- `id` names the rule (`BR-CO-15`, `PEPPOL-EN16931-R001`), `flag` says how bad a failure is
  (`fatal` or `warning` in EN 16931 and Peppol), the text is the message.
- `queryBinding="xslt2"` means the tests are XPath 2.0: typed values (`xs:decimal(…)`),
  `every $x in … satisfies …`, regular expressions; `let` defines variables.
- **Abstract patterns** state a rule once in semantic terms (`$BT-112`) and are instantiated
  per syntax (UBL, CII) with `is-a` — that is how EN 16931 binds one model to two syntaxes.

## How a rule set runs

Schematron is not executed directly; it is compiled to XSLT, and the XSLT is applied to the
document. The output is **SVRL** (Schematron Validation Report Language).

```text
 rules.sch ─▶ include ─▶ expand abstract ─▶ generate XSLT ─▶ rules.xslt     (once, cached)
                                                               │
 invoice.xml ──────────────────────────────────────▶ Saxon ◀───┘
                                                       │
            <svrl:failed-assert id="BR-CO-15" flag="fatal" location="/*:Invoice[…][1]">
              <svrl:text>[BR-CO-15]-Invoice total amount with VAT …</svrl:text>
            </svrl:failed-assert>                     ─▶  Violation(rule_id, severity,
                                                                    xpath, line, message)
```

CEN publishes both the Schematron and the compiled XSLT for EN 16931; OpenPeppol publishes
only Schematron, so SEF Kopilot compiles it with the ISO reference pipeline (ADR-0005).

## Things that surprise people

- **The location is the rule's context, not the faulty child.** BR-CO-15's context is the
  invoice element, so the violation points at `/ubl:Invoice` even though the wrong value sits
  in `cac:LegalMonetaryTotal`. The explainer has to name the business terms (BT-112, BT-109,
  BT-110); the XPath alone does not.
- **Rules assume a schema-valid document.** `xs:decimal('12,50')` is a dynamic *error*, not a
  failed assertion. That is why XSD validation runs first.
- **"Success" is silent.** SVRL lists what failed; a rule that passed leaves no trace (unless
  `fired-rule` output is switched on, which only says the rule was evaluated).
- **One rule can fail many times** — once per context node. Ten lines with a bad unit code
  give ten BR-CL-23 violations, each with its own line's XPath.
- **Global `let` variables read the document** (Peppol's `$profile`), so the processor must be
  given the document as global context item, not only as the node to match templates on.

## Why the rules are executed, never re-implemented

Over a thousand assertions, maintained by the standards bodies, with published unit tests.
Running them as published — and proving it against those unit tests — is the only way to say
"this invoice passes EN 16931 and Peppol BIS 3.0" with a straight face. Our own code is reserved
for what no published Schematron covers: the SRB-CIUS rules and the arithmetic in Python.
