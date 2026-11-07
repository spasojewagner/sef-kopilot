import { cn } from "@/lib/utils";

/**
 * The mark's geometry, on a 64-unit square: a compass bezel open at its four diagonals, and a
 * check whose long stroke is the needle, leaving the ring through the north-east gap. The
 * favicon (`src/app/icon.svg`) draws the same paths in fixed colours; a test keeps them equal.
 */
export const MARK = {
  ring: "M43.13 49.81A21 21 0 0 1 20.87 49.81M14.19 43.13A21 21 0 0 1 14.19 20.87M20.87 14.19A21 21 0 0 1 43.13 14.19M49.81 20.87A21 21 0 0 1 49.81 43.13",
  arm: "M19.5 32.5L27.5 40.5",
  needle: "M29.71 42.37L49.50 14.50L25.29 38.63Z",
  joint: { cx: 27.5, cy: 40.5, r: 2.9 },
} as const;

/**
 * The brand's mark. The ring takes the colour of the text around it and the check the brand's
 * accent, so the mark suits whatever surface it is drawn on. Beside the product's name it is
 * decoration, hidden from screen readers; alone, it is an image with the name it is given.
 */
export function LogoMark({
  className,
  label,
}: {
  className?: string;
  label?: string;
}) {
  return (
    <svg
      viewBox="8 8 48 48"
      className={cn("shrink-0", className)}
      {...(label
        ? { role: "img", "aria-label": label }
        : { "aria-hidden": true, focusable: false })}
    >
      <path
        d={MARK.ring}
        fill="none"
        stroke="currentColor"
        strokeWidth={4.5}
        strokeLinecap="round"
      />
      <g className="fill-brand stroke-brand">
        <path d={MARK.arm} strokeWidth={5.8} strokeLinecap="round" />
        <circle {...MARK.joint} stroke="none" />
        <path d={MARK.needle} stroke="none" />
      </g>
    </svg>
  );
}

/** The mark and the product's name, set in the brand's typeface. */
export function Logo({
  name,
  className,
  nameClassName,
}: {
  name: string;
  className?: string;
  nameClassName?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2.5 text-[1.0625rem] font-semibold tracking-[-0.015em]",
        className,
      )}
    >
      <LogoMark className="size-7" />
      <span className={nameClassName}>{name}</span>
    </span>
  );
}
