"""Invoices read from PDFs and pictures (ADR-0062, beta).

A document (:mod:`~sef_api.extraction.documents`) is opened into pages; the reading model
(:mod:`~sef_api.extraction.reader`) reads them into an invoice's fields
(:mod:`~sef_api.extraction.fields`); a person confirms the fields; and code writes the UBL
invoice they describe (:mod:`~sef_api.extraction.draft`), which the validator then judges as
any other. The model sits between the person who confirms and the validator that judges, and
is trusted by neither.
"""
