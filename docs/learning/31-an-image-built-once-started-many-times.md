# 31. An image built once, started many times

A container image is built once, in CI or on the platform, and then started every time a
deployment goes live, an instance wakes or a machine restarts. On a free instance, which sleeps
after 15 minutes and wakes on the next request, "started" happens many times a day. So the
first question for every step is: **build or start?**

```text
build (once)                                 start (every time)
------------------------------------------   ------------------------------------------
dependencies from the lock file              migrations, which need the database
the code                                     the server, as PID 1
rule sets fetched by their pins, compiled    nothing fetched, nothing compiled
no secret                                    secrets from the environment
```

**What is the same for every start belongs in the build.** Compiling the API's rule sets costs
about 11 s on a tenth of a CPU; in the image it costs nothing at a wake. A step that needs the
network at start fails when the network, or a source, does.

**What depends on where it runs belongs in the start.** The database's URL, the signing key, the
model's key: an image with a secret in it gives the secret to everyone who can pull it. The
migrations need the database, so they run when the container starts, before the server.

**Layers are a cache, in order.** Each instruction of a Dockerfile is a layer, rebuilt when it
or anything above it changes. So the slow, rarely changing steps come first: the dependencies
from the lock file alone (`COPY pyproject.toml uv.lock` then `uv sync --no-install-workspace`),
and the code, which changes on every commit, after. A change of a line of code reuses the
installed dependencies.

**Two stages.** The build stage has uv and the build's leftovers; the image copies only
`/app` from it, onto a clean base.

**Least privilege.** The server runs as a user that owns none of its files: a flaw in it cannot
rewrite its code or its rule sets. Anything it must write goes to `/tmp`.

**PID 1.** `exec uvicorn ...` makes the server the container's first process, so that the
platform's stop signal reaches it and it shuts down cleanly; a shell left in between would
swallow the signal, and the container would be killed instead.

**Measure the box.** "It should fit" is not a number. Started with `--memory 512m --cpus 0.1`,
the API's image used at most about 330 MB and was ready in about 40 s, on an empty database,
and in 35 s on a migrated one.

The question to ask of any step in a Dockerfile: does it give the same result every time the
container starts? Then it belongs in the build.
