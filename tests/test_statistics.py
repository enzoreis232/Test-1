from datetime import datetime, timedelta, timezone

import pytest

from bacbo_analytics.analysis import SimulationEngine, StatisticalAnalysisEngine
from bacbo_analytics.analysis.common import NO_EVIDENCE, THEORETICAL, holm, wilson


def test_theoretical_counts_exact():
    assert THEORETICAL["P"] == 575 / 1296
    assert THEORETICAL["B"] == 575 / 1296
    assert THEORETICAL["T"] == 146 / 1296
    assert sum(THEORETICAL.values()) == 1


def test_small_sample_does_not_assert_significance():
    report = StatisticalAnalysisEngine().analyze(list("PPPP"))
    assert report["independence"]["p_value"] is None
    assert report["goodness_of_fit"]["p_value"] is None
    assert report["conclusion"] == NO_EVIDENCE


def test_random_history_not_declared_predictable():
    values = [r for r, _ in SimulationEngine(51).generate(1500)]
    report = StatisticalAnalysisEngine().analyze(values)
    assert report["conclusion"] == NO_EVIDENCE
    assert sum(report["frequencies"].values()) == 1500
    assert sum(report["relative"].values()) == pytest.approx(1)
    assert report["independence"]["p_value"] is not None


def test_periodic_sequence_dependency_detected_without_prediction_claim():
    report = StatisticalAnalysisEngine().analyze(list("PBT" * 100))
    assert report["independence"]["adjusted_p_value"] <= 0.05
    assert report["conclusion"] == NO_EVIDENCE


def test_counts_intervals_entropy():
    report = StatisticalAnalysisEngine().analyze(list("PPBBTT"))
    assert report["entropy"] == pytest.approx(1.584962500721156)
    lower, upper = report["confidence_intervals"]["T"]
    assert 0 <= lower < 1 / 3 < upper <= 1
    assert wilson(0, 0) is None


def test_holm_adjustment():
    assert holm({"a": 0.01, "b": 0.03, "c": 0.04}) == {"a": 0.03, "b": 0.06, "c": 0.06}


def test_time_groups_are_corrected_with_other_tests():
    values = [r for r, _ in SimulationEngine(51).generate(180)]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = [(start + timedelta(minutes=5 * n)).isoformat() for n in range(180)]
    report = StatisticalAnalysisEngine().analyze(values, times)
    assert "hour" in report["time_groups"]
    assert report["multiple_comparisons"]["family_size"] >= 3
    assert report["time_groups"]["hour"]["n"] == len(values)


def test_timestamp_mismatch_raises():
    with pytest.raises(ValueError):
        StatisticalAnalysisEngine().analyze(["P"], [])


def test_compare_samples_insufficient_and_strong_difference():
    engine = StatisticalAnalysisEngine()
    assert engine.compare_samples(["P"], ["B"])["p_value"] is None
    assert engine.compare_samples(["P"] * 100, ["B"] * 100)["p_value"] <= 0.01
