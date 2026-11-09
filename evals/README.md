# Evaluations

How well SEF Kopilot does its job, measured on golden sets: the workspace package
`sef-kopilot-evals` (`sef_evals`).

## The golden set of documents

[`golden/documents.yaml`](golden/documents.yaml) names every document of the corpus
(`fixtures/invoices/`, and the examples CEN/TC 434 and OpenPeppol publish), in groups, with the
profile each is judged by, whether it must be accepted or rejected, and the rules that must be
among those reported. The labels come from the documents' publishers and from the mistakes the
mutations were made to have, never from what the validator answered.
