from tdm_platform.core.episode_history import find_patient_episodes, summarize_episodes_by_antibiotic


def test_find_patient_episodes_for_specific_antibiotic_and_all_antibiotics():
    rows = [
        {"patient_id": "P-1", "drug": "Vancomycin", "inputs": {"patient_name": "Teszt Elek"}},
        {"patient_id": "P-1", "drug": "Linezolid", "inputs": {"patient_name": "Teszt Elek"}},
        {"patient_id": "P-2", "drug": "Vancomycin", "inputs": {"patient_name": "Más Valaki"}},
    ]
    vanco = find_patient_episodes(rows, patient_id="P-1", patient_name="", antibiotic="Vancomycin")
    all_abx = find_patient_episodes(rows, patient_id="P-1", patient_name="", antibiotic=None)
    assert len(vanco) == 1
    assert len(all_abx) == 2


def test_episode_summary_groups_all_antibiotics():
    rows = [
        {"drug": "Vancomycin"},
        {"drug": "Vancomycin"},
        {"drug": "Linezolid"},
    ]
    summary = summarize_episodes_by_antibiotic(rows)
    assert summary["Linezolid"] == 1
    assert summary["Vancomycin"] == 2
