"""The rate limiter on its own: bursts, pace, the time to wait, rules counted together, and the
memory it keeps."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from sef_api.rate_limits import Limit, RateLimiter, Rule

SECOND = 1_000_000_000


class Clock:
    """A monotonic clock that the test moves by hand, in nanoseconds."""

    def __init__(self) -> None:
        self.now = 1_000 * SECOND

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += round(seconds * SECOND)


@pytest.fixture
def clock() -> Clock:
    return Clock()


def three_in_thirty_seconds(key: str = "203.0.113.7", name: str = "sign-in") -> Rule:
    return Rule(name, key, Limit(3, timedelta(seconds=30)))


def test_a_limit_allows_its_count_at_once_then_one_per_interval(clock: Clock) -> None:
    limiter, rule = RateLimiter(clock=clock), three_in_thirty_seconds()

    assert [limiter.hit(rule) for _ in range(3)] == [0, 0, 0]
    assert limiter.hit(rule) == pytest.approx(10)
    clock.advance(9.9)
    assert limiter.hit(rule) == pytest.approx(0.1)
    clock.advance(0.1)
    assert limiter.hit(rule) == 0
    assert limiter.hit(rule) == pytest.approx(10)


def test_after_a_quiet_period_the_whole_burst_is_back_and_no_more(clock: Clock) -> None:
    limiter, rule = RateLimiter(clock=clock), three_in_thirty_seconds()
    for _ in range(3):
        limiter.hit(rule)

    clock.advance(300)

    assert [limiter.hit(rule) for _ in range(4)] == [0, 0, 0, pytest.approx(10)]


def test_requests_at_the_limits_pace_are_never_refused(clock: Clock) -> None:
    """Seven a minute is an interval that no float divides exactly; integers lose nothing."""
    limiter, rule = RateLimiter(clock=clock), Rule("refresh", "ana", Limit(7, timedelta(minutes=1)))
    for _ in range(7):
        limiter.hit(rule)

    refused = []
    for _ in range(1000):
        clock.now += rule.limit.interval
        refused.append(limiter.hit(rule))

    assert set(refused) == {0}


def test_names_and_keys_are_counted_apart(clock: Clock) -> None:
    limiter = RateLimiter(clock=clock)
    for _ in range(3):
        limiter.hit(three_in_thirty_seconds())

    assert limiter.hit(three_in_thirty_seconds()) > 0
    assert limiter.hit(three_in_thirty_seconds(key="198.51.100.4")) == 0
    assert limiter.hit(three_in_thirty_seconds(name="registration")) == 0


def test_waiting_counts_nothing(clock: Clock) -> None:
    limiter, rule = RateLimiter(clock=clock), three_in_thirty_seconds()

    assert [limiter.wait(rule) for _ in range(10)] == [0] * 10
    assert [limiter.hit(rule) for _ in range(3)] == [0, 0, 0]
    assert limiter.wait(rule) == pytest.approx(10)


def test_rules_counted_together_count_only_when_all_of_them_allow(clock: Clock) -> None:
    limiter = RateLimiter(clock=clock)
    caller = Rule("validation", "ana", Limit(1, timedelta(minutes=1)))
    organization = Rule("organization validation", "primer", Limit(10, timedelta(minutes=1)))

    assert limiter.hit(caller, organization) == 0
    assert limiter.hit(caller, organization) == pytest.approx(60)

    assert [limiter.hit(organization) for _ in range(10)] == [0] * 9 + [pytest.approx(6)]


def test_forgetting_a_rule_starts_its_count_afresh(clock: Clock) -> None:
    limiter, rule = RateLimiter(clock=clock), three_in_thirty_seconds()
    for _ in range(3):
        limiter.hit(rule)

    limiter.forget(rule)

    assert [limiter.hit(rule) for _ in range(3)] == [0, 0, 0]


@pytest.mark.parametrize(
    ("count", "period"),
    [(0, timedelta(minutes=1)), (1, timedelta(0)), (1, timedelta(seconds=-1))],
)
def test_a_limit_allows_at_least_one_request_in_a_positive_period(
    count: int, period: timedelta
) -> None:
    with pytest.raises(ValueError, match="at least one request"):
        Limit(count, period)


def test_the_limiter_keeps_its_capacity_of_keys_and_the_ones_it_holds_back(clock: Clock) -> None:
    limiter = RateLimiter(clock=clock, capacity=10)
    held = Rule("sign-in", "203.0.113.7", Limit(1, timedelta(hours=1)))
    limiter.hit(held)

    for n in range(50):
        limiter.hit(Rule("sign-in", f"198.51.100.{n}", Limit(100, timedelta(seconds=1))))

    assert len(limiter) <= 10
    assert limiter.wait(held) > 0


def test_keys_whose_count_has_run_out_are_dropped_first(clock: Clock) -> None:
    limiter = RateLimiter(clock=clock, capacity=10)
    for n in range(10):
        limiter.hit(Rule("sign-in", f"198.51.100.{n}", Limit(1, timedelta(seconds=1))))
    clock.advance(1)

    limiter.hit(Rule("sign-in", "203.0.113.7", Limit(1, timedelta(seconds=1))))

    assert len(limiter) == 1


class Hesitant(Limit):
    """A limit whose arithmetic lets other threads run in the middle of a check."""

    @property
    def tolerance(self) -> int:
        time.sleep(0.0001)
        return super().tolerance


def test_threads_never_count_past_a_limit() -> None:
    limiter = RateLimiter()
    rule = Rule("validation", "ana", Hesitant(50, timedelta(hours=1)))

    with ThreadPoolExecutor(max_workers=8) as pool:
        waits = list(pool.map(lambda _: limiter.hit(rule), range(400)))

    assert waits.count(0) == 50
