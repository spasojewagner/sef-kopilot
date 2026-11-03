const REPOSITORY_URL = "https://github.com/spasojewagner/sef-kopilot";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-6 px-6 py-24 text-center">
      <p className="rounded-full border border-amber-300 bg-amber-50 px-3 py-1 text-xs font-medium tracking-wide text-amber-800 uppercase dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
        pre-alpha
      </p>
      <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
        SEF Kopilot
      </h1>
      <p className="max-w-xl text-lg text-balance text-zinc-700 dark:text-zinc-300">
        Deterministička validacija, objašnjenja na običnom jeziku i pregledne
        ispravke elektronskih faktura za SEF, EN 16931 i Peppol.
      </p>
      <p
        lang="en"
        className="max-w-xl text-balance text-zinc-500 dark:text-zinc-400"
      >
        Deterministic validation, plain-language explanations and reviewable
        repairs for Serbian and EU e-invoices.
      </p>
      <p className="max-w-xl text-sm text-balance text-zinc-500 dark:text-zinc-400">
        Nezavisan projekat otvorenog koda. Nije sertifikovani validator i nije
        povezan sa Ministarstvom finansija ni sa SEF platformom.
      </p>
      <a
        className="rounded-md border border-zinc-300 px-4 py-2 text-sm font-medium transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
        href={REPOSITORY_URL}
        target="_blank"
        rel="noopener noreferrer"
      >
        Izvorni kod na GitHubu
      </a>
    </main>
  );
}
