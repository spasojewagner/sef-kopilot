import { useTranslations } from "next-intl";

/** The rule sets, by the names they go by, and the message that says what each checks. */
const RULE_SETS = [
  { name: "UBL 2.1", says: "ubl" },
  { name: "EN 16931", says: "en16931" },
  { name: "SRB-CIUS", says: "srb" },
  { name: "Peppol BIS Billing 3.0", says: "peppol" },
] as const;

/** What an invoice is checked against: the official rule sets, the Serbian rules, the sums. */
export function Standards() {
  const t = useTranslations("home.standards");
  return (
    <section aria-labelledby="standards-title" className="border-y bg-card/60">
      <div className="page-width grid grid-cols-[minmax(0,1fr)] gap-10 py-20 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16 lg:py-24">
        <div>
          <h2
            id="standards-title"
            className="text-3xl leading-tight font-semibold tracking-[-0.02em] sm:text-4xl"
          >
            {t("title")}
          </h2>
          <p className="mt-5 max-w-[34rem] leading-relaxed text-muted-foreground">
            {t("intro")}
          </p>
        </div>
        <dl className="divide-y border-y">
          {[
            ...RULE_SETS.map(({ name, says }) => [name, t(says)] as const),
            [t("arithmetic"), t("arithmeticText")] as const,
          ].map(([name, text]) => (
            <div
              key={name}
              className="grid gap-1 py-5 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6"
            >
              <dt className="font-semibold">{name}</dt>
              <dd className="leading-relaxed text-muted-foreground">{text}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
