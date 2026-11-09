"""Measures, their thresholds and the judgement of one by the other."""

from __future__ import annotations

from pathlib import Path

import pytest

from sef_evals.measures import Measure
from sef_evals.thresholds import Threshold, ThresholdError, judge, load_thresholds


def share(name: str, total: int, *failures: str) -> Measure:
    return Measure(name=name, title=name, kind="share", total=total, failures=failures)


def rate(name: str, total: int, *failures: str) -> Measure:
    return Measure(name=name, title=name, kind="rate", total=total, failures=failures)


def test_a_share_counts_what_passed_and_a_rate_what_failed() -> None:
    assert share("agreement", 4, "one").value == 0.75
    assert rate("false_accept_rate", 4, "one").value == 0.25
    assert share("agreement", 4).passed == 4
    assert share("agreement", 0).value is None


def test_a_measure_has_no_more_failures_than_cases() -> None:
    with pytest.raises(ValueError, match="2 failures of 1 cases"):
        share("agreement", 1, "one", "two")


def test_a_threshold_is_a_minimum_or_a_maximum() -> None:
    assert Threshold(min=0.8).met_by(0.8)
    assert not Threshold(min=0.8).met_by(0.79)
    assert Threshold(max=0.0).met_by(0.0)
    assert not Threshold(max=0.0).met_by(0.01)
    assert str(Threshold(min=0.9)) == "≥ 90%"
    assert str(Threshold(max=0.0)) == "≤ 0%"
    for wrong in ({}, {"min": 1.0, "max": 0.0}):
        with pytest.raises(ValueError, match="either min or max"):
            Threshold.model_validate(wrong)
    with pytest.raises(ValueError, match="less than or equal to 1"):
        Threshold(min=80)


def test_judges_each_measure_and_misses_none_of_the_thresholds() -> None:
    thresholds = {
        "agreement": Threshold(min=1.0),
        "false_accept_rate": Threshold(max=0.0),
        "repair_success": Threshold(min=0.8),
    }
    judged = judge(
        [
            share("agreement", 3),
            rate("false_accept_rate", 2, "accepted"),
            share("coverage", 5, "missing"),
        ],
        thresholds,
    )
    assert [(j.name, j.met) for j in judged] == [
        ("agreement", True),
        ("false_accept_rate", False),
        ("coverage", None),  # no threshold: reported, not judged
        ("repair_success", False),  # a threshold whose measure was not taken is not met
    ]
    assert judged[3].measure is None


def test_a_measure_without_cases_does_not_meet_its_threshold() -> None:
    (judged,) = judge([share("detection", 0)], {"detection": Threshold(min=1.0)})
    assert judged.met is False


def test_loads_the_repository_thresholds(tmp_path: Path) -> None:
    path = tmp_path / "thresholds.yaml"
    path.write_text("# a comment\nagreement: {min: 1.0}\nfalse_accept_rate: {max: 0}\n")
    assert load_thresholds(path) == {
        "agreement": Threshold(min=1.0),
        "false_accept_rate": Threshold(max=0.0),
    }


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("agreement: {min: 1.0, max: 1.0}\n", "either min or max"),
        ("agreement: {at_least: 1.0}\n", "at_least"),
        ("agreement: 1.0\n", "agreement"),
        ("- agreement\n", "thresholds.yaml"),
        ("agreement: {min: [1\n", "thresholds.yaml"),
    ],
)
def test_refuses_thresholds_it_cannot_read(tmp_path: Path, text: str, problem: str) -> None:
    path = tmp_path / "thresholds.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ThresholdError, match=problem):
        load_thresholds(path)
