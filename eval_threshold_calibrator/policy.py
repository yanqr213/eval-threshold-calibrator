from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Sequence

from .errors import ConfigError, InputError
from .io import read_metric_value
from .models import CurrentGateReport, CurrentRecordDecision
from .utils import to_float


POLICY_SCHEMA_VERSION = "eval-threshold-policy.v1"


def load_policy(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} policy JSON 解析失败: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"无法读取 policy {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("policy 顶层必须是 JSON object")
    validate_policy(data)
    return data


def validate_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise ConfigError(f"policy schema_version 必须是 {POLICY_SCHEMA_VERSION}")
    metrics = policy.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ConfigError("policy.metrics 必须是非空 object")
    for name, raw in metrics.items():
        if not isinstance(raw, dict):
            raise ConfigError(f"policy.metrics.{name} 必须是 object")
        if "threshold" not in raw:
            raise ConfigError(f"policy.metrics.{name}.threshold 缺失")
        direction = raw.get("direction", "higher")
        if direction not in {"higher", "lower"}:
            raise ConfigError(f"policy.metrics.{name}.direction 必须是 higher 或 lower")
        required = raw.get("required", True)
        if not isinstance(required, bool):
            raise ConfigError(f"policy.metrics.{name}.required 必须是 boolean")
        threshold = to_float(raw.get("threshold"))
        if threshold is None:
            raise ConfigError(f"policy.metrics.{name}.threshold 必须是 finite number")
    pass_rate = policy.get("current_min_pass_rate", 1.0)
    if isinstance(pass_rate, bool) or not isinstance(pass_rate, (int, float)) or not 0 <= float(pass_rate) <= 1:
        raise ConfigError("policy.current_min_pass_rate 必须在 [0, 1]")


def evaluate_current_with_policy(records: Sequence[Mapping[str, object]], policy: Mapping[str, Any]) -> CurrentGateReport:
    validate_policy(policy)
    metrics = policy["metrics"]
    id_field = str(policy.get("id_field", "id"))
    decisions = []
    for index, record in enumerate(records):
        record_id = str(record.get(id_field, index + 1))
        metric_values: Dict[str, float] = {}
        metric_passed: Dict[str, bool] = {}
        missing = []
        passed = True
        for name, raw_metric in metrics.items():
            if not bool(raw_metric.get("required", True)):
                continue
            value = read_metric_value(record, str(name))
            if value is None:
                missing.append(str(name))
                metric_passed[str(name)] = False
                passed = False
                continue
            metric_values[str(name)] = value
            direction = str(raw_metric.get("direction", "higher"))
            threshold = float(raw_metric["threshold"])
            ok = value <= threshold if direction == "lower" else value >= threshold
            metric_passed[str(name)] = ok
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
    required_rate = float(policy.get("current_min_pass_rate", 1.0))
    if not records:
        raise InputError("当前候选数据为空，无法应用 policy")
    return CurrentGateReport(
        total=total,
        passed=passed_count,
        failed=total - passed_count,
        pass_rate=pass_rate,
        gate_passed=pass_rate >= required_rate,
        decisions=decisions,
    )
