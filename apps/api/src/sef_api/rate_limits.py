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
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

__all__ = ["Limit", "RateLimiter", "Rule"]

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
