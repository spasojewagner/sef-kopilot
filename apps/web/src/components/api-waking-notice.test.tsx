import { act, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { forgetAnswers, getHealth, WAKE } from "@/lib/api";
import { renderIn } from "@/test/render";

import { ApiWakingNotice } from "./api-waking-notice";

const HEALTH = {
  status: "ok",
  service: "sef-kopilot-api",
  version: "0.2.0",
  public_demo: false,
};

/** The API answers `/health` ``ms`` after it is asked. */
function answerAfter(ms: number): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) =>
          setTimeout(
            () =>
              resolve(new Response(JSON.stringify(HEALTH), { status: 200 })),
            ms,
          ),
        ),
    ),
  );
}

describe("The notice that the API is waking up", () => {
  it("says nothing while no page waits for the API", () => {
    renderIn("sr-Latn", <ApiWakingNotice />);

    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("says why the pages wait while the API wakes, and goes once it answers", async () => {
    vi.useFakeTimers();
    try {
      forgetAnswers();
      answerAfter(20_000);
      renderIn("sr-Latn", <ApiWakingNotice />);

      const checked = getHealth();
      await act(() => vi.advanceTimersByTimeAsync(WAKE.wakingAfterMs));
      const notice = screen.getByRole("status");
      expect(notice).toHaveTextContent("API se budi");
      expect(notice).toHaveTextContent(
        "Server koji je neko vreme mirovao budi se za oko minut. Ono što pošaljete sačekaće i otići čim odgovori.",
      );
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();

      await act(() => vi.advanceTimersByTimeAsync(20_000));
      await checked;
      expect(screen.getByRole("status")).toBeEmptyDOMElement();
    } finally {
      vi.useRealTimers();
    }
  });

  it("says nothing of a wait that is over within a few seconds", async () => {
    vi.useFakeTimers();
    try {
      forgetAnswers();
      answerAfter(WAKE.wakingAfterMs - 1);
      renderIn("en", <ApiWakingNotice />);

      const checked = getHealth();
      await act(() => vi.advanceTimersByTimeAsync(WAKE.wakingAfterMs));
      await checked;

      expect(screen.getByRole("status")).toBeEmptyDOMElement();
    } finally {
      vi.useRealTimers();
    }
  });
});
