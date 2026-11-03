"""The SRB-CIUS rules, one per module.

A rule module is named ``srb_<number>_<subject>.py`` and defines ``RULE``, an instance of
:class:`einvoice_core.srb.rule.Rule` whose identifier is ``SRB-<number>``. Modules are found
by name, so adding a rule is adding a file (and its tests; a test fails for a rule without a
document that satisfies it and one that breaks it).
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from typing import Final

from einvoice_core.srb.rule import Rule

__all__ = ["load_rules"]

_MODULE: Final = re.compile(r"srb_(?P<number>\d{3})_[a-z0-9_]+")


def load_rules() -> tuple[Rule, ...]:
    """Import every rule module and return their rules in identifier order.

    Raises :class:`TypeError` for a rule module without a ``RULE``, and :class:`ValueError`
    when a rule's identifier does not match its module name.
    """
    rules = []
    for info in pkgutil.iter_modules(__path__):
        match = _MODULE.fullmatch(info.name)
        if match is None:
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        rule = getattr(module, "RULE", None)
        if not isinstance(rule, Rule):
            raise TypeError(f"{module.__name__} does not define RULE as an SRB-CIUS Rule")
        if rule.id != f"SRB-{match['number']}":
            raise ValueError(f"{module.__name__} defines {rule.id}, expected SRB-{match['number']}")
        rules.append(rule)
    return tuple(sorted(rules, key=lambda rule: rule.id))
