import pytest

from bacbo_analytics.analysis import StrategyEngine


def test_surf_preserves_ties():
    report = StrategyEngine().analyze(list("PPPPT"))
    assert not report["patterns"]["surf"]["active"]
    assert report["longest_run"] == 4
    assert report["current_run"] == {"side": "T", "length": 1}


def test_chess_uses_four_changes_not_four_results():
    engine = StrategyEngine()
    assert not engine.analyze(list("PBPB"))["patterns"]["chess"]["active"]
    assert engine.analyze(list("PBPBP"))["patterns"]["chess"]["active"]


def test_blocks_sizes():
    report = StrategyEngine().analyze(list("PPBBPPBB"))
    assert report["patterns"]["blocks"]["sizes"] == [2]


def test_consecutive_ties_preserved_with_distance_one():
    report = StrategyEngine().analyze(list("PTTTBPT"))
    assert report["tie_intervals"]["intervals"] == [1, 1, 3]
    assert report["transitions"]["T"]["T"] == 2
    assert report["windows"]["all"]["counts"]["T"] == 4


def test_empty_history_and_corrupt_input():
    assert StrategyEngine().analyze([])["longest_run"] == 0
    with pytest.raises(ValueError):
        StrategyEngine().analyze(["P", "X"])


def test_custom_detector_extensible():
    class Detector:
        name = "custom"

        def detect(self, results):
            return {"n": len(results)}

    assert StrategyEngine(detectors=[Detector()]).analyze(["P"])["patterns"]["custom"] == {"n": 1}
