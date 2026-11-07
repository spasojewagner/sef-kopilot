# 32. A warm cache hides a cold path

A step that has two branches, "use what is there" and "make it", is tested only on the branch
its inputs choose. The API's image had such a step:

```text
RUN fetch_rulesets.py --check || fetch_rulesets.py
        │                          │
        │ rule sets given, current │ none given (a clone)
        ▼                          ▼
   keep them                   fetch them: git, HTTPS
   (CI, with its cache)        (Render; never run in CI)
```

CI restored the rule sets from its cache before it built the image, so the check passed and the
fetch never ran. Render builds from a clone, which holds none, so its build took the other
branch, and the build's stage had no git. CI was green; the first deploy failed.

**Every cache skips work, and skipped work is untested work.** That is the bargain a cache makes,
and for most jobs it is a good one: the unit tests test the code, not how the rule sets arrive.
But a job whose purpose is to prove that something builds as a platform builds it must start
from what the platform starts from.

**Ask what the platform is given.** For a Docker build on Render, Vercel, or any CI of someone
else: a fresh clone of the commit, no untracked files, no caches of yours, no `.env`, no
credentials but those configured. A test of the build that is given more tests a different
build.

**Make the intent executable.** A comment that says "this job must not use the cache" is read
once; a step that fails when `git ls-files --others third_party` lists anything fails every time
someone adds the cache back.

**Keep both branches alive.** When a step can either reuse or make, run the "make" branch
somewhere on a schedule or in one job, or delete it. A branch that no test takes is one that
will fail the first time it is needed, at the worst moment: here, the first deploy.
