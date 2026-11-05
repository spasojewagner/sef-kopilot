# M2 — `ci/corpus-sources-check`

## Three questions a senior engineer would ask

**1. "Why a scheduled job, and not the download in every CI run?"**

Because the sources are government sites the project does not control. A pull request should
fail for what it changes, not because a ministry's server is slow or a text was consolidated
again that morning. Every CI run already checks the corpus against the converter's tests and
the files against what the converter writes; only the live download is left, and it answers
another question: has a publisher changed a text since we pinned it? Laws change a few times a
year, so once a week is often enough, and it costs one short job.

**2. "How does anyone find out that it failed?"**

A failed scheduled run is reported by GitHub to the user who last changed the workflow's
schedule, the maintainer, and it shows in the Actions tab. The log names the source: "cannot
download …" when the site did not answer, or the source and its new digest when the text
changed. The job can be started by hand to see again. In a public repository GitHub stops
scheduled workflows after 60 days without activity, which the corpus README says.

**3. "What if a site is merely down, or refuses GitHub's runners?"**

The run fails as it would for a changed text, so a false alarm is possible, and the message
tells the two apart. If one site turns out to be unreliable from GitHub's network, the fix is a
retry with a backoff in the converter, or a job that fails only on a changed digest and warns on
a failed download; neither is needed before it happens. What must never happen is a run that
passes without having compared anything: the job downloads every source afresh, with no cache.

## The one concept to explain unaided

**Pinning and watching are two jobs.** The manifest's digests make every build reproducible
and reject a changed source; a scheduled job that downloads the sources afresh is what notices
that a publisher changed one, so that the new edition is reviewed instead of discovered.

## Supporting facts worth remembering

- `.github/workflows/corpus-sources.yml`: Mondays at 04:23 UTC and `workflow_dispatch`;
  `contents: read`; `uv run python scripts/build_corpus.py --fetch --check`, 15 minutes at most.
- The actions are pinned to the same commits as `ci.yml`, so Dependabot updates them together.
- The maintainer's live run of `--fetch --check` (on `fix/rag-corpus-sources`) is the first
  proof that the sites answer a plain client; the scheduled run is the first from GitHub's
  network.
