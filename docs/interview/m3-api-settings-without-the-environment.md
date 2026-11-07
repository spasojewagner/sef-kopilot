# M3 — `test/api-settings-without-the-environment`

## Three questions a senior engineer would ask

**1. "`settings_for` passed every value a test needs. How did a test application still read the
developer's `.env`?"**

Because a pydantic-settings class builds its values from all of its sources even when it is
validated from a dictionary: the values given, the environment, `.env`, the secrets directory,
in that order of priority. `Settings.model_validate(values)` let the given values win and took
everything else from the machine. A developer whose `.env` names Groq and its key got test
applications with Groq's client, and CI, which has no `.env`, did not.

**2. "Most tests replace the model anyway. Why does it matter?"**

Not every test does. An application built by the `client` fixture keeps the explainer and the
repairer its settings make, so a test that reached the model through it would send a synthetic
invoice's violations to the provider, on the developer's key and quota. And the other settings,
the limits, the origins, the validator's mode, change what a test checks: a suite that passes in
CI could fail on a laptop, or pass there for the wrong reason. Run with a hostile environment
(a provider and embeddings with keys, an origin, a lower limit, the validator's other mode),
eight of the existing tests failed before this change, and none do now.

**3. "Why a method on `Settings` rather than a helper in the tests?"**

Three places needed the same thing: the OpenAPI exporter and the end-to-end test's launcher
each held a subclass of their own, and the API's tests needed one. `Settings.from_values()`
does it once, next to the settings it builds, so the values are checked as ever (production
still requires its secret and its database). The way the API itself reads its settings,
`Settings()`, is unchanged.

## The one concept to explain unaided

**Configuration has sources, and a test must choose them.** A settings class reads the values
given, then the environment, then files, the first one winning; a test that means to depend on
nothing but itself names its values and turns the other sources off.

## Supporting facts worth remembering

- pydantic-settings: `settings_customise_sources` returns the sources in priority order;
  returning only `init_settings` reads the values given and nothing else.
- `Settings.from_values({"SEF_ENVIRONMENT": "test", ...})` takes the variables' names, as the
  environment would give them.
- Found in `test/web-golden-path`, while the launcher's settings were made independent of the
  machine.
