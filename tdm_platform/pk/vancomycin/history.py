from __future__ import annotations

from tdm_platform.core.episode_history import find_patient_episodes


def find_matching_episode_history(
    rows: list[dict],
    patient_id: str,
    patient_name: str,
    antibiotic: str,
) -> list[dict]:
    return find_patient_episodes(rows, patient_id=patient_id, patient_name=patient_name, antibiotic=antibiotic)
