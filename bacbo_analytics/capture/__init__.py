"""Captura visual calibrável; nunca completa resultados não observados."""

from .calibration import CaptureCalibration
from .grid_tracking import GridTrackingEngine, TrackingResult
from .image_processor import GridObservation, ImageProcessor
from .screen_capture import ScreenCaptureEngine

__all__ = ["CaptureCalibration", "GridObservation", "GridTrackingEngine",
           "ImageProcessor", "ScreenCaptureEngine", "TrackingResult"]
