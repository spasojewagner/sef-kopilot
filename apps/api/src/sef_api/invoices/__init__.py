"""Invoices in the API: validating them with the deterministic validator (ADR-0014).

The validator is ``einvoice_core``. The API reads the document within its limits, runs the
validator off the event loop and returns the validator's own report; it never logs a
document's content.
"""
