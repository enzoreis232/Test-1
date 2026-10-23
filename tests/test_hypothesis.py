from bacbo_analytics.analysis import HypothesisEvaluationEngine, SimulationEngine
from bacbo_analytics.analysis.common import NO_EVIDENCE
from unittest.mock import patch


def test_partitions_disjoint_and_chronological():
    report = HypothesisEvaluationEngine().evaluate(list("PBT" * 10))
    a, b, c = (report["partitions"][name] for name in ("development", "validation", "test"))
    assert a["end"] == b["start"]
    assert b["end"] == c["start"]
    assert a["start"] == 0 and c["end"] == 30


def test_no_future_leakage_and_tie_is_not_a_success():
    engine = HypothesisEvaluationEngine()
    report = engine.evaluate(list("PPPPT"))
    hypothesis = report["hypotheses"]["surf_continuation"]
    assert hypothesis["test"]["n"] == 1
    assert hypothesis["test"]["successes"] == 0


def test_monte_carlo_detector_matches_observed_detector():
    engine = HypothesisEvaluationEngine()
    values = list("PPPPPBTBPBPBPTTTBBBBB")
    direct = engine.evaluate(values)
    efficient = engine._events(values)
    for name, events in efficient.items():
        observed = direct["hypotheses"][name]
        assert sum(part["n"] for part in observed.values()) == len(events)
        assert sum(part["successes"] for part in observed.values()) == sum(ok for _, ok in events)


def test_coincidental_patterns_not_claimed_as_predictive():
    values = [r for r, _ in SimulationEngine(11).generate(1000)]
    report = HypothesisEvaluationEngine().evaluate(values)
    assert report["status"] == NO_EVIDENCE
    assert not report["replicated"]


def test_empty_eligible_family_does_not_run_null_simulations():
    engine = HypothesisEvaluationEngine()
    # Sem gatilhos nem amostras elegíveis: nenhuma sequência nula deve ser gerada.
    with patch.object(engine, "_events", side_effect=AssertionError("simulação desnecessária")):
        report = engine.evaluate(list("PBT" * 300))
    assert report["multiple_comparisons"]["adjusted_p_values"] == {}
    assert report["multiple_comparisons"]["family_size"] == 4


def test_overlapping_trigger_intervals_explicitly_have_no_nominal_coverage():
    report = HypothesisEvaluationEngine().evaluate(list("P" * 100))
    interval_note = report["hypotheses"]["surf_continuation"]["test"]["interval_method"]
    assert "não se afirma cobertura nominal" in interval_note
    assert "gatilhos sobrepostos" in interval_note
    assert "cobertura nominal" in report["warning"]


def test_null_simulation_p_values_are_nonzero_and_full_family_corrected():
    report = HypothesisEvaluationEngine().evaluate(["P"] * 200)
    assert report["multiple_comparisons"]["family_size"] == 4
    validation = report["hypotheses"]["surf_continuation"]["validation"]
    assert validation["simulations"] >= 99
    assert 0 < validation["p_value"] <= 1
    assert validation["adjusted_p_value"] >= validation["p_value"]
