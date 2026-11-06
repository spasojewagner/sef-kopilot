import { describe, expect, it } from "vitest";

import { json, keepSession, stubApi } from "@/test/api";
import { storedInvoice } from "@/test/invoices";

import { getInvoice } from "./invoices";

describe("A stored invoice", () => {
  it("is asked for by its id, which stays one segment of the path", async () => {
    keepSession();
    const asked = stubApi(() => json(200, storedInvoice()));

    // Whatever the id holds: `/invoices/../members` would be the browser's `/members`.
    await getInvoice("../members");

    expect(asked.map((request) => request.path)).toEqual([
      "/invoices/..%2Fmembers",
    ]);
  });
});
