import type { Report, Violation } from "@/lib/invoices";

/** The violations of one rule, where the report found them. */
export interface RuleViolations {
  ruleId: string;
  severity: Violation["severity"];
  layer: Violation["layer"];
  /** What the rule's source says, in English, as the first violation reports it. */
  message: string;
  violations: Violation[];
}

/**
 * A report's violations by rule: the rules that make the invoice invalid first, then the
 * warnings, each in the order the validator found its first violation. A rule's violations
 * keep the validator's order, which is the document's.
 */
export function byRule(report: Report): RuleViolations[] {
  const rules = new Map<string, RuleViolations>();
  for (const violation of report.violations) {
    const key = `${violation.severity} ${violation.rule_id}`;
    const rule = rules.get(key);
    if (rule) {
      rule.violations.push(violation);
    } else {
      rules.set(key, {
        ruleId: violation.rule_id,
        severity: violation.severity,
        layer: violation.layer,
        message: violation.message,
        violations: [violation],
      });
    }
  }
  const all = [...rules.values()];
  return [
    ...all.filter((rule) => rule.severity === "fatal"),
    ...all.filter((rule) => rule.severity !== "fatal"),
  ];
}

/** Whether the document is XML, which patches apply to: the report's XML layer found nothing. */
export function isXml(report: Report): boolean {
  return report.layers.some(
    (layer) => layer.layer === "xml" && layer.ran && layer.violations === 0,
  );
}
