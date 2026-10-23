"""Recorta uma grade regular calibrada; não presume a estrutura de roadmaps."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .calibration import CaptureCalibration
from .color_detector import ColorDetector


@dataclass
class GridObservation:
    cells: tuple[str, ...]
    confidences: tuple[float, ...]
    annotated: np.ndarray | None = field(default=None, repr=False)
    sequence: tuple[str, ...] = ()
    valid: bool = True
    message: str = ""
    frame_shape: tuple[int, int] = (0, 0)

    @property
    def confidence(self) -> float:
        values = [v for label, v in zip(self.cells, self.confidences) if label in "PBT"]
        return min(values) if values else 0.0


class ChronologicalGridAdapter:
    """Mapeia células físicas a ordem cronológica; empates têm célula própria."""

    def __init__(self, calibration: CaptureCalibration):
        self.calibration = calibration

    def ordered_indices(self) -> list[int]:
        config = self.calibration
        if config.fill_order == "row":
            indices = list(range(config.rows * config.columns))
        else:
            indices = [row * config.columns + column
                       for column in range(config.columns) for row in range(config.rows)]
        return indices

    def sequence(self, cells: tuple[str, ...]) -> tuple[tuple[str, ...], bool, str]:
        if self.calibration.layout != "chronological":
            return (), False, "Roadmap de sequências exige adaptador específico; use grade cronológica"
        if self.calibration.tie_behavior != "separate":
            return (), False, "Empates sobrepostos não têm ordem recuperável; use células separadas"
        sequence = []
        empty_seen = False
        for index in self.ordered_indices():
            label = cells[index]
            if label == "UNKNOWN":
                return (), False, "Célula desconhecida: aguarde leitura estável ou recalibre as cores"
            if label == "EMPTY":
                empty_seen = True
            elif label in ("P", "B", "T"):
                if empty_seen:
                    return (), False, "Lacuna interna na grade: verifique ordem, região e calibração"
                sequence.append(label)
            else:
                return (), False, "Classificação inválida"
        if not self.calibration.newest_at_end:
            sequence.reverse()
        return tuple(sequence), True, "Grade cronológica reconhecida"


class ImageProcessor:
    def __init__(self, calibration: CaptureCalibration):
        self.calibration = calibration
        self.detector = ColorDetector(calibration)
        self.adapter = ChronologicalGridAdapter(calibration)

    def process(self, frame: np.ndarray) -> GridObservation:
        if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8
                or frame.ndim != 3 or frame.shape[2] not in (3, 4)):
            raise ValueError("Captura deve ser imagem BGR/BGRA uint8")
        frame = frame[:, :, :3]
        height, width = frame.shape[:2]
        config = self.calibration
        x, y, rw, rh = config.grid_roi
        left, top = round(x * width), round(y * height)
        right, bottom = round((x + rw) * width), round((y + rh) * height)
        if (right - left) < config.columns * 5 or (bottom - top) < config.rows * 5:
            raise ValueError("Região pequena demais para a grade; selecione novamente")
        annotated = frame.copy()
        cells, confidences = [], []
        colors = {"P": (245, 153, 50), "B": (75, 75, 230), "T": (115, 210, 60),
                  "EMPTY": (100, 100, 100), "UNKNOWN": (0, 200, 255)}
        for row in range(config.rows):
            for column in range(config.columns):
                x1 = left + round(column * (right - left) / config.columns)
                x2 = left + round((column + 1) * (right - left) / config.columns)
                y1 = top + round(row * (bottom - top) / config.rows)
                y2 = top + round((row + 1) * (bottom - top) / config.rows)
                px = max(1, int((x2 - x1) * config.cell_padding))
                py = max(1, int((y2 - y1) * config.cell_padding))
                reading = self.detector.classify(frame[y1 + py:y2 - py, x1 + px:x2 - px])
                cells.append(reading.label)
                confidences.append(reading.confidence)
                cv2.rectangle(annotated, (x1, y1), (x2 - 1, y2 - 1), colors[reading.label], 1)
                cv2.putText(annotated, reading.label[0] if reading.label != "UNKNOWN" else "?",
                            (x1 + 3, y1 + min(18, y2 - y1 - 2)), cv2.FONT_HERSHEY_SIMPLEX,
                            0.4, colors[reading.label], 1, cv2.LINE_AA)
        sequence, valid, message = self.adapter.sequence(tuple(cells))
        return GridObservation(tuple(cells), tuple(confidences), annotated, sequence,
                               valid, message, (height, width))

