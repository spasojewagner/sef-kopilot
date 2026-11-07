import { useTranslations } from "next-intl";

/** What happens to an invoice, in order. */
const STEPS = ["validate", "explain", "repair", "decide"] as const;

/**
 * How the product works, as the course an invoice takes: four waypoints on one line, the
 * validator before the language model and after it, and a person last. The list is ordered for
 * a screen reader; the numbers in the circles are for the eye.
 */
export function Route() {
  const t = useTranslations("home.route");
  return (
    <section
      aria-labelledby="route-title"
      className="page-width grid grid-cols-[minmax(0,1fr)] gap-10 pt-20 pb-20 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16 lg:pt-24 lg:pb-28"
    >
      <div className="lg:sticky lg:top-28 lg:self-start">
        <h2
          id="route-title"
          className="text-3xl leading-tight font-semibold tracking-[-0.02em] sm:text-4xl"
        >
          {t("title")}
        </h2>
        <p className="mt-5 max-w-[34rem] leading-relaxed text-muted-foreground">
          {t("intro")}
        </p>
      </div>
      <ol className="relative grid gap-10">
        <span
          aria-hidden="true"
          className="absolute top-4 bottom-4 left-[15px] w-0.5 rounded-full bg-brand/35"
        />
        {STEPS.map((step, index) => (
          <li key={step} className="relative grid grid-cols-[2rem_1fr] gap-5">
            <span
              aria-hidden="true"
              className="grid size-8 place-items-center rounded-full border-2 border-brand bg-background text-sm font-semibold tabular-nums"
            >
              {index + 1}
            </span>
            <div className="pt-0.5">
              <h3 className="text-lg font-semibold tracking-tight">
                {t(`steps.${step}.title`)}
              </h3>
              <p className="mt-2 max-w-[38rem] leading-relaxed text-muted-foreground">
                {t(`steps.${step}.text`)}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
