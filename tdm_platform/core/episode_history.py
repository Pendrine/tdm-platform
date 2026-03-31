from __future__ import annotations

import re
from collections import defaultdict


def normalize_patient_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def find_patient_episodes(
    rows: list[dict],
    patient_id: str,
    patient_name: str,
    antibiotic: str | None = None,
) -> list[dict]:
    pid = str(patient_id or "").strip()
    pname = normalize_patient_name(patient_name)
    antibiotic_norm = str(antibiotic or "").strip().lower()
    matches: list[dict] = []
    for row in rows:
        row_abx = str(row.get("drug", "")).strip().lower()
        if antibiotic_norm and row_abx != antibiotic_norm:
            continue

        row_pid = str(row.get("patient_id", "")).strip()
        row_pname = normalize_patient_name(str((row.get("inputs") or {}).get("patient_name", "")))
        if pid and row_pid == pid:
            matches.append(row)
            continue
        if pname and row_pname and row_pname == pname:
            matches.append(row)
    return matches


def summarize_episodes_by_antibiotic(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        abx = str(row.get("drug", "")).strip() or "Ismeretlen"
        counts[abx] += 1
    return dict(sorted(counts.items(), key=lambda item: item[0]))
