"""Which language model writes for an organization: its own, with the key it set (ADR-0058), or
the server's.

An organization that set a key to a provider is answered by that provider's model, for every
explanation and repair its members, keys and MCP clients ask for: a client is made for the
request from the sealed key and closed after it, traced as the server's model is where
Langfuse's keys are set. An organization without one is answered by the server's model, if the
server has one.

An organization's own key that cannot be opened (``SEF_FERNET_KEY`` no longer holds the key
that sealed it) answers 503: its invoices are never sent to the server's model instead, which
the organization did not choose.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.llm import LLMClient, client_for
from sef_api.model_traces import ModelTraces, TracedClient
from sef_api.organization import service
from sef_api.rag.explainer import Explainer
from sef_api.repairs.repairer import Repairer
from sef_api.sef.keys import Keyring, UnreadableKeyError

__all__ = ["explainer_for", "repairer_for"]


async def _own_model(
    request: Request, session: AsyncSession, organization_id: uuid.UUID
) -> LLMClient | None:
    """The organization's own model, for this request; None when it set no key."""
    stored = await service.model_key(session, organization_id)
    if stored is None:
        return None
    keyring = cast(Keyring | None, request.app.state.sef_keys)
    try:
        if keyring is None:
            raise UnreadableKeyError("SEF_FERNET_KEY is not set")
        api_key = keyring.open(organization_id, stored.token, "model")
    except UnreadableKeyError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the organization's key to its model cannot be opened on this server: an owner sets "
            "it again",
        ) from None
    client = client_for(stored.provider, api_key, stored.model)
    if client is None:  # pragma: no cover - the table holds only the providers there are
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "unknown model provider")
    traces = cast(ModelTraces | None, request.app.state.model_traces)
    return TracedClient(client, traces, owns_traces=False) if traces is not None else client


@asynccontextmanager
async def explainer_for(
    request: Request, session: AsyncSession, organization_id: uuid.UUID
) -> AsyncIterator[Explainer | None]:
    """The explainer that writes for the organization: with its own model, or the server's;
    None when there is neither."""
    own = await _own_model(request, session, organization_id)
    if own is None:
        yield cast(Explainer | None, request.app.state.explainer)
        return
    try:
        yield Explainer(own)
    finally:
        await own.aclose()


@asynccontextmanager
async def repairer_for(
    request: Request, session: AsyncSession, organization_id: uuid.UUID
) -> AsyncIterator[Repairer | None]:
    """The repairer that writes for the organization: with its own model, or the server's;
    None when there is neither."""
    own = await _own_model(request, session, organization_id)
    if own is None:
        yield cast(Repairer | None, request.app.state.repairer)
        return
    try:
        yield Repairer(own)
    finally:
        await own.aclose()
