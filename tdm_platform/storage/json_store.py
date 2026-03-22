from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


JSONDict = dict[str, Any]
JSONList = list[Any]


def load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2, default=str)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def load_json_list(path: Path) -> JSONList:
    data = load_json(path, [])
    return data if isinstance(data, list) else []


def load_json_dict(path: Path) -> JSONDict:
    data = load_json(path, {})
    return data if isinstance(data, dict) else {}
