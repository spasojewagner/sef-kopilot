import { useTranslations } from "next-intl";

const REPOSITORY_URL = "https://github.com/spasojewagner/sef-kopilot";

export default function HomePage() {
  const t = useTranslations("home");
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-6 px-6 py-24 text-center">
      <p className="rounded-full border border-amber-300 bg-amber-50 px-3 py-1 text-xs font-medium tracking-wide text-amber-800 uppercase dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
        {t("status")}
      </p>
      <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
        {t("title")}
      </h1>
      <p className="max-w-xl text-lg text-balance text-zinc-700 dark:text-zinc-300">
        {t("tagline")}
      </p>
      <a
        className="rounded-md border border-zinc-300 px-4 py-2 text-sm font-medium transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
        href={REPOSITORY_URL}
        target="_blank"
        rel="noopener noreferrer"
      >
        {t("source")}
      </a>
    </main>
  );
}
