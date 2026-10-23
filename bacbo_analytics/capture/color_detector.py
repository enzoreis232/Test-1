"""Classifica por matiz circular, saturação e proporção de pixels úteis."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .calibration import CaptureCalibration


@dataclass(frozen=True)
class CellReading:
    label: str
    confidence: float
    color_fraction: float


class ColorDetector:
    def __init__(self, calibration: CaptureCalibration):
        self.calibration = calibration

    def classify(self, cell: np.ndarray) -> CellReading:
        if cell.size == 0 or cell.ndim != 3 or cell.shape[2] != 3:
            return CellReading("UNKNOWN", 0.0, 0.0)
        hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
        calibration = self.calibration
        colored = ((hsv[:, :, 1] >= calibration.min_saturation)
                   & (hsv[:, :, 2] >= calibration.min_value))
        fraction = float(np.mean(colored))
        if fraction <= calibration.max_empty_color_fraction:
            # EMPTY significa ausência de pixels saturados, não resultado do jogo.
            return CellReading("EMPTY", 1.0 - fraction, fraction)
        if fraction < calibration.min_color_fraction:
            return CellReading("UNKNOWN", 0.0, fraction)
        hues = hsv[:, :, 0][colored].astype(float)
        scores = {}
        for label, center in calibration.hue_profiles.items():
            distance = np.abs(hues - float(center))
            circular_distance = np.minimum(distance, 180 - distance)
            scores[label] = float(np.mean(circular_distance <= calibration.hue_tolerance))
        ranking = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        label, confidence = ranking[0]
        # Perfis sobrepostos e misturas semelhantes nunca viram classificação aleatória.
        if confidence < calibration.confidence_threshold or confidence - ranking[1][1] < 0.20:
            return CellReading("UNKNOWN", confidence, fraction)
        return CellReading(label, confidence, fraction)

    @staticmethod
    def sample_hue(patch: np.ndarray, min_saturation: int = 80) -> float:
        """Obtém matiz médio circular de amostra selecionada pelo usuário."""
        if patch.size == 0:
            raise ValueError("Selecione uma amostra de cor não vazia")
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        hues = hsv[:, :, 0][hsv[:, :, 1] >= min_saturation]
        if len(hues) < 3:
            raise ValueError("Amostra sem pixels coloridos suficientes")
        angles = hues.astype(float) * (2 * np.pi / 180)
        concentration = abs(np.mean(np.exp(1j * angles)))
        if concentration < 0.8:
            raise ValueError("Amostra mistura cores; selecione apenas um resultado")
        return float((np.angle(np.mean(np.exp(1j * angles))) * 180 / (2 * np.pi)) % 180)

