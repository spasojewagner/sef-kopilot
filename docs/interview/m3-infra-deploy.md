# M3 — `chore/infra-deploy`

## Three questions a senior engineer would ask

**1. "The brief said Cloudflare Pages. Why is the web application on Vercel?"**

Because the report's page needs a server to read an invoice's id from its address (ADR-0028).
On Cloudflare that server is the OpenNext adapter running as a Worker, and the free plan limits a
Worker to 3 MiB compressed, which a Next.js application with its dependencies is near or above;
the alternative, a static export, would move the id into the browser and the language redirect
into the host's rules. Vercel runs Next.js as it is built, on its free Hobby plan. The cost is the
Hobby plan's terms, personal and non-commercial, which fit a portfolio demo; a commercial launch
moves to a paid plan. The deviation is recorded in ADR-0035.

**2. "How do the secrets get into production without being in the repository?"**

Each is typed by the account's owner into the platform that keeps it. `render.yaml` lists the
variables, and those marked `sync: false`, the database's URL, the model's key and the web
application's origin, are asked for when the Blueprint is applied; the signing key is generated
by Render. The web application's only setting, the API's address, is public by design: it is
written into the code the browser loads. The corpus is loaded from the owner's terminal, with the
database's URL in that shell's environment for one command.

**3. "What does a visitor see when the free API is asleep?"**

Render's free service sleeps after 15 minutes without a request. The next request wakes it,
which takes about a minute, of which the image's own start is about 35 s on a small CPU. Today
the pages would say that the API does not answer, since a request gives up after 10 s; the next
branch makes them say that it is waking up, and wait. Neon's compute suspends too, after
5 minutes, but wakes in a moment.

## The one concept to explain unaided

**Configuration in the repository, secrets out of it.** `render.yaml` and `vercel.json` say how
each part is built and run, reviewed like code; the values that would grant access live only in
the platforms, typed by their owner.

## Supporting facts worth remembering

- `autoDeployTrigger: checksPass`: Render deploys a commit of `main` only once its checks pass;
  `buildFilter` skips commits that change nothing of the image.
- Neon's direct connection, as `postgresql+asyncpg://...?ssl=require`: the pooled one breaks
  asyncpg's prepared statements, and asyncpg takes `ssl`, not `sslmode`.
- Vercel: Root Directory `apps/web`, Node.js 22 from `package.json`, Corepack for pnpm
  (`ENABLE_EXPERIMENTAL_COREPACK=1`), and `vercel.json`'s `ignoreCommand` to skip builds.
- No Redis: one instance runs its jobs in its own process.
- Previews cannot call the API, which allows the production origin alone.
