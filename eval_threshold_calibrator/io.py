from __future__ import annotations

import csv
import json
import os
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .errors import ConfigError, InputError
from .models import CalibrationConfig, MetricConfig
from .utils import to_float


AUTO_AUXILIARY_FIELDS = [
    "cost_usd",
    "latency_ms",
    "tokens",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
]


def read_records(path: str) -> List[Dict[str, Any]]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".jsonl":
        return read_jsonl(path)
    if ext == ".csv":
        return read_csv(path)
    raise InputError(f"不支持的输入格式: {path}，仅支持 .jsonl 和 .csv")


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise InputError(f"{path}:{lineno} JSON 解析失败: {exc}") from exc
                if not isinstance(obj, dict):
                    raise InputError(f"{path}:{lineno} 必须是 JSON object")
                records.append(obj)
    except OSError as exc:
        raise InputError(f"无法读取 {path}: {exc}") from exc
    return records


def read_csv(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                raise InputError(f"{path} 缺少 CSV 表头")
            return [dict(row) for row in reader]
    except csv.Error as exc:
        raise InputError(f"{path} CSV 解析失败: {exc}") from exc
    except OSError as exc:
        raise InputError(f"无法读取 {path}: {exc}") from exc


def load_config(path: Optional[str]) -> CalibrationConfig:
    if path is None:
        return CalibrationConfig()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} JSON 配置解析失败: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"无法读取配置 {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("配置文件顶层必须是 JSON object")
    return config_from_dict(data)


def config_from_dict(data: Mapping[str, Any]) -> CalibrationConfig:
    cfg = CalibrationConfig()
    allowed = {
        "label_field",
        "result_field",
        "id_field",
        "metrics",
        "objective",
        "stability_tolerance",
        "target_precision",
        "min_recall",
        "max_fpr",
        "max_fnr",
        "fail_on_current",
        "current_min_pass_rate",
        "auxiliary_fields",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"未知配置字段: {', '.join(unknown)}")
    for field_name in allowed - {"metrics", "auxiliary_fields"}:
        if field_name in data:
            setattr(cfg, field_name, data[field_name])
    if "auxiliary_fields" in data:
        if not isinstance(data["auxiliary_fields"], list):
            raise ConfigError("auxiliary_fields 必须是数组")
        cfg.auxiliary_fields = [str(item) for item in data["auxiliary_fields"]]
    if "metrics" in data:
        raw_metrics = data["metrics"]
        if not isinstance(raw_metrics, dict):
            raise ConfigError("metrics 必须是 object")
        cfg.metrics = {}
        for name, raw in raw_metrics.items():
            if raw is None:
                raw = {}
            if not isinstance(raw, dict):
                raise ConfigError(f"metrics.{name} 必须是 object")
            cfg.metrics[str(name)] = metric_config_from_dict(str(name), raw)
    validate_config(cfg)
    return cfg


def metric_config_from_dict(name: str, data: Mapping[str, Any]) -> MetricConfig:
    allowed = {
        "direction",
        "required",
        "weight",
        "min_value",
        "max_value",
        "threshold",
        "kind",
        "target_precision",
        "min_recall",
        "max_fpr",
        "max_fnr",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"metrics.{name} 未知字段: {', '.join(unknown)}")
    metric = MetricConfig(name=name)
    for key in allowed:
        if key in data:
            setattr(metric, key, data[key])
    validate_metric(metric)
    return metric


def validate_config(cfg: CalibrationConfig) -> None:
    if cfg.objective not in {"f1", "precision", "recall", "accuracy", "balanced_accuracy"}:
        raise ConfigError("objective 必须是 f1/precision/recall/accuracy/balanced_accuracy")
    if cfg.stability_tolerance < 0:
        raise ConfigError("stability_tolerance 不能为负数")
    if not 0 <= cfg.current_min_pass_rate <= 1:
        raise ConfigError("current_min_pass_rate 必须在 [0, 1]")
    for name in ("target_precision", "min_recall", "max_fpr", "max_fnr"):
        value = getattr(cfg, name)
        if value is not None and not 0 <= value <= 1:
            raise ConfigError(f"{name} 必须在 [0, 1]")
    for metric in cfg.metrics.values():
        validate_metric(metric)


def validate_metric(metric: MetricConfig) -> None:
    if metric.direction not in {"higher", "lower"}:
        raise ConfigError(f"metrics.{metric.name}.direction 必须是 higher 或 lower")
    if metric.weight <= 0:
        raise ConfigError(f"metrics.{metric.name}.weight 必须大于 0")
    if metric.min_value is not None and metric.max_value is not None and metric.min_value >= metric.max_value:
        raise ConfigError(f"metrics.{metric.name}.min_value 必须小于 max_value")
    for name in ("target_precision", "min_recall", "max_fpr", "max_fnr"):
        value = getattr(metric, name)
        if value is not None and not 0 <= value <= 1:
            raise ConfigError(f"metrics.{metric.name}.{name} 必须在 [0, 1]")


def discover_metrics(records: Iterable[Mapping[str, Any]], cfg: CalibrationConfig) -> Dict[str, MetricConfig]:
    if cfg.metrics:
        return dict(cfg.metrics)
    excluded = {cfg.label_field, cfg.id_field}
    if cfg.result_field:
        excluded.add(cfg.result_field)
    excluded.update(AUTO_AUXILIARY_FIELDS)
    names = set()
    for record in records:
        nested = record.get("metrics")
        if isinstance(nested, dict):
            for key, value in nested.items():
                if to_float(value) is not None:
                    names.add(str(key))
        for key, value in record.items():
            if key in excluded or key == "metrics":
                continue
            if to_float(value) is not None:
                names.add(str(key))
    return {name: MetricConfig(name=name) for name in sorted(names)}


def read_metric_value(record: Mapping[str, Any], name: str) -> Optional[float]:
    nested = record.get("metrics")
    if isinstance(nested, dict) and name in nested:
        return to_float(nested.get(name))
    return to_float(record.get(name))


def auxiliary_fields(records: Iterable[Mapping[str, Any]], cfg: CalibrationConfig) -> List[str]:
    fields = list(cfg.auxiliary_fields)
    for record in records:
        for name in AUTO_AUXILIARY_FIELDS:
            if name not in fields and name in record and to_float(record.get(name)) is not None:
                fields.append(name)
    return fields
