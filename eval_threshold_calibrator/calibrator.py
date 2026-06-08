from __future__ import annotations

from typing import Dict, Mapping, Optional, Sequence

from .errors import InputError
from .io import auxiliary_fields, discover_metrics, read_metric_value
from .metrics import compare_result_field, filter_labeled_records, normalize_value, scan_metric
from .models import (
    CalibrationConfig,
    CalibrationReport,
    CurrentGateReport,
    CurrentRecordDecision,
)


def calibrate(
    history_records: Sequence[Mapping[str, object]],
    config: Optional[CalibrationConfig] = None,
    current_records: Optional[Sequence[Mapping[str, object]]] = None,
) -> CalibrationReport:
    cfg = config or CalibrationConfig()
    labeled_records, labels, skipped = filter_labeled_records(history_records, cfg.label_field)
    if not labeled_records:
        raise InputError(f"历史数据中没有可用人工 label 字段: {cfg.label_field}")
    metrics = discover_metrics(labeled_records, cfg)
    if not metrics:
        raise InputError("没有发现可校准指标，请在 metrics 配置中声明或提供数值字段")
    aux_fields = auxiliary_fields(labeled_records, cfg)

    metric_reports = {}
    warnings = []
    if skipped:
        warnings.append(f"忽略 {skipped} 条缺少人工 label 的历史记录")
    for metric in metrics.values():
        try:
            metric_reports[metric.name] = scan_metric(labeled_records, labels, metric, cfg, aux_fields)
        except ValueError as exc:
            warnings.append(str(exc))
    if not metric_reports:
        raise InputError("所有指标都缺少可用数值")

    current = evaluate_current(current_records, cfg, metric_reports) if current_records is not None else None
    existing_gate = compare_result_field(labeled_records, labels, cfg.result_field)
    return CalibrationReport(
        metrics=metric_reports,
        current=current,
        config=cfg,
        history_count=len(labeled_records),
        positive_count=sum(1 for label in labels if label),
        negative_count=sum(1 for label in labels if not label),
        existing_gate=existing_gate,
        warnings=warnings,
    )


def evaluate_current(
    records: Sequence[Mapping[str, object]],
    cfg: CalibrationConfig,
    metric_reports: Mapping[str, object],
) -> CurrentGateReport:
    decisions = []
    for index, record in enumerate(records):
        record_id = str(record.get(cfg.id_field, index + 1))
        metric_values: Dict[str, float] = {}
        metric_passed: Dict[str, bool] = {}
        missing = []
        passed = True
        for name, calibration in metric_reports.items():
            if not calibration.required:
                continue
            raw = read_metric_value(record, name)
            if raw is None:
                missing.append(name)
                metric_passed[name] = False
                passed = False
                continue
            metric_values[name] = raw
            normalized = normalize_value(raw, cfg.metrics.get(name, calibration_to_metric_config(calibration)))
            ok = normalized >= calibration.normalized_threshold
            metric_passed[name] = ok
            if not ok:
                passed = False
        decisions.append(
            CurrentRecordDecision(
                record_id=record_id,
                metric_values=metric_values,
                metric_passed=metric_passed,
                passed=passed,
                missing_metrics=missing,
            )
        )
    total = len(decisions)
    passed_count = sum(1 for item in decisions if item.passed)
    pass_rate = passed_count / total if total else 0.0
    return CurrentGateReport(
        total=total,
        passed=passed_count,
        failed=total - passed_count,
        pass_rate=pass_rate,
        gate_passed=pass_rate >= cfg.current_min_pass_rate,
        decisions=decisions,
    )


def calibration_to_metric_config(calibration) -> object:
    from .models import MetricConfig

    return MetricConfig(
        name=calibration.name,
        direction=calibration.direction,
        required=calibration.required,
    )
