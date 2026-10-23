"""Imagens sintéticas rotuladas: não medem precisão sobre uma mesa real."""
import cv2
import numpy as np
import pytest
import json
from pathlib import Path

from bacbo_analytics.capture.calibration import CaptureCalibration
from bacbo_analytics.capture.color_detector import ColorDetector
from bacbo_analytics.capture.image_processor import ImageProcessor


COLORS = {"P": (255, 75, 0), "B": (0, 0, 230), "T": (0, 210, 0), "EMPTY": (25, 25, 25)}


def test_labeled_reference_image_exactness():
    fixtures = Path(__file__).parent / "fixtures"
    labels = json.loads((fixtures / "reference_labels.json").read_text(encoding="utf-8"))
    image = cv2.imread(str(fixtures / "reference_grid.png"))
    observation = ImageProcessor(CaptureCalibration(rows=labels["rows"], columns=labels["columns"])).process(image)
    assert observation.cells == tuple(labels["labels"])
    assert labels["origin"] == "synthetic"
    assert not labels["real_table_validation"]


def synthetic_grid(labels, rows=1, columns=None, brightness=1.0):
    columns = columns or len(labels)
    image = np.full((rows * 60, columns * 60, 3), 25, np.uint8)
    for index, label in enumerate(labels):
        y, x = divmod(index, columns)
        color = tuple(int(value * brightness) for value in COLORS[label])
        if label != "EMPTY":
            cv2.circle(image, (x * 60 + 30, y * 60 + 30), 18, color, -1)
    return image


@pytest.mark.parametrize("brightness", [0.45, 0.75, 1.0])
def test_known_synthetic_colors_survive_brightness_changes(brightness):
    config = CaptureCalibration(rows=1, columns=4)
    result = ImageProcessor(config).process(synthetic_grid(["P", "B", "T", "EMPTY"], brightness=brightness))
    assert result.cells == ("P", "B", "T", "EMPTY")
    assert result.sequence == ("P", "B", "T")
    assert result.valid
    assert result.annotated.shape == (60, 240, 3)


def test_ambiguous_mixed_color_never_invents_result():
    image = np.zeros((60, 60, 3), np.uint8)
    image[:, :30] = COLORS["P"]
    image[:, 30:] = COLORS["B"]
    observation = ImageProcessor(CaptureCalibration(rows=1, columns=1)).process(image)
    assert observation.cells == ("UNKNOWN",)
    assert not observation.valid


def test_unconfigured_yellow_is_unknown_not_tie():
    patch = np.full((60, 60, 3), (0, 220, 220), np.uint8)
    assert ColorDetector(CaptureCalibration()).classify(patch).label == "UNKNOWN"
    config = CaptureCalibration(hue_profiles={"P": 110, "B": 0, "T": 30})
    assert ColorDetector(config).classify(patch).label == "T"


def test_column_order_and_ties_preserved():
    labels = ["P", "B", "T", "T", "P", "B"]
    result = ImageProcessor(CaptureCalibration(rows=2, columns=3)).process(synthetic_grid(labels, 2, 3))
    assert result.sequence == ("P", "T", "B", "P", "T", "B")


def test_hole_is_not_silently_dropped():
    result = ImageProcessor(CaptureCalibration(rows=1, columns=3)).process(synthetic_grid(["P", "EMPTY", "B"]))
    assert not result.valid
    assert "Lacuna" in result.message


def test_newest_first_reverses_only_occupied_cells():
    config = CaptureCalibration(rows=1, columns=4, newest_at_end=False)
    result = ImageProcessor(config).process(synthetic_grid(["B", "P", "EMPTY", "EMPTY"]))
    assert result.valid
    assert result.sequence == ("P", "B")


def test_sequence_layout_is_explicitly_unsupported():
    result = ImageProcessor(CaptureCalibration(rows=1, columns=2, layout="sequence")).process(synthetic_grid(["P", "B"]))
    assert not result.valid
    assert "adaptador" in result.message


def test_hue_sampling_handles_red_circular_boundary():
    hsv = np.zeros((10, 10, 3), np.uint8)
    hsv[:, :, 1:] = 255
    hsv[:5, :, 0], hsv[5:, :, 0] = 1, 179
    color = ColorDetector.sample_hue(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))
    assert color < 3 or color > 177


@pytest.mark.parametrize("kwargs", [{"rows": 0}, {"columns": -2}, {"confirmations": 0},
                                    {"cell_padding": 0.9}, {"grid_roi": (0.8, 0, 0.5, 1)}])
def test_invalid_calibration_rejected(kwargs):
    with pytest.raises(ValueError):
        CaptureCalibration(**kwargs)

