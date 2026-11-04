# M1 — `chore/release-0.1.0`

## Three questions a senior engineer would ask

**1. "Why 0.1.0 and not 1.0.0 — the validator works?"**

Under Semantic Versioning, 0.x says the public API may still change, and it will: the HTTP API,
the explainer and the repairer (M2–M3) will shape what the core returns. 1.0.0 is planned for
M7, when the API is stable and documented.

**2. "Why do all packages share one version?"**

They are released together from one repository and only make sense together today; one version
keeps the tag, the changelog and the packages aligned. A package gets its own version when it is
published on its own.

**3. "Why is the tag made after the merge, not on the release branch?"**

The tag must point at what `main` contains, and merges on GitHub are merge commits: a tag on the
branch would point at a commit that is not `main`'s. The maintainer tags the merge commit, so the
tag, the changelog's links and the release notes agree.

## The one concept to explain unaided

**Semantic Versioning.** MAJOR.MINOR.PATCH: a major increment breaks compatibility, a minor one
adds behaviour compatibly, a patch only fixes. Before 1.0.0 anything may change, which is why the
changelog says, release by release, what did.
