from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any


def to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(item) for item in value]
    return value


def to_json(value: Any, pretty: bool = True) -> str:
    return json.dumps(to_plain(value), ensure_ascii=False, indent=2 if pretty else None, sort_keys=True)
