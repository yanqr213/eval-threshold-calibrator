"""Offline threshold calibration for eval CI gates."""

from .calibrator import calibrate
from .models import CalibrationConfig, CalibrationReport, MetricConfig

__all__ = [
    "CalibrationConfig",
    "CalibrationReport",
    "MetricConfig",
    "calibrate",
]

__version__ = "0.1.0"
