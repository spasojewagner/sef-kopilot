"""Deterministic validation engine for UBL 2.1 electronic invoices.

``einvoice_core`` validates an invoice against XSD schemas, the EN 16931 and Peppol BIS
Billing 3.0 Schematron rule sets and the Serbian SRB-CIUS profile, and reports violations
as structured data. It never calls a language model: it is the source of truth that the rest
of SEF Kopilot builds on (see ``docs/adr/0002-deterministic-validator-is-the-source-of-truth.md``).

The package is pure Python with no I/O side effects beyond reading the files it is given, so
it can run inside the API, in a command-line tool, in tests and in evaluation harnesses alike.
"""

__all__ = ["__version__"]

# Kept in sync with ``pyproject.toml`` by ``tests/test_package.py``.
__version__ = "0.4.0"
