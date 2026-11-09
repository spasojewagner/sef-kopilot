"""Evaluations of SEF Kopilot.

``sef_evals`` measures the system on golden sets: what each document of the corpus must get
from the validator, labelled apart from it (``evals/golden/``), and whether its verdicts agree
with the reference composition of the published rule sets.
"""

__all__ = ["__version__"]

# Kept in sync with ``pyproject.toml`` by ``tests/test_package.py``.
__version__ = "0.5.0"
