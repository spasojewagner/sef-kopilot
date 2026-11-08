"""Unexpected errors reported to Sentry, where the operator gives a DSN, and nothing more
(ADR-0048).

Without ``SENTRY_DSN`` nothing is sent anywhere: a self-hosted deployment calls out to
nothing it did not choose. With it, an exception that no handler answered, in the API or in a
worker, and a line logged at error, are reported with what says where they happened (the
exception's type, its stack of files, functions and lines, the route, the release) and nothing
a person sent: no request body, headers, cookies or query, no variables of the frames, no
breadcrumbs, no user, and not the exception's message, which may quote what it was given. No
traces of performance are taken.
"""

from __future__ import annotations

import logging
from typing import Any, Final, cast
from urllib.parse import urlsplit

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.transport import Transport
from sentry_sdk.types import Event, Hint

from sef_api import __version__
from sef_api.settings import Settings

__all__ = ["RELEASE", "scrubbed", "track_errors"]

#: The release an error is reported under.
RELEASE: Final = f"sef-kopilot-api@{__version__}"
#: What an exception's message is replaced with.
_UNSAID: Final = "(the message is not sent: it may quote what the API was given)"


def track_errors(settings: Settings, *, transport: Transport | None = None) -> bool:
    """Report unexpected errors to the Sentry project of ``SENTRY_DSN``, if it is set;
    whether they are. ``transport`` replaces the network, for tests."""
    if settings.sentry_dsn is None:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.environment,
        release=RELEASE,
        # Every category of what a person sent, off; the lines of code around a frame stay.
        data_collection={
            "user_info": False,
            "cookies": {"mode": "off"},
            "http_headers": {"request": {"mode": "off"}},
            "url_query_params": {"mode": "off"},
            "http_bodies": [],
            "gen_ai": {"inputs": False, "outputs": False},
            "graphql": {"document": False, "variables": False},
            "database_query_data": False,
            "queues": False,
            "stack_frame_variables": False,
        },
        max_breadcrumbs=0,
        traces_sample_rate=None,
        # A line logged at error is reported; no line becomes a breadcrumb.
        integrations=[LoggingIntegration(level=None, event_level=logging.ERROR)],
        before_send=scrubbed,
        transport=transport,
    )
    return True


def scrubbed(sent: Event, hint: Hint) -> Event:
    """``sent`` with nothing a person sent, whatever an integration put in it: the request as
    its method and path, no user, breadcrumbs or extra data, and exceptions and log lines
    without their words or the frames' variables."""
    del hint
    event = cast(dict[str, Any], sent)
    request = event.get("request")
    if isinstance(request, dict):
        event["request"] = {
            "method": request.get("method"),
            "url": _path_of(request.get("url")),
        }
    for unsent in ("user", "breadcrumbs", "extra"):
        event.pop(unsent, None)
    for exception in (event.get("exception") or {}).get("values") or []:
        exception["value"] = _UNSAID
        for frame in (exception.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        # The line as written in the code, without what it was given.
        event["logentry"] = {"message": logentry.get("message")}
    return sent


def _path_of(url: object) -> str | None:
    """``url`` without its query or fragment."""
    if not isinstance(url, str):
        return None
    parts = urlsplit(url)
    return parts._replace(query="", fragment="").geturl()
