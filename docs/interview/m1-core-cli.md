# M1 — `feat/core-cli`

## Three questions a senior engineer would ask

**1. "Why three exit codes and not just 0 and 1?"**

Because a CI job must tell "this invoice is wrong" from "I could not check it". Exit 1 means
the validator ran and found a fatal violation — the invoice needs fixing. Exit 2 means it could
not run: a usage error, a file that does not exist, rule sets that were never fetched — the job
needs fixing. A malformed *document* is still a verdict (exit 1, an `XML` violation); a missing
*file* is not. Warnings keep exit 0, because they do not stop SEF.

**2. "Why `argparse` when Typer gives nicer help for free?"**

Because the core package is also the engine of the API and the MCP server, and the command has
three options. A dependency for nicer help text is not worth adding to everything that imports
the validator; `argparse` is in the standard library, well understood, and its own usage errors
already exit with 2, matching our contract (ADR-0009).

**3. "Does it work the same in PowerShell?"**

Two things differ on Windows. cmd and PowerShell pass `*.xml` to the program as typed instead of
expanding it, so the command expands a path that does not exist and holds `*`, `?` or `[` (an
existing file is always taken as named), and a directory stands for the `.xml` files under it
on every platform. And a console or pipe may not encode every character a message quotes from a
document: the JSON is ASCII-escaped, and the console script replaces what the stream cannot
encode instead of raising `UnicodeEncodeError`. Messages go to standard output only — never to a
log — because they may contain invoice content.

## The one concept to explain unaided

**A command line is an API with two audiences.** People read the text output; scripts read the
exit status and the JSON. The contract — what 0, 1 and 2 mean, which fields the JSON has — has
to stay stable like any API, which is why the JSON is the pipeline's report model unchanged and
the exit codes are written down in an ADR and pinned by tests.

## Supporting facts worth remembering

- `einvoice validate PATH ... [--profile srb|en16931|peppol] [--format text|json]
  [--max-violations N] [--show-set-aside]`, `einvoice rules`, `einvoice --version`; a PATH is a
  file, a directory or a pattern.
- Missing rule sets: exit 2, and the message names `make rulesets` and
  `EINVOICE_RULESETS_DIR`.
- The text lists each violation with severity, rule id, line and XPath, then the message.
