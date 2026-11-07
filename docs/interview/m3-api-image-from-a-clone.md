# M3 — `fix/api-image-fetches-rule-sets`

## Three questions a senior engineer would ask

**1. "CI built the image and started it on every change. Why did the first build on Render
fail?"**

Because CI never took the path Render took. The container job restored the rule sets that the
other jobs cache before it built the image, so the build's check found them current and fetched
nothing. Render builds from a clone of the repository, whose `third_party` holds the manifest
alone, so its build fetched all four rule sets; three of them are pinned to a tag and fetched
with git, which `python:3.12-slim` does not have. The job passed on inputs the platform never
has. It now builds from what a clone holds, and a step fails the job if the build would be given
any untracked file under `third_party`, so that a cache added back cannot hide the path again.

**2. "Why install git, rather than download the tags' archives over HTTPS?"**

Because the git path is the one that checks the pin. The script fetches the tag, then compares
the commit it resolved to with the commit the manifest pins, so a tag moved upstream is caught.
An archive of a tag would need a check of its own. Keeping the script as it is keeps one way to
fetch for a developer, CI and the image. Git is installed in the build's stage only: the image
copies `/app` from there, so what runs has no git, and the image is no larger.

**3. "Doesn't fetching on every run make the job slower and more fragile?"**

Slower by a few seconds: the three git fetches took about 4 s here. More fragile, yes: the job
now fails when GitHub or OASIS cannot be reached. But so does a deploy, which fetches the same
files, so the job fails exactly when a deploy would. The other jobs keep the cache, since they
test the code, not the build.

## The one concept to explain unaided

**Test the path the platform takes.** A cache makes CI fast by skipping work, and every skipped
step is a step the test no longer covers. The job that proves an image builds must start from
what the platform starts from, a clean clone, or it proves only that a warm workspace builds.

## Supporting facts worth remembering

- Render's log: `FileNotFoundError: [Errno 2] No such file or directory: 'git'`, at the step
  `fetch_rulesets.py --check || fetch_rulesets.py`, 22 s into the build.
- `git ls-files --others third_party` lists every untracked file there, ignored or not: empty
  in a clone, 420 files in a developer's workspace.
- `apt-get install --no-install-recommends git` in the build stage; the lists removed in the
  same layer.
