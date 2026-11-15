import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Reveal, RevealCurtain, RevealWords } from "./reveal";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Landing reveals", () => {
  function observe(top: number, reduced = false) {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      top,
    } as DOMRect);
    const matchMedia = vi.fn(() => ({ matches: reduced }));
    vi.stubGlobal("matchMedia", matchMedia);
    const watch = vi.fn();
    const disconnect = vi.fn();
    let notify: IntersectionObserverCallback;
    const observer = vi.fn(function (callback: IntersectionObserverCallback) {
      notify = callback;
      return { observe: watch, disconnect };
    });
    vi.stubGlobal("IntersectionObserver", observer);
    return {
      matchMedia,
      observer,
      watch,
      disconnect,
      intersect(isIntersecting: boolean) {
        act(() => {
          notify(
            [{ isIntersecting } as IntersectionObserverEntry],
            {} as IntersectionObserver,
          );
        });
      },
    };
  }

  it("keeps the full heading name and staggers each word or rich span", () => {
    render(
      <RevealWords as="h1">
        {"Check an "}
        <span className="whitespace-nowrap">e-invoice</span>
        {" before sending"}
      </RevealWords>,
    );

    const heading = screen.getByRole("heading", {
      level: 1,
      name: "Check an e-invoice before sending",
    });
    const words = [
      ...heading.querySelectorAll<HTMLElement>("[data-reveal-word]"),
    ];
    expect(words.map((word) => word.textContent)).toEqual([
      "Check",
      "an",
      "e-invoice",
      "before",
      "sending",
    ]);
    expect(
      words.map((word) => word.style.getPropertyValue("--reveal-delay")),
    ).toEqual(["0ms", "40ms", "80ms", "120ms", "160ms"]);
    expect(words[2].firstElementChild).toHaveClass("whitespace-nowrap");
  });

  it("leaves reduced motion content in place without observing it", () => {
    const { matchMedia, observer } = observe(window.innerHeight + 20, true);
    const { container } = render(
      <>
        <RevealWords>Heading below the fold</RevealWords>
        <RevealCurtain>Diagram</RevealCurtain>
        <Reveal>Card</Reveal>
      </>,
    );
    expect(matchMedia).toHaveBeenCalledWith("(prefers-reduced-motion: reduce)");
    expect(observer).not.toHaveBeenCalled();
    expect(container.querySelector("[data-reveal-state]")).toBeNull();
  });

  it("waits below the fold, reveals on entry and disconnects", () => {
    const { observer, watch, disconnect, intersect } = observe(
      window.innerHeight + 20,
    );
    render(<RevealWords>Heading below the fold</RevealWords>);
    const heading = screen.getByRole("heading", {
      name: "Heading below the fold",
    });

    expect(heading).toHaveAttribute("data-reveal-state", "waiting");
    expect(observer).toHaveBeenCalledWith(expect.any(Function), {
      rootMargin: "0px 0px -15% 0px",
    });
    expect(watch).toHaveBeenCalledWith(heading);
    intersect(false);
    expect(heading).toHaveAttribute("data-reveal-state", "waiting");
    intersect(true);
    expect(disconnect).toHaveBeenCalledOnce();
    intersect(false);
    expect(heading).toHaveAttribute("data-reveal-state", "shown");
  });

  it("does not hide a section already in the viewport when the page mounts", () => {
    const { observer } = observe(window.innerHeight - 1);
    render(<RevealWords>Already visible</RevealWords>);
    expect(screen.getByRole("heading")).not.toHaveAttribute(
      "data-reveal-state",
    );
    expect(observer).not.toHaveBeenCalled();
  });
});
