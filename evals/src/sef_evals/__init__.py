"""Evaluations of SEF Kopilot (ADR-0054).

``sef_evals`` measures the system on golden sets and judges the measures against the
thresholds in ``evals/thresholds.yaml``: whether the validator's verdicts agree with the
reference composition of the published rule sets, whether it rejects every document that must
be rejected, and for the right reason. ``sef-evals`` runs them, writes the report in
``evals/reports/`` and, with ``--check``, fails when a threshold is not met or the committed
report is not what the run gives.
"""

__all__ = ["__version__"]

# Kept in sync with ``pyproject.toml`` by ``tests/test_package.py``.
__version__ = "0.6.0"
