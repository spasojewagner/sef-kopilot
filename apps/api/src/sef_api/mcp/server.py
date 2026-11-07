"""The MCP server and its endpoint, ``/mcp`` (ADR-0042).

The server lives in the API's process and answers over Streamable HTTP without sessions: each
message is a POST answered with JSON, so any instance answers any message, a restart loses
nothing, and a client of an earlier revision of the protocol is answered too. The endpoint is a
route of the API's application, behind its middleware (the limit on bodies, the answers to
unexpected failures), and :class:`~sef_api.mcp.access.RequireCredential` admits callers in front
of the server as the routes' dependencies do.
"""

from __future__ import annotations

import logging
from typing import Final

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.routing import Route

from sef_api import __version__
from sef_api.mcp import tools
from sef_api.mcp.access import RequireCredential
from sef_api.settings import Settings

__all__ = ["INSTRUCTIONS", "PATH", "mount"]

#: Where the endpoint is.
PATH: Final = "/mcp"

#: What a client's model is told about the server as it connects.
INSTRUCTIONS: Final = (
    "SEF Kopilot checks electronic invoices for Serbia's e-invoicing system (SEF): UBL 2.1 "
    "invoices and credit notes, against SRB-CIUS, the profile SEF uses, against EN 16931 and "
    "against Peppol BIS Billing 3.0. Its rule sets decide whether an invoice is valid, never a "
    "language model: report what its tools answer, and do not judge an invoice's validity "
    "yourself. SEF Kopilot is not a certified validator."
)


def mount(app: FastAPI, settings: Settings) -> StreamableHTTPSessionManager:
    """Add the MCP endpoint to ``app``; the session manager that answers it, which runs for as
    long as the application does (``run()``, in its lifespan)."""
    server = _server()
    tools.register(server)
    server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        max_request_body_size=settings.max_body_bytes,
        # The SDK's guard against DNS rebinding checks the Host header against a list of hosts,
        # which a server behind a platform's proxy does not know. RequireCredential checks the
        # origin of a page instead, and every request needs a credential, which a page cannot send
        # unasked.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    manager = server.session_manager
    app.router.routes.append(
        Route(PATH, RequireCredential(manager.handle_request, origins=settings.web_origins))
    )
    return manager


def _server() -> MCPServer:
    """The server, with the root logger as it was: the SDK configures it when a server is made
    (``logging.basicConfig``), and the process's logging is not a library's to decide."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    server = MCPServer(name="SEF Kopilot", instructions=INSTRUCTIONS, version=__version__)
    root.handlers[:] = handlers
    root.setLevel(level)
    return server
