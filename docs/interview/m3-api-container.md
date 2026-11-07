# M3 — `build/api-container`

## Three questions a senior engineer would ask

**1. "Why compile the rule sets while the image is built, and not when the server starts?"**

Because a free instance starts many times a day: it sleeps after 15 minutes without traffic and
wakes on the next request. Compiling every profile's stylesheets adds about 11 s to a start on a
tenth of a CPU; done in the build, a wake does not pay for it. And fetching them at start would
make every start depend on the rule sets' sources being up. The build checks them against their
pins, so the image holds exactly the versions the tests ran against.

**2. "The container runs the migrations when it starts. What can go wrong?"**

Two containers starting at once would both migrate, and Alembic takes no lock. The free plan runs
one instance, so that cannot happen there; scaling out needs the platform's pre-deploy step or a
lock first, which the ADR records. A failed migration stops the start before the server answers,
so the platform keeps the previous deployment. And the server's database role must be allowed to
change the schema, which is the default role's right on a managed database.

**3. "How do you know it fits a free instance?"**

I measured it: the image started with `--memory 512m --cpus 0.1`, a tenth of a CPU and the free
plan's memory, on an empty database. It was ready in about 40 s, migrations included (35 s on a
migrated database), validated a typical invoice in 0.1 to 0.4 s and one of 11 800 elements in
about 5 s, and its memory peaked at about 330 MB: the API's process and the validator's child,
which keeps its time limit.

## The one concept to explain unaided

**Build or start.** What is the same every time a container starts (dependencies, code, compiled
rule sets) belongs in the image; what depends on where it runs (the database, the secrets, the
migrations that need them) belongs in the start.

## Supporting facts worth remembering

- `docker build -f apps/api/Dockerfile -t sef-kopilot-api .` from the repository's root; the
  context is cut to what the image needs by `.dockerignore`.
- `docker/start.sh`: `alembic upgrade head`, then `exec uvicorn ...` so that the server is PID 1
  and gets the stop signal.
- `FORWARDED_ALLOW_IPS=*` behind a platform's proxy, so that the rate limits see the client's
  address and not the proxy's (ADR-0018).
- The user `sef` (uid 10001) owns no file; Saxon's configuration goes to `/tmp`.
- CI builds the image, starts it on an empty database, waits for `/ready` and validates an
  invoice through it.
