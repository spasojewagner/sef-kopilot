import { describe, expect, it } from "vitest";

import { json, keepSession, stubApi } from "@/test/api";
import { listedRepair, repair } from "@/test/repairs";

import { getRepair, listRepairs } from "./repairs";

describe("A stored invoice's repairs", () => {
  it("are listed from the invoice's own path", async () => {
    keepSession();
    const asked = stubApi(() => json(200, [listedRepair()]));

    const repairs = await listRepairs("i-1");

    expect(repairs).toEqual([listedRepair()]);
    expect(asked.map(({ method, path }) => `${method} ${path}`)).toEqual([
      "GET /invoices/i-1/repairs",
    ]);
  });

  it("are read one at a time, each id kept to one segment of the path", async () => {
    keepSession();
    const asked = stubApi(() => json(200, repair()));

    await getRepair("../members", "../keys");

    expect(asked.map((request) => request.path)).toEqual([
      "/invoices/..%2Fmembers/repairs/..%2Fkeys",
    ]);
  });
});
