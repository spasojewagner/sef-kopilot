# M3 — `feat/web-demo-upload-notice`

## Three questions a senior engineer would ask

**1. "Why does the API say that it is the demo, rather than the web application's build?"**

Because the fact is about where the invoice goes. The API stores it and sends its violations and
fields to the model's provider; a web application only shows pages. With the flag on the API, any
client built against the demo's API learns the same, and the setting lives in `render.yaml`, in
the repository, instead of a variable typed into Vercel's dashboard. A self-hosted API leaves it
false, and its pages say nothing of the kind.

**2. "Isn't `/health` the liveness probe? Why put a setting in it?"**

It already says more than "up": the service and its version. `public_demo` is of the same kind,
static and read from the process's own settings, touching no dependency, so the probe stays as
cheap and as safe as before. And the pages already ask `/health` on every page for the footer,
so the upload reads the answer from the cache: no new endpoint, and no request more.

**3. "Could a visitor upload before the notice appears?"**

Hardly. The upload is reached only signed in, and signing in is itself an answer of the API, by
which time the footer's check has answered too. If the check failed, the page shows no note,
which is the accepted cost: the footer then says that the API does not answer, and the upload
would fail as well.

## The one concept to explain unaided

**The fact belongs to whoever holds the data.** Where an invoice is stored, and where it is
sent, is the server's to say; the pages only repeat it.

## Supporting facts worth remembering

- `SEF_PUBLIC_DEMO`, false by default; `render.yaml` sets it to `"true"`.
- `useQuery({ ...healthQuery, enabled: false })` reads the footer's answer and asks nothing.
- The note is a `role="note"` region above the form, with a link to
  `fixtures/invoices/synthetic` on GitHub.
