from __future__ import annotations

import math
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .io import read_metric_value
from .models import (
    CalibrationConfig,
    Confusion,
    MetricCalibration,
    MetricConfig,
    StabilityInterval,
    ThresholdPoint,
)
from .utils import parse_bool, safe_div, to_float


def normalize_value(value: float, metric: MetricConfig) -> float:
    if metric.min_value is not None and metric.max_value is not None:
        span = metric.max_value - metric.min_value
        normalized = (value - metric.min_value) / span
        if metric.direction == "lower":
            normalized = 1.0 - normalized
        return normalized
    if metric.direction == "lower":
        return -value
    return value


def raw_from_normalized(value: float, metric: MetricConfig) -> float:
    if metric.min_value is not None and metric.max_value is not None:
        span = metric.max_value - metric.min_value
        if metric.direction == "lower":
            return metric.min_value + (1.0 - value) * span
        return metric.min_value + value * span
    if metric.direction == "lower":
        return -value
    return value


def confusion_from_predictions(labels: Sequence[bool], predictions: Sequence[bool]) -> Confusion:
    c = Confusion()
    for label, prediction in zip(labels, predictions):
        if label and prediction:
            c.tp += 1
        elif not label and prediction:
            c.fp += 1
        elif not label and not prediction:
            c.tn += 1
        elif label and not prediction:
            c.fn += 1
    return c


def rates(confusion: Confusion) -> Dict[str, float]:
    precision = safe_div(confusion.tp, confusion.tp + confusion.fp, 1.0)
    recall = safe_div(confusion.tp, confusion.tp + confusion.fn, 0.0)
    fpr = safe_div(confusion.fp, confusion.fp + confusion.tn, 0.0)
    fnr = safe_div(confusion.fn, confusion.fn + confusion.tp, 0.0)
    f1 = safe_div(2 * precision * recall, precision + recall, 0.0)
    accuracy = safe_div(confusion.tp + confusion.tn, confusion.total, 0.0)
    tnr = safe_div(confusion.tn, confusion.tn + confusion.fp, 0.0)
    balanced_accuracy = (recall + tnr) / 2
    return {
        "precision": precision,
        "recall": recall,
        "fpr": fpr,
        "fnr": fnr,
        "f1": f1,
        "accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy,
    }


def objective_value(rates_map: Mapping[str, float], objective: str) -> float:
    return float(rates_map[objective])


def constraints_satisfied(point: ThresholdPoint, cfg: CalibrationConfig, metric: MetricConfig) -> bool:
    target_precision = metric.target_precision if metric.target_precision is not None else cfg.target_precision
    min_recall = metric.min_recall if metric.min_recall is not None else cfg.min_recall
    max_fpr = metric.max_fpr if metric.max_fpr is not None else cfg.max_fpr
    max_fnr = metric.max_fnr if metric.max_fnr is not None else cfg.max_fnr
    if target_precision is not None and point.precision < target_precision:
        return False
    if min_recall is not None and point.recall < min_recall:
        return False
    if max_fpr is not None and point.fpr > max_fpr:
        return False
    if max_fnr is not None and point.fnr > max_fnr:
        return False
    return True


def threshold_candidates(values: Sequence[float]) -> List[float]:
    if not values:
        return []
    unique = sorted(set(values))
    eps = max(1e-12, (unique[-1] - unique[0]) * 1e-9)
    return [unique[0] - eps] + unique + [unique[-1] + eps]


def score_threshold(
    values: Sequence[float],
    raw_values: Sequence[float],
    labels: Sequence[bool],
    threshold: float,
    raw_threshold: float,
    objective: str,
    auxiliary_rows: Optional[Sequence[Mapping[str, float]]] = None,
) -> ThresholdPoint:
    predictions = [value >= threshold for value in values]
    confusion = confusion_from_predictions(labels, predictions)
    r = rates(confusion)
    accepted = sum(1 for item in predictions if item)
    rejected = len(predictions) - accepted
    auxiliaries: Dict[str, float] = {}
    if auxiliary_rows:
        fields = sorted({key for row in auxiliary_rows for key in row})
        for field in fields:
            all_values = [row[field] for row in auxiliary_rows if field in row]
            accepted_values = [row[field] for row, pred in zip(auxiliary_rows, predictions) if pred and field in row]
            auxiliaries[f"{field}_avg_all"] = safe_div(sum(all_values), len(all_values), 0.0)
            auxiliaries[f"{field}_avg_accepted"] = safe_div(sum(accepted_values), len(accepted_values), 0.0)
            auxiliaries[f"{field}_sum_accepted"] = sum(accepted_values)
    return ThresholdPoint(
        threshold=threshold,
        raw_threshold=raw_threshold,
        confusion=confusion,
        precision=r["precision"],
        recall=r["recall"],
        fpr=r["fpr"],
        fnr=r["fnr"],
        f1=r["f1"],
        accuracy=r["accuracy"],
        accepted=accepted,
        rejected=rejected,
        acceptance_rate=safe_div(accepted, len(predictions), 0.0),
        objective_value=objective_value(r, objective),
        auxiliaries=auxiliaries,
    )


def scan_metric(
    records: Sequence[Mapping[str, object]],
    labels: Sequence[bool],
    metric: MetricConfig,
    cfg: CalibrationConfig,
    auxiliary_fields: Sequence[str],
) -> MetricCalibration:
    normalized: List[float] = []
    raw_values: List[float] = []
    metric_labels: List[bool] = []
    auxiliary_rows: List[Dict[str, float]] = []
    warnings: List[str] = []

    for record, label in zip(records, labels):
        raw = read_metric_value(record, metric.name)
        if raw is None:
            continue
        raw_values.append(raw)
        normalized.append(normalize_value(raw, metric))
        metric_labels.append(label)
        aux: Dict[str, float] = {}
        for field in auxiliary_fields:
            value = to_float(record.get(field))
            if value is not None:
                aux[field] = value
        auxiliary_rows.append(aux)

    if not normalized:
        raise ValueError(f"指标 {metric.name} 没有可用数值")
    if len(normalized) < len(records):
        warnings.append(f"忽略 {len(records) - len(normalized)} 条缺少 {metric.name} 的历史记录")

    points: List[ThresholdPoint] = []
    for candidate in threshold_candidates(normalized):
        points.append(
            score_threshold(
                normalized,
                raw_values,
                metric_labels,
                candidate,
                raw_from_normalized(candidate, metric),
                cfg.objective,
                auxiliary_rows,
            )
        )

    feasible = [point for point in points if constraints_satisfied(point, cfg, metric)]
    if feasible:
        pool = feasible
    else:
        pool = points
        warnings.append("没有阈值同时满足约束，已回退到目标函数最优阈值")

    best = max(pool, key=lambda p: (p.objective_value, p.f1, p.precision, p.recall, -p.acceptance_rate))
    stable = compute_stability_interval(points, best, cfg, metric)
    reason = build_reason(best, stable, cfg, feasible=bool(feasible))
    return MetricCalibration(
        name=metric.name,
        direction=metric.direction,
        required=metric.required,
        threshold=best.raw_threshold,
        normalized_threshold=best.threshold,
        best=best,
        stable_interval=stable,
        points=points,
        reason=reason,
        warnings=warnings,
    )


def compute_stability_interval(
    points: Sequence[ThresholdPoint],
    best: ThresholdPoint,
    cfg: CalibrationConfig,
    metric: MetricConfig,
) -> StabilityInterval:
    floor = best.objective_value - cfg.stability_tolerance
    eligible = [
        point
        for point in points
        if point.objective_value >= floor and constraints_satisfied(point, cfg, metric)
    ]
    if not eligible:
        eligible = [best]
    lows = [point.threshold for point in eligible]
    raw_values = [point.raw_threshold for point in eligible]
    return StabilityInterval(
        normalized_low=min(lows),
        normalized_high=max(lows),
        raw_low=min(raw_values),
        raw_high=max(raw_values),
        width=max(lows) - min(lows),
        count=len(eligible),
    )


def build_reason(best: ThresholdPoint, stable: StabilityInterval, cfg: CalibrationConfig, feasible: bool) -> str:
    bits = [
        f"选择目标 {cfg.objective}={best.objective_value:.4f}",
        f"precision={best.precision:.4f}",
        f"recall={best.recall:.4f}",
        f"FPR={best.fpr:.4f}",
        f"FNR={best.fnr:.4f}",
    ]
    if feasible:
        bits.append("满足已配置约束")
    else:
        bits.append("未满足全部约束，使用目标函数最优")
    bits.append(f"稳定候选数={stable.count}")
    return "；".join(bits)


def labels_from_records(records: Sequence[Mapping[str, object]], label_field: str) -> Tuple[List[bool], List[str]]:
    labels: List[bool] = []
    warnings: List[str] = []
    skipped = 0
    for record in records:
        parsed = parse_bool(record.get(label_field))
        if parsed is None:
            skipped += 1
            continue
        labels.append(parsed)
    if skipped:
        warnings.append(f"忽略 {skipped} 条缺少人工 label 的历史记录")
    return labels, warnings


def filter_labeled_records(records: Sequence[Mapping[str, object]], label_field: str) -> Tuple[List[Mapping[str, object]], List[bool], int]:
    filtered: List[Mapping[str, object]] = []
    labels: List[bool] = []
    skipped = 0
    for record in records:
        parsed = parse_bool(record.get(label_field))
        if parsed is None:
            skipped += 1
            continue
        filtered.append(record)
        labels.append(parsed)
    return filtered, labels, skipped


def compare_result_field(records: Sequence[Mapping[str, object]], labels: Sequence[bool], result_field: Optional[str]) -> Optional[ThresholdPoint]:
    if not result_field:
        return None
    predictions = []
    usable_labels = []
    for record, label in zip(records, labels):
        parsed = parse_bool(record.get(result_field))
        if parsed is None:
            continue
        predictions.append(parsed)
        usable_labels.append(label)
    if not predictions:
        return None
    confusion = confusion_from_predictions(usable_labels, predictions)
    r = rates(confusion)
    return ThresholdPoint(
        threshold=math.nan,
        raw_threshold=math.nan,
        confusion=confusion,
        precision=r["precision"],
        recall=r["recall"],
        fpr=r["fpr"],
        fnr=r["fnr"],
        f1=r["f1"],
        accuracy=r["accuracy"],
        accepted=sum(1 for p in predictions if p),
        rejected=sum(1 for p in predictions if not p),
        acceptance_rate=safe_div(sum(1 for p in predictions if p), len(predictions), 0.0),
        objective_value=r["f1"],
    )
