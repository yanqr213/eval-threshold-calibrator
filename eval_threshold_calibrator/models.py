from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class MetricConfig:
    name: str
    direction: str = "higher"
    required: bool = True
    weight: float = 1.0
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    threshold: Optional[float] = None
    kind: str = "quality"
    target_precision: Optional[float] = None
    min_recall: Optional[float] = None
    max_fpr: Optional[float] = None
    max_fnr: Optional[float] = None


@dataclass
class CalibrationConfig:
    label_field: str = "label"
    result_field: Optional[str] = "passed"
    id_field: str = "id"
    metrics: Dict[str, MetricConfig] = field(default_factory=dict)
    objective: str = "f1"
    stability_tolerance: float = 0.01
    target_precision: Optional[float] = None
    min_recall: Optional[float] = None
    max_fpr: Optional[float] = None
    max_fnr: Optional[float] = None
    fail_on_current: bool = False
    current_min_pass_rate: float = 1.0
    auxiliary_fields: List[str] = field(default_factory=list)


@dataclass
class Confusion:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.tn + self.fn


@dataclass
class ThresholdPoint:
    threshold: float
    raw_threshold: float
    confusion: Confusion
    precision: float
    recall: float
    fpr: float
    fnr: float
    f1: float
    accuracy: float
    accepted: int
    rejected: int
    acceptance_rate: float
    objective_value: float
    auxiliaries: Dict[str, float] = field(default_factory=dict)


@dataclass
class StabilityInterval:
    normalized_low: float
    normalized_high: float
    raw_low: float
    raw_high: float
    width: float
    count: int


@dataclass
class MetricCalibration:
    name: str
    direction: str
    required: bool
    threshold: float
    normalized_threshold: float
    best: ThresholdPoint
    stable_interval: StabilityInterval
    points: List[ThresholdPoint]
    reason: str
    warnings: List[str] = field(default_factory=list)


@dataclass
class CurrentRecordDecision:
    record_id: str
    metric_values: Dict[str, float]
    metric_passed: Dict[str, bool]
    passed: bool
    missing_metrics: List[str] = field(default_factory=list)


@dataclass
class CurrentGateReport:
    total: int
    passed: int
    failed: int
    pass_rate: float
    gate_passed: bool
    decisions: List[CurrentRecordDecision] = field(default_factory=list)


@dataclass
class CalibrationReport:
    metrics: Dict[str, MetricCalibration]
    current: Optional[CurrentGateReport]
    config: CalibrationConfig
    history_count: int
    positive_count: int
    negative_count: int
    existing_gate: Optional[ThresholdPoint] = None
    warnings: List[str] = field(default_factory=list)


def interval_tuple(interval: StabilityInterval) -> Tuple[float, float]:
    return interval.raw_low, interval.raw_high
