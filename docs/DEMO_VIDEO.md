# The 90-second demo video: script

A screen recording with a voice-over, for the README, a CV and a talk. It shows the golden path
on a synthetic invoice, then the two things a GIF cannot: an explanation that cites the
regulation, and an assistant using the MCP server. About 210 words, read at a calm pace.

## Before recording

- **Where:** the public demo (`docs/DEPLOY.md`), or a local run with a model of your own
  (`LLM_PROVIDER` and its key in `.env`, then `make up`, `make migrate`, `make ingest`,
  `make api`, `make web`). The explanation needs the corpus loaded and a model; the rest does
  not.
- **Invoices, synthetic only:**
  [`srb-001-invoice-type-code.xml`](../fixtures/invoices/synthetic/mutations/srb-001-invoice-type-code.xml)
  for the repair (its type code, 393, is one SEF does not accept), and a photograph from
  [`evals/golden/documents/`](../evals/golden/documents/) for the reading.
- **The screen:** a browser window of 1280 by 720, the page at 100 %, the interface in English,
  an account made beforehand whose e-mail address can be shown, no other tab or bookmark in view.
  For the assistant, Claude connected to the server as [`DEMO.md`](DEMO.md) shows.
- **Nothing private:** no key, no `.env`, no real company's invoice, no notification on screen.

## The script

| Time | On screen | Voice-over |
| --- | --- | --- |
| 0:00–0:08 | The home page. | When SEF rejects an invoice, you get a rule identifier, like SRB-001. Then you start digging through the regulation. |
| 0:08–0:22 | **Check an invoice**: choose `srb-001-invoice-type-code.xml`, **Check and keep**. The report: *Invalid*, the layers of the check, SRB-001 at its place. | SEF Kopilot checks the invoice the way SEF does: the UBL schema, the European rules as CEN and Peppol publish them, and the Serbian rules, written in code. No language model decides what is valid. |
| 0:22–0:36 | **Explain the rules**. The explanation of SRB-001, its citation of SRB-CIUS with the dates it is in force. | A model explains each error, and it may cite only passages of the regulation the system retrieved, in force on the invoice's date. A citation that doesn't resolve is refused. |
| 0:36–0:54 | **Suggest a repair**: the patch 393 → 380 with its reason, the diff, *Report after the changes: Valid*. **Approve**, **Yes, approve**. | The model can suggest a repair, but only as patches. Code applies them to a copy, the validator checks it again, and a person approves the diff. Amounts, VAT and tax numbers are never changed by the model. |
| 0:54–1:00 | Back to the report: *Valid*. | Now it's valid, and every step is in the audit log. |
| 1:00–1:12 | The upload page with the photograph: the fields read beside the picture, one field corrected, **Make the invoice and check it**. | It also reads PDFs and photos into fields you check, in beta. The UBL is written by code from what you confirm. |
| 1:12–1:22 | Claude: asked to check the invoice, it calls `explain_errors`; its answer with the citations. | The same service is an MCP server with OAuth 2.1, so an accountant can ask Claude or ChatGPT, and an ERP can call the API. |
| 1:22–1:30 | The README's results table, then the repository's address. | It agrees with the published rule sets on every document of its test set, and CI fails if it ever stops. SEF Kopilot is open source. |

## After recording

- Cut to 90 seconds; keep the pauses where a page loads short, not out.
- Add captions from the voice-over: many viewers watch without sound.
- Export 1280 by 720, H.264. Add it to the README by dragging it into GitHub's editor, which
  hosts it, rather than committing it: the repository takes no file above 512 KB.
- The README's GIF (`docs/demo/golden-path.gif`) is not this video: `make demo-gif` records it,
  against the end-to-end test's API with a scripted model, and it shows no explanation.
