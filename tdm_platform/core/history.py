from __future__ import annotations

import uuid

from tdm_platform.app_meta import APP_VERSION, SCHEMA_VERSION
from tdm_platform.core.models import HistoryRecord
from tdm_platform.storage.json_store import load_json_list, save_json
from tdm_platform.storage.paths import get_storage_paths


class HistoryStore:
    def __init__(self, path=None):
        self.path = path or get_storage_paths().history_path

    def load(self) -> list[dict]:
        data = load_json_list(self.path)
        if not isinstance(data, list):
            return []
        changed = False
        for row in data:
            if isinstance(row, dict) and not row.get("record_id"):
                row["record_id"] = str(uuid.uuid4())
                changed = True
        if changed:
            self.save(data)
        return data

    def save(self, rows: list[dict]) -> None:
        save_json(self.path, rows)

    def append(self, record: HistoryRecord) -> list[dict]:
        rows = self.load()
        payload = record.as_dict()
        payload["record_id"] = str(payload.get("record_id") or uuid.uuid4())
        payload["app_version"] = payload.get("app_version") or APP_VERSION
        payload["schema_version"] = payload.get("schema_version") or SCHEMA_VERSION
        rows.append(payload)
        self.save(rows)
        return rows
