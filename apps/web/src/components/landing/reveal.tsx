"use client";

import {
  Children,
  isValidElement,
  useEffect,
  useRef,
  type CSSProperties,
  type ReactNode,
} from "react";

import "./reveal.css";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

/** Arm only the content below the fold, and stop watching as soon as it appears. */
function useReveal(onLoad: boolean) {
  const ref = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const element = ref.current;
    if (
      !element ||
      onLoad ||
      window.matchMedia?.(REDUCED_MOTION).matches ||
      typeof IntersectionObserver === "undefined" ||
      element.getBoundingClientRect().top < window.innerHeight
    ) {
      return;
    }

    const show = () => {
      if (element.dataset.revealState === "waiting") {
        element.dataset.revealState = "shown";
        observer.disconnect();
      }
    };
    const showOnFocus = () => {
      element.dataset.revealState = "focused";
      observer.disconnect();
    };
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          show();
        }
      },
      { rootMargin: "0px 0px -15% 0px" },
    );

    element.dataset.revealState = "waiting";
    observer.observe(element);
    element.addEventListener("focusin", showOnFocus, { once: true });
    return () => {
      observer.disconnect();
      element.removeEventListener("focusin", showOnFocus);
      delete element.dataset.revealState;
    };
  }, [onLoad]);

  return (element: HTMLElement | null) => {
    ref.current = element;
  };
}

function textOf(children: ReactNode): string {
  return Children.toArray(children)
    .map((node): string =>
      isValidElement<{ children?: ReactNode }>(node)
        ? textOf(node.props.children)
        : String(node),
    )
    .join("");
}

type RevealProps = {
  children: ReactNode;
  className?: string;
  delay?: number;
};

function delayStyle(delay: number): CSSProperties {
  return { "--reveal-delay": `${delay}ms` } as CSSProperties;
}

/** Preserve the full heading name while each word has an independent animation. */
export function RevealWords({
  as: Heading = "h2",
  children,
  className,
  id,
  onLoad = false,
}: RevealProps & { as?: "h1" | "h2"; id?: string; onLoad?: boolean }) {
  const ref = useReveal(onLoad);
  let word = 0;
  const parts = Children.toArray(children).flatMap((part) =>
    typeof part === "string" ? part.split(/(\s+)/u) : [part],
  );
  return (
    <Heading
      ref={ref}
      id={id}
      className={className}
      aria-label={textOf(children)}
      data-reveal="words"
      data-reveal-load={onLoad || undefined}
    >
      <span aria-hidden="true">
        {parts.map((part, index) =>
          typeof part === "string" && !part.trim() ? (
            part
          ) : (
            <span key={index} data-reveal-word style={delayStyle(word++ * 40)}>
              {part}
            </span>
          ),
        )}
      </span>
    </Heading>
  );
}

/** Clip the outer frame as the content moves in the opposite direction. */
export function RevealCurtain({
  children,
  className,
  delay = 0,
  onLoad = false,
  fromRight = false,
}: RevealProps & { onLoad?: boolean; fromRight?: boolean }) {
  return (
    <div
      ref={useReveal(onLoad)}
      className={className}
      data-reveal="curtain"
      data-reveal-load={onLoad || undefined}
      data-reveal-right={fromRight || undefined}
      style={delayStyle(delay)}
    >
      <div data-reveal-inner>{children}</div>
    </div>
  );
}

/** Fade and lift a single item without changing its place in the layout. */
export function Reveal({
  as: Item = "div",
  children,
  className,
  delay = 0,
}: RevealProps & { as?: "div" | "figure" | "li" }) {
  return (
    <Item
      ref={useReveal(false)}
      className={className}
      data-reveal="rise"
      style={delayStyle(delay)}
    >
      {children}
    </Item>
  );
}
