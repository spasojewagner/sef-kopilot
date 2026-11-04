# 9. Command-line interface: stdlib `argparse`, text and JSON output, exit codes 0/1/2

- Status: accepted
- Date: 2026-11-04
- Deciders: Marko Spasojević
- Technical story: milestone M1, branch `feat/core-cli`

## Context and problem statement

The validator core ships a command, `einvoice validate file.xml --profile srb`, for
accountants' and integrators' scripts, for CI pipelines of ERP vendors and for us. It needs a
stable contract — what it prints, what its exit status means — and a parser. The pipeline
(ADR-0008) already produces the report; the command only presents it.

## Decision drivers

- Scripts and CI decide on the exit status; it must separate "invalid invoice" from "could not
  validate".
- Machines want the full report; people want a short, located list.
- The core package stays small: no dependency that the API and the MCP server do not need.
- Works the same on Linux, macOS and Windows terminals, including documents with Serbian
  characters.

## Considered options

1. **`argparse` from the standard library, subcommands `validate` and `rules`, text or JSON,
   exit 0/1/2** — chosen.
2. Typer or Click.
3. JSON only.

## Decision outcome

Option 1. Concretely:

- `einvoice validate PATH [PATH ...] [--profile srb|en16931|peppol] [--format text|json]
  [--max-violations N] [--show-set-aside]` and `einvoice rules [--profile ...] [--format ...]`;
  `einvoice --version`. The console script is `einvoice_core.cli:console`.
- **Paths:** a file; a directory, standing for the `.xml` files under it in order; or a pattern
  such as `*.xml`. cmd and PowerShell hand patterns to a program as typed, so the command
  expands a path that does not exist and holds `*`, `?` or `[`; an existing file is always taken
  as named. A path that names no document stops the command before anything is validated.
- **Exit status:** 0 when every document is valid — warnings do not change it; 1 when at least
  one is invalid; 2 for a usage error, a path that names no document or cannot be opened, or
  rule sets that have not been fetched (with the command that fetches them). An unreadable
  *document* is a verdict (an `XML` violation, exit 1), a missing *file* is an error (exit 2).
- **Text:** written as each document is judged: one line with the verdict and the counts, then
  each violation with severity, rule id, line and XPath, and its message; the number of
  set-aside reports, or with `--show-set-aside` each of them with its reason; the layers that
  did not run and why. A summary line closes a run over several documents.
- **JSON:** a list of `{"file": …, "report": …}` with the pipeline's report as is, ASCII-escaped
  so that any terminal or pipe can carry it.
- The console script replaces characters a terminal cannot encode instead of crashing.
  Messages may quote document values; the command writes them to standard output only.

### Consequences

Good: no new dependency; the JSON output is the same model the API will return; the exit
status works in any CI system.

Bad / accepted: `argparse` help is plainer than Typer's; its usage errors exit with 2 by
itself, which matches our contract.

## Pros and cons of the options

### Typer or Click

- Good: nicer help, completion.
- Bad: a dependency in the core package for a command that has three options.

### JSON only

- Bad: unreadable for the person at the terminal, who is the first user of the command.
