import { describe, expect, it } from "vitest";

import { parseDiff } from "./diff";

/** A repair's diff as the API writes it: a line replaced in one hunk, one added in the other. */
const DIFF = `--- before
+++ after
@@ -5,5 +5,5 @@
   <cbc:IssueDate>2026-10-05</cbc:IssueDate>
   <cbc:DueDate>2026-10-20</cbc:DueDate>
-  <cbc:InvoiceTypeCode>393</cbc:InvoiceTypeCode>
+  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
   <cbc:Note>Rok za plaćanje je 15 dana od datuma prometa.</cbc:Note>
   <cbc:DocumentCurrencyCode>RSD</cbc:DocumentCurrencyCode>
@@ -21,2 +21,3 @@
     <cac:Party>
+      <cbc:EndpointID schemeID="9948">100000024</cbc:EndpointID>
       <cac:PartyName>
`;

describe("A repair's diff", () => {
  it("is read line by line, with a gap where unchanged lines are left out", () => {
    expect(parseDiff(DIFF)).toEqual([
      { kind: "gap" },
      { kind: "context", text: "  <cbc:IssueDate>2026-10-05</cbc:IssueDate>" },
      { kind: "context", text: "  <cbc:DueDate>2026-10-20</cbc:DueDate>" },
      {
        kind: "removed",
        text: "  <cbc:InvoiceTypeCode>393</cbc:InvoiceTypeCode>",
      },
      {
        kind: "added",
        text: "  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>",
      },
      {
        kind: "context",
        text: "  <cbc:Note>Rok za plaćanje je 15 dana od datuma prometa.</cbc:Note>",
      },
      {
        kind: "context",
        text: "  <cbc:DocumentCurrencyCode>RSD</cbc:DocumentCurrencyCode>",
      },
      { kind: "gap" },
      { kind: "context", text: "    <cac:Party>" },
      {
        kind: "added",
        text: '      <cbc:EndpointID schemeID="9948">100000024</cbc:EndpointID>',
      },
      { kind: "context", text: "      <cac:PartyName>" },
    ]);
  });

  it("has no gap above a hunk that starts the document", () => {
    expect(
      parseDiff("--- before\n+++ after\n@@ -1,2 +1,2 @@\n-a\n+b\n c\n"),
    ).toEqual([
      { kind: "removed", text: "a" },
      { kind: "added", text: "b" },
      { kind: "context", text: "c" },
    ]);
  });

  it("keeps a removed line that starts like a header", () => {
    expect(
      parseDiff(
        "--- before\n+++ after\n@@ -1 +1 @@\n--- a dash line\n+++ another\n",
      ),
    ).toEqual([
      { kind: "removed", text: "-- a dash line" },
      { kind: "added", text: "++ another" },
    ]);
  });

  it("leaves out the lines that say nothing about the invoice", () => {
    expect(
      parseDiff("@@ -3 +3 @@\n-a\n+b\n\\ No newline at end of file\n"),
    ).toEqual([
      { kind: "gap" },
      { kind: "removed", text: "a" },
      { kind: "added", text: "b" },
    ]);
  });

  it("is empty when the repair changes nothing", () => {
    expect(parseDiff("")).toEqual([]);
  });
});
