import pytest

from bacbo_analytics.capture import CaptureCalibration, GridObservation, GridTrackingEngine


def observation(sequence, capacity=6, valid=True, shape=(60, 360)):
    cells = tuple(sequence) + ("EMPTY",) * (capacity - len(sequence))
    return GridObservation(cells, tuple(1.0 for _ in cells), sequence=tuple(sequence),
                           valid=valid, frame_shape=shape)


def stable(tracker, frame, count=None):
    for _ in range(count or tracker.calibration.confirmations):
        result = tracker.update(frame)
    return result


def tracker(capacity=6, **kwargs):
    return GridTrackingEngine(CaptureCalibration(rows=1, columns=capacity, **kwargs))


def test_first_frame_is_baseline_not_historical_rounds():
    result = stable(tracker(), observation("PBT"))
    assert result.baseline
    assert not result.new_results


def test_unchanged_grid_creates_no_round():
    engine = tracker()
    stable(engine, observation("PBP"))
    for _ in range(20):
        assert not engine.update(observation("PBP")).new_results
    assert engine.duplicates_avoided == 20


def test_new_cell_creates_exactly_one_result():
    engine = tracker()
    stable(engine, observation("PBP"))
    assert stable(engine, observation("PBPT")).new_results == ("T",)
    assert not stable(engine, observation("PBPT")).new_results


def test_full_scroll_unique_alignment_retains_only_new():
    engine = tracker(capacity=5)
    stable(engine, observation("BTPPB", 5))
    result = stable(engine, observation("TPPBP", 5))
    assert result.new_results == ("P",)
    assert result.status == "SYNCED"


def test_column_shift_recovers_only_visible_new_results():
    engine = GridTrackingEngine(CaptureCalibration(rows=2, columns=3, min_overlap=3))
    stable(engine, observation("PBTPPB"))
    result = stable(engine, observation("TPPBTB"))
    assert result.new_results == ("T", "B")
    assert result.status == "RECOVERED"


def test_ambiguous_scroll_suspends_instead_of_guessing():
    engine = tracker()
    stable(engine, observation("PPPPPP"))
    result = stable(engine, observation("PPPPPB"))
    assert result.status == "RECALIBRATE"
    assert not result.new_results
    assert not stable(engine, observation("PPPBBB")).new_results


def test_missing_overlap_never_fills_gap():
    engine = tracker()
    stable(engine, observation("PPPPPB"))
    result = stable(engine, observation("TTTTTT"))
    assert result.status == "RECALIBRATE"
    assert not result.new_results


def test_animation_does_not_confirm_prematurely():
    engine = tracker()
    stable(engine, observation("PB"))
    assert not engine.update(observation("PBP")).new_results
    assert not engine.update(observation("PBB")).new_results
    assert not engine.update(observation("PB")).new_results
    assert stable(engine, observation("PBT")).new_results == ("T",)


def test_unknown_resets_confirmation_without_inventing():
    engine = tracker()
    stable(engine, observation("PB"))
    engine.update(observation("PBT"))
    uncertain = observation("PB", valid=False)
    assert not engine.update(uncertain).new_results
    assert not engine.update(observation("PBT")).new_results
    assert engine.update(observation("PBT")).new_results == ()
    assert engine.update(observation("PBT")).new_results == ("T",)


def test_consecutive_ties_are_separate_rounds():
    engine = tracker()
    stable(engine, observation("P"))
    assert stable(engine, observation("PT")).new_results == ("T",)
    assert stable(engine, observation("PTT")).new_results == ("T",)


def test_resolution_change_requires_recalibration():
    engine = tracker()
    stable(engine, observation("PB"))
    result = engine.update(observation("PBP", shape=(120, 720)))
    assert result.status == "RECALIBRATE"
    assert not result.new_results


def test_manual_baseline_after_pause_preserves_old_history():
    engine = tracker()
    stable(engine, observation("PBP"))
    engine.reset()
    baseline = stable(engine, observation("TTB"))
    assert baseline.baseline and not baseline.new_results
    assert stable(engine, observation("TTBP")).new_results == ("P",)


def test_fixed_grid_cannot_guess_overwritten_cells():
    engine = tracker(scroll_mode="fixed")
    stable(engine, observation("PBTPPB"))
    result = stable(engine, observation("BTPPBT"))
    assert result.status == "RECALIBRATE"


def test_overlay_ties_are_not_fabricated():
    engine = tracker(tie_behavior="overlay")
    assert engine.update(observation("PBT")).status == "UNSUPPORTED"
