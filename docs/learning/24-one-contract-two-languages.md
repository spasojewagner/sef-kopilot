# 24. One contract, two languages: the API's OpenAPI document and the web application's types

The API is Python and the web application is TypeScript. Each answer the pages read, a stored
invoice and its report, has a shape that both sides must agree on. Write it twice, once as a
Pydantic model and once as a TypeScript type, and the two drift apart: a field renamed in the
API still compiles in the web application, and shows `undefined` on the page.

The cure is one description and a machine that copies it. FastAPI already writes an OpenAPI
document from the Pydantic models (**code first**: the code is the source, the document its
description). SEF Kopilot keeps that document in the repository and generates the types from it:

```text
the Pydantic models (apps/api)
   │  FastAPI writes the document; scripts/export_openapi.py keeps it
   ▼
docs/api/openapi.json                 a test: is it the API's?
   │  openapi-typescript
   ▼
apps/web/src/lib/api-schema.d.ts      a test: is it the document's?
   │  Schemas["StoredInvoiceOut"]
   ▼
the pages                             tsc: does every page read what the API sends?
```

**Generated files kept in the repository, and tests that generate them again.** Each test makes
the file afresh and compares it with the one committed (a *golden file*). A change to the API
without `make openapi` fails a test; a change with it shows in the pull request as a diff of the
contract, where a removed field is a removed line. The alternative, generating during the build
from a running API, needs the API, its database and a network, and a reviewer never sees the
contract change.

**A golden file must be deterministic.** If generating it depends on the machine, the test fails
on the next one. The API's document depended on its settings, read from the environment and a
`.env` file, so the export builds the API with settings of its own and writes JSON in a fixed
form. A test sets the environment differently and expects the same document.

**Types are a compile-time promise.** They vanish when the code is built: nothing in the browser
checks that an answer has the shape the types say. That is acceptable for an API that validates
every answer against its own model before sending it, as FastAPI does. For an API you do not
control, parse the answer at the boundary (with zod, say) and trust only what passes.

**Absent and null are different.** In TypeScript `line?: number | null` may be missing or `null`;
`line: number | null` is always there. OpenAPI says which with `required`, and Pydantic marks a
field that has a default as not required, so its type is optional even when the API always sends
it. Read the generated type before assuming a field is there.

**Types, not a client.** The generator also writes the paths and their parameters. A generated
client would use them to write each request too, but it brings its own request function, beside
the one that limits the time, names errors and refreshes the token. The pages use the schemas
alone, and each call's path is checked by its tests.

The question to ask of anything described in two places: which one is the source, and what fails
when the other one is not its copy?
