"""Invoices in the API: validating them with the deterministic validator (ADR-0015), and
keeping them for an organization (ADR-0016).

The validator is ``einvoice_core``. The API reads the document within its limits, runs the
validator in a child process and returns the validator's own report; a stored invoice keeps
the document and that report. The API never logs a document's content.
"""
