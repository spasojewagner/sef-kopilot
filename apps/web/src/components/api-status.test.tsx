import { act, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { forgetAnswers, WAKE } from "@/lib/api";
import { renderIn } from "@/test/render";

import { ApiStatus } from "./api-status";

function health(version: string): Response {
  return new Response(
    JSON.stringify({ status: "ok", service: "sef-kopilot-api", version }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

describe("API status", () => {
  it("says that it is checking, then which version of the API answers", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example");
    const fetch = vi.fn(async () => health("0.2.0"));
    vi.stubGlobal("fetch", fetch);

    renderIn("sr-Latn", <ApiStatus />);

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Proveravam API…");
    expect(
      await screen.findByText("API radi, verzija 0.2.0"),
    ).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "https://api.example/health",
      expect.anything(),
    );
  });

  it("says so when the API cannot be reached", async () => {
    // vitest.setup.ts answers no request: each fails as if the API could not be reached.
    renderIn("en", <ApiStatus />);

    expect(await screen.findByText("API is not answering")).toBeInTheDocument();
  });

  it("says so when the API answers with an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 503 })),
    );

    renderIn("en", <ApiStatus />);

    expect(await screen.findByText("API is not answering")).toBeInTheDocument();
  });

  it("says that the API is waking up while it waits for one that had not answered", async () => {
    vi.useFakeTimers();
    try {
      forgetAnswers();
      vi.stubGlobal(
        "fetch",
        vi.fn(
          () =>
            new Promise<Response>((resolve) =>
              setTimeout(() => resolve(health("0.2.0")), 20_000),
            ),
        ),
      );

      renderIn("sr-Latn", <ApiStatus />);
      expect(screen.getByRole("status")).toHaveTextContent("Proveravam API…");
      await act(() => vi.advanceTimersByTimeAsync(WAKE.wakingAfterMs));
      expect(screen.getByRole("status")).toHaveTextContent("API se budi…");
      await act(() => vi.advanceTimersByTimeAsync(20_000));

      expect(screen.getByRole("status")).toHaveTextContent(
        "API radi, verzija 0.2.0",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps its coloured dot from screen readers, which read the words", () => {
    renderIn("en", <ApiStatus />);

    const dot = screen.getByRole("status").querySelector("span");
    expect(dot).toHaveAttribute("aria-hidden", "true");
  });
});
