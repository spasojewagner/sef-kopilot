import { describe, expect, it } from "vitest";

import type { Violation } from "@/lib/invoices";
import { storedInvoice } from "@/test/invoices";

import { byRule, isXml } from "./report";

function violation(
  rule_id: string,
  severity: Violation["severity"],
  xpath: string,
): Violation {
  return {
    rule_id,
    severity,
    message: `${rule_id} failed`,
    xpath,
    layer: "schematron",
    code: null,
    line: null,
  };
}

describe("A report's violations by rule", () => {
  it("put the rules that make an invoice invalid first, each in the validator's order", () => {
    const report = {
      ...storedInvoice().report,
      violations: [
        violation("BR-CO-15", "warning", "/a"),
        violation("BR-16", "fatal", "/b"),
        violation("BR-CO-15", "warning", "/c"),
        violation("SRB-009", "fatal", "/d"),
        violation("BR-16", "fatal", "/e"),
      ],
    };

    const rules = byRule(report);

    expect(rules.map((rule) => [rule.ruleId, rule.severity])).toEqual([
      ["BR-16", "fatal"],
      ["SRB-009", "fatal"],
      ["BR-CO-15", "warning"],
    ]);
    expect(rules[0].violations.map((found) => found.xpath)).toEqual([
      "/b",
      "/e",
    ]);
    expect(rules[2].violations.map((found) => found.xpath)).toEqual([
      "/a",
      "/c",
    ]);
    expect(rules[0].message).toBe("BR-16 failed");
  });

  it("keep a rule's errors apart from its warnings", () => {
    const report = {
      ...storedInvoice().report,
      violations: [
        violation("PEPPOL-EN16931-R008", "warning", "/a"),
        violation("PEPPOL-EN16931-R008", "fatal", "/b"),
      ],
    };

    expect(
      byRule(report).map((rule) => [
        rule.severity,
        rule.violations.map((found) => found.xpath),
      ]),
    ).toEqual([
      ["fatal", ["/b"]],
      ["warning", ["/a"]],
    ]);
  });

  it("are none for a report without violations", () => {
    expect(byRule({ ...storedInvoice().report, violations: [] })).toEqual([]);
  });
});

describe("A document that patches apply to", () => {
  it("is XML: the report's XML layer ran and found nothing", () => {
    const report = storedInvoice().report;
    const xml = (ran: boolean, violations: number) => ({
      ...report,
      layers: report.layers.map((layer) =>
        layer.layer === "xml" ? { ...layer, ran, violations } : layer,
      ),
    });

    expect(isXml(report)).toBe(true);
    expect(isXml(xml(true, 1))).toBe(false);
    expect(isXml(xml(false, 0))).toBe(false);
    expect(isXml({ ...report, layers: [] })).toBe(false);
  });
});
