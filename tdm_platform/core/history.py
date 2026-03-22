from __future__ import annotations

from tdm_platform.app_meta import APP_VERSION, SCHEMA_VERSION
from tdm_platform.core.models import HistoryRecord
from tdm_platform.storage.json_store import load_json_list, save_json
from tdm_platform.storage.paths import HISTORY_PATH


class HistoryStore:
    def __init__(self, path=HISTORY_PATH):
        self.path = path

    def load(self) -> list[dict]:
        data = load_json_list(self.path)
        return data if isinstance(data, list) else []

    def save(self, rows: list[dict]) -> None:
        save_json(self.path, rows)

    def append(self, record: HistoryRecord) -> list[dict]:
        rows = self.load()
        payload = record.as_dict()
        payload["app_version"] = payload.get("app_version") or APP_VERSION
        payload["schema_version"] = payload.get("schema_version") or SCHEMA_VERSION
        rows.append(payload)
        self.save(rows)
        return rows
