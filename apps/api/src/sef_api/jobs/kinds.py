"""What each kind of job does: the handler that runs it, wherever jobs are run."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from sef_api.invoices.revalidation import revalidate
from sef_api.jobs.runs import Handler
from sef_api.models import JobKind

__all__ = ["HANDLERS"]

HANDLERS: Final[Mapping[str, Handler]] = MappingProxyType({JobKind.REVALIDATION: revalidate})
