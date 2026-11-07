# 34. The API's image: the lock file's dependencies, rule sets compiled in, migrations at start

- Status: accepted
- Date: 2026-11-07
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `build/api-container`, the first part of
  `chore/infra-deploy`

## Context and problem statement

The public demo runs the API on a free instance of a platform (Render's has 512 MB of memory and
a small share of a CPU, no disk that survives, no shell and no one-off jobs, and it sleeps after
15 minutes without traffic, to wake on the next request), and anyone may host it themselves.
Both need the API as one image that starts the same way everywhere. What goes into the image,
what happens when it is built and what when a container starts?

## Decision drivers

- The same image for the demo and for anyone who hosts it, built from the lock file.
- A small instance: within 512 MB, and ready soon after it wakes, on a fraction of a CPU.
- Nothing fetched when a container starts, and no secret in the image.
- Least privilege: the server owns none of its files.
- The validator keeps its time limit, which a single instance needs against a hostile document.

## Considered options

How the code is installed:

1. **Two stages with uv: the locked dependencies of the API alone, then the code, installed
   where it is.** Chosen.
2. The workspace's packages built as wheels into the environment.
3. The repository as it is, with the tools of development.

When the rule sets are fetched and their stylesheets compiled:

1. **While the image is built.** Chosen.
2. When a container starts.

When the migrations run:

1. **When a container starts, before the server.** Chosen.
2. In a step of the platform before a deployment goes live.
3. By hand.

## Decision outcome

**The build** (`apps/api/Dockerfile`) syncs the API's dependencies from `uv.lock` without the
development tools, first from the lock file alone, so that a change of the code keeps that
layer, then installs the workspace's two packages where they are. The API then finds the rule
sets and the corpus beside its code, as it does in the repository. The rule sets are checked
against their pins and fetched from their official sources when the build is given none, and
`warm_up()` compiles every profile's stylesheets into `third_party/_compiled`, which the core
writes readable by any user. The corpus is copied in, for `python -m sef_api.rag.ingest`. The
base images are build arguments, so that a build without their registries can name mirrors.

**A container** applies the migrations, then runs uvicorn on `PORT` (8000) as the user `sef`,
which owns no file, with `SEF_ENVIRONMENT=production`: the database's URL and the signing key
must be given, and nothing is written to the disk. The validator runs in its child process with
its time limit. Behind a platform's proxy, `FORWARDED_ALLOW_IPS` names the addresses whose
`X-Forwarded-For` is trusted, `*` where the proxy is the only way in, so that the rate limits
count each client and not the proxy (ADR-0018). The image's health check asks `/health`; a
platform's readiness check asks `/ready`.

**CI** builds the image, starts it on an empty database, waits for `/ready`, and registers and
validates an invoice through it.

### Consequences

Good:

- Measured with 512 MB and a tenth of a CPU, from mirrors of the base images: ready about 40 s
  after it starts on an empty database, and 35 s on a migrated one, of which the migrations'
  check takes about 10 s; a typical invoice validated in 0.1 to 0.4 s and one of 11 800 elements
  in about 5 s; at most about 330 MB. Compiling the stylesheets at start would add about 11 s.
- A container needs no network but its database's and, for explanations and repairs, the
  model's: the rule sets are inside, already compiled.
- One image for the demo and for anyone who hosts the API.

Bad / accepted:

- The base images are named by tag, not by digest: their registries could not be reached from
  where this was built. Pinning them by digest, and having Dependabot propose new ones, is a
  change for a build environment that reaches them.
- Migrations at start race if two containers start at once: Alembic takes no lock. The free
  plan runs one instance; more instances need the platform's pre-deploy step, or a lock.
- The server's database role must be allowed to change the schema.
- The migrations' check is a second interpreter's start, about 10 s of a wake on a tenth of a
  CPU; running it in the server's own process would save most of it.
- About 200 MB to pull, compressed, of which the Python runtime and Saxon are most.

## Pros and cons of the options

### Wheels into the environment

- Good: the environment alone, without the code's directories.
- Bad: the API finds the rule sets and the corpus beside its code; installed elsewhere, both
  would need paths of their own, and the corpus's ingest would read nothing.

### The repository as it is

- Good: no Dockerfile to think about.
- Bad: the web application, the tests, the fixtures and the tools of development, hundreds of
  megabytes the server never reads, and a cache that any change of any file invalidates.

### Compiling the stylesheets when a container starts

- Good: a smaller build.
- Bad: every wake of a sleeping instance pays for it, about 11 s more on a tenth of a CPU, and a
  start that fetched rule sets would fail when a source was down.

### A step before a deployment goes live

- Good: a failed migration stops the deployment before it serves.
- Bad: not on the free plan; the start runs the same command, and fails the same way, before the
  server answers.

### By hand

- Bad: someone must remember, and the API serves a schema it does not know until they do.
