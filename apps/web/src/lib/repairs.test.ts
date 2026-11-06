import { describe, expect, it } from "vitest";

import { json, keepSession, stubApi } from "@/test/api";
import { repair } from "@/test/repairs";

import { getRepair } from "./repairs";

describe("A stored invoice's repairs", () => {
  it("are read one at a time, each id kept to one segment of the path", async () => {
    keepSession();
    const asked = stubApi(() => json(200, repair()));

    await getRepair("../members", "../keys");

    expect(asked.map((request) => request.path)).toEqual([
      "/invoices/..%2Fmembers/repairs/..%2Fkeys",
    ]);
  });
});
