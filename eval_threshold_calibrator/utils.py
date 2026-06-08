from __future__ import annotations

import math
from typing import Any, Optional


TRUE_STRINGS = {"1", "true", "t", "yes", "y", "pass", "passed", "ok", "good", "accepted"}
FALSE_STRINGS = {"0", "false", "f", "no", "n", "fail", "failed", "bad", "rejected"}


def parse_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
    text = str(value).strip().lower()
    if text in TRUE_STRINGS:
        return True
    if text in FALSE_STRINGS:
        return False
    return None


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if text == "":
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    if not math.isfinite(number):
        return None
    return number


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0:
        return default
    return numerator / denominator


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def fmt_float(value: float, digits: int = 4) -> str:
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    if value == int(value):
        return str(int(value))
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")
