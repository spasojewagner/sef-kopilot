import { describe, expect, it } from "vitest";

describe("The tests", () => {
  it("reach no network: a request no test answers fails as if the API were away", async () => {
    await expect(fetch("http://127.0.0.1:8000/health")).rejects.toThrow(
      TypeError,
    );
    expect(fetch).toHaveBeenCalledOnce();
  });
});
