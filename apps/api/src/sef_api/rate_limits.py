"""Rate limits: how often a client may do something, counted in the API's process (ADR-0018).

A limit allows ``count`` requests per ``period``, at once or spread out, as a token bucket of
``count`` tokens refilled over ``period`` would. The algorithm is GCRA, the generic cell rate
algorithm. Per key it keeps a single moment, the *theoretical arrival time* (TAT) of the next
request were requests evenly spaced, and it allows a request while that moment is no further
ahead than the burst may reach. It needs no timer and no list of past requests, and the time
to wait comes out of the same arithmetic::

    interval T = period / count          tolerance τ = period - T
    tat = max(tat, now)                  allowed when tat - now ≤ τ, and then tat = tat + T
                                         otherwise wait tat - τ - now

Times are integer nanoseconds of a monotonic clock, so that no rounding refuses a request the
limit allows. The counts live in the process, as the validator's admission does (ADR-0015):
behind several workers each would count its own. A shared store can take them over behind
the same methods.

What the API counts is :class:`Counted`, and :func:`limits` says against which limit. A
request beyond a limit answers 429 with ``Retry-After``.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from functools import cache
from types import MappingProxyType
from typing import Final, cast

from fastapi import HTTPException, Request, status

from sef_api.settings import Settings

__all__ = [
    "DEFAULT_LIMITS",
    "Counted",
    "Limit",
    "PasswordAttempts",
    "RateLimiter",
    "Rule",
    "client_address",
    "limits",
    "per_address",
    "too_many",
]

_NANOSECONDS: Final = 1_000_000_000


@dataclass(frozen=True)
class Limit:
    """At most ``count`` requests per ``period``: in a burst, or one every ``period / count``."""

    count: int
    period: timedelta

    def __post_init__(self) -> None:
        if self.count < 1 or self.period <= timedelta(0):
            raise ValueError("a limit allows at least one request in a positive period")

    @property
    def interval(self) -> int:
        """Nanoseconds between requests spread evenly over the period."""
        return self._period // self.count

    @property
    def tolerance(self) -> int:
        """Nanoseconds by which the next arrival may run ahead of now: what makes a burst."""
        return self._period - self.interval

    @property
    def _period(self) -> int:
        return round(self.period.total_seconds() * _NANOSECONDS)


@dataclass(frozen=True)
class Rule:
    """A limit and what it counts: requests named ``name``, for one ``key``."""

    name: str
    key: str
    limit: Limit


class RateLimiter:
    """Counts requests against rules, per name and key, in the process's memory.

    Every method holds a lock, so that a check and the count that follows it are one step for
    whichever thread or task calls them.
    """

    #: The most keys kept by default. Beyond it, the keys whose counts have run out go first.
    DEFAULT_CAPACITY: Final = 100_000

    def __init__(
        self,
        *,
        clock: Callable[[], int] = time.monotonic_ns,
        capacity: int = DEFAULT_CAPACITY,
    ) -> None:
        self._clock = clock
        self._capacity = capacity
        self._arrivals: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def wait(self, *rules: Rule) -> float:
        """Seconds until every rule allows one more request, 0 when they all do now. It counts
        nothing."""
        with self._lock:
            return self._wait(rules, self._clock()) / _NANOSECONDS

    def hit(self, *rules: Rule) -> float:
        """Count one request against every rule and return 0 when all of them allow it;
        otherwise count nothing and return the seconds to wait."""
        with self._lock:
            now = self._clock()
            waiting = self._wait(rules, now)
            if waiting > 0:
                return waiting / _NANOSECONDS
            for rule in rules:
                key = (rule.name, rule.key)
                self._arrivals[key] = max(self._arrivals.get(key, now), now) + rule.limit.interval
            self._evict(now)
            return 0.0

    def forget(self, *rules: Rule) -> None:
        """Start the count of every rule afresh."""
        with self._lock:
            for rule in rules:
                self._arrivals.pop((rule.name, rule.key), None)

    def __len__(self) -> int:
        """How many keys the limiter holds a count for."""
        return len(self._arrivals)

    def _wait(self, rules: tuple[Rule, ...], now: int) -> int:
        """Nanoseconds until every rule allows a request; 0 when they all do now."""
        return max(
            0,
            *(
                max(self._arrivals.get((rule.name, rule.key), now), now)
                - rule.limit.tolerance
                - now
                for rule in rules
            ),
        )

    def _evict(self, now: int) -> None:
        """Keep at most the capacity of keys. A key whose arrival time has passed counts as
        nothing and goes first; beyond those, the keys nearest to running out go, so that the
        ones being held back now are kept."""
        if len(self._arrivals) <= self._capacity:
            return
        live = {key: arrival for key, arrival in self._arrivals.items() if arrival > now}
        if len(live) > self._capacity:
            kept = sorted(live.items(), key=lambda item: item[1], reverse=True)
            live = dict(kept[: self._capacity * 9 // 10])
        self._arrivals = live


class Counted(StrEnum):
    """What the API counts against a limit, as an answer of 429 names it."""

    SIGN_IN = "sign-in attempts"
    REGISTRATION = "registrations"
    REFRESH = "refresh-token requests"
    INVITATION = "attempts to accept an invitation"
    FAILED_PASSWORD = "failed passwords for this e-mail address"
    VALIDATION = "validations"
    ORGANIZATION_VALIDATION = "validations in this organization"
    MODEL_REQUEST = "requests to the language model"
    ORGANIZATION_MODEL_REQUEST = "requests to the language model in this organization"
    CLIENT_REGISTRATION = "registrations of OAuth clients"
    TOKEN_REQUEST = "requests for OAuth tokens"
    AUTHORIZATION_REQUEST = "OAuth authorization requests"


#: The limits that settings do not change. Per address: what one client may try, generous
#: enough for an office of people behind one address. Per e-mail address: the passwords that
#: may be wrong, from wherever they come, which is what stops a guess at one account.
DEFAULT_LIMITS: Final[Mapping[Counted, Limit]] = MappingProxyType(
    {
        Counted.SIGN_IN: Limit(30, timedelta(minutes=1)),
        Counted.REGISTRATION: Limit(10, timedelta(hours=1)),
        Counted.REFRESH: Limit(60, timedelta(minutes=1)),
        Counted.INVITATION: Limit(10, timedelta(minutes=1)),
        Counted.FAILED_PASSWORD: Limit(10, timedelta(minutes=15)),
        Counted.CLIENT_REGISTRATION: Limit(10, timedelta(hours=1)),
        Counted.TOKEN_REQUEST: Limit(60, timedelta(minutes=1)),
        # Each may make the server fetch a client's metadata document (ADR-0045).
        Counted.AUTHORIZATION_REQUEST: Limit(30, timedelta(minutes=1)),
    }
)


def limits(settings: Settings) -> Mapping[Counted, Limit]:
    """Every limit the API counts against: :data:`DEFAULT_LIMITS`, and the validations and the
    requests to the language model (for explanations or a repair) a minute that the settings
    allow one caller and one organization."""
    minute = timedelta(minutes=1)
    return MappingProxyType(
        {
            **DEFAULT_LIMITS,
            Counted.VALIDATION: Limit(settings.validations_per_minute, minute),
            Counted.ORGANIZATION_VALIDATION: Limit(
                settings.organization_validations_per_minute, minute
            ),
            Counted.MODEL_REQUEST: Limit(settings.explanations_per_minute, minute),
            Counted.ORGANIZATION_MODEL_REQUEST: Limit(
                settings.organization_explanations_per_minute, minute
            ),
        }
    )


@dataclass(frozen=True)
class PasswordAttempts:
    """The failed password checks of each e-mail address, against one limit. An address that
    no account has is counted like any other, so that being held back reveals nothing."""

    limiter: RateLimiter
    limit: Limit

    def wait(self, email: str) -> float:
        """Seconds until a password for ``email`` may be checked again; 0 when it may now."""
        return self.limiter.wait(self._rule(email))

    def failed(self, email: str) -> None:
        self.limiter.hit(self._rule(email))

    def passed(self, email: str) -> None:
        """The right password starts the count afresh."""
        self.limiter.forget(self._rule(email))

    def _rule(self, email: str) -> Rule:
        return Rule(Counted.FAILED_PASSWORD, email, self.limit)


def client_address(request: Request) -> str:
    """The address the request came from, as the server saw it. Behind a proxy it is the one
    the server was told to trust (uvicorn's ``--forwarded-allow-ips``), never a header the
    client wrote."""
    return request.client.host if request.client is not None else "unknown"


def too_many(counted: Counted, wait: float) -> HTTPException:
    """429 for a request beyond the limit of ``counted``, with the whole seconds to wait."""
    seconds = max(1, math.ceil(wait))
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        f"too many {counted}; try again in {seconds} s",
        headers={"Retry-After": str(seconds)},
    )


def per_address(counted: Counted) -> Callable[[Request], None]:
    """A dependency that counts the request against the application's limit of ``counted``,
    by the address it came from, and answers 429 beyond it."""
    return _per_address(counted)


@cache
def _per_address(counted: Counted) -> Callable[[Request], None]:
    def count(request: Request) -> None:
        limiter = cast(RateLimiter, request.app.state.limiter)
        limits = cast(Mapping[Counted, Limit], request.app.state.limits)
        wait = limiter.hit(Rule(counted, client_address(request), limits[counted]))
        if wait > 0:
            raise too_many(counted, wait)

    return count
