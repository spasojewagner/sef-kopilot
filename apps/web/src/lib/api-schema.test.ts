// @vitest-environment node
import { readFileSync } from "node:fs";

import openapiTS, { astToString, COMMENT_HEADER } from "openapi-typescript";
import { describe, expect, it } from "vitest";

const DOCUMENT = new URL("../../../../docs/api/openapi.json", import.meta.url);
const TYPES = new URL("./api-schema.d.ts", import.meta.url);

describe("The API's types", () => {
  it("are those of the OpenAPI document in the repository", async () => {
    const generated =
      COMMENT_HEADER + astToString(await openapiTS(DOCUMENT, { silent: true }));

    expect(
      readFileSync(TYPES, "utf8"),
      "src/lib/api-schema.d.ts is out of date: run `pnpm --filter @sef-kopilot/web api:types`",
    ).toBe(generated);
  });
});
