from bacbo_analytics.analysis import SimulationEngine


def test_seed_reproducible():
    assert SimulationEngine(15).generate(100) == SimulationEngine(15).generate(100)


def test_four_dice_determine_result():
    for result, dice in SimulationEngine(72).generate(1000):
        assert len(dice) == 4
        assert all(1 <= die <= 6 for die in dice)
        p, b = sum(dice[:2]), sum(dice[2:])
        assert result == ("P" if p > b else "B" if b > p else "T")


def test_ten_thousand_fair_simulated_rounds():
    values = [r for r, _ in SimulationEngine(51).generate(10000)]
    assert 0.42 < values.count("P") / len(values) < 0.47
    assert 0.09 < values.count("T") / len(values) < 0.14
