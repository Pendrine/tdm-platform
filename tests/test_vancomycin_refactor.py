from datetime import datetime

from tdm_platform.pk.vancomycin.domain import AntibioticEpisode, EpisodeEvent, Patient
from tdm_platform.pk.vancomycin.fit_engine import fit_models
from tdm_platform.pk.vancomycin.history import find_matching_episode_history
from tdm_platform.pk.vancomycin.model_library import ACTIVE_MODEL_KEYS, MODELS, active_models
from tdm_platform.pk.vancomycin.recommendation_engine import build_recommendation
from tdm_platform.pk.vancomycin.selector import auto_select_model
from tdm_platform.pk.vancomycin.workflow import build_simple_episode, normalize_event_type, run_vancomycin_workflow
from tdm_platform.pk.vancomycin.weights import build_weight_metrics, crcl_from_metrics
from tdm_platform.pk.vancomycin_engine import VancomycinInputs, calc_auc_trapezoid, calculate


def _episode(**flags):
    patient = Patient(
        patient_id="P-1",
        patient_name="Teszt Elek",
        sex="férfi",
        age=60,
        height_cm=175,
        tbw_kg=110 if flags.get("obese") else 80,
        scr_umol=100,
        icu_flag=flags.get("icu", False),
        unstable_renal_flag=flags.get("unstable_renal", False),
        hematology_flag=flags.get("hematology", False),
        hsct_flag=flags.get("hsct", False),
        hemodialysis_flag=flags.get("dialysis", False),
    )
    now = datetime.utcnow()
    return AntibioticEpisode(
        episode_id="EP-1",
        antibiotic="Vancomycin",
        patient=patient,
        events=(
            EpisodeEvent("maintenance_dose", now, 1000.0, "mg", {"tau_h": 12.0, "tinf_h": 1.0, "t_from_last_start_h": 0.0}),
            EpisodeEvent("sample", now, 22.0, "mg/L", {"t_from_last_start_h": 2.0}),
            EpisodeEvent("sample", now, 12.0, "mg/L", {"t_from_last_start_h": 10.0}),
        ),
    )


def test_weight_metrics_tbw_ibw_adjbw_and_obesity_flag():
    m = build_weight_metrics("férfi", 175, 110)
    assert m.tbw_kg == 110
    assert m.ibw_kg > 0
    assert m.adjbw_kg > m.ibw_kg
    assert m.obesity_flag


def test_crcl_calculation_supports_weight_strategies():
    m = build_weight_metrics("férfi", 175, 110)
    crcl_tbw = crcl_from_metrics(60, "férfi", 100, m, "tbw")
    crcl_adjbw = crcl_from_metrics(60, "férfi", 100, m, "adjbw")
    assert crcl_tbw != crcl_adjbw


def test_trapezoid_auc_and_auc_mic_and_suggestion():
    inp = VancomycinInputs(
        sex="férfi",
        age=60,
        weight_kg=80,
        scr_umol=100,
        dose_mg=1000,
        tau_h=12,
        tinf_h=1,
        c1=25,
        t1_start_h=2,
        c2=12,
        t2_start_h=10,
        mic=1.0,
        method="Klasszikus",
    )
    auc = calc_auc_trapezoid(inp)
    result = calculate(inp)
    assert auc["auc24"] > 0
    assert result["auc_mic"] == result["auc24"]
    assert result["suggestion"]["best"]["dose"] > 0


def test_selector_icu_obese_hsct_and_bayes_preference():
    ep_icu = _episode(icu=True)
    sel_icu = auto_select_model(ep_icu, build_weight_metrics("férfi", 175, 80), dose_number=1, has_previous_episode=False)
    assert sel_icu.recommended_model_key == "roberts_2011"
    assert sel_icu.bayesian_preferred

    ep_obese = _episode(obese=True)
    sel_obese = auto_select_model(ep_obese, build_weight_metrics("férfi", 175, 110), dose_number=3, has_previous_episode=False)
    assert sel_obese.recommended_model_key == "goti_2018"

    ep_hsct = _episode(hsct=True, hematology=True)
    sel_hsct = auto_select_model(ep_hsct, build_weight_metrics("férfi", 175, 80), dose_number=2, has_previous_episode=False)
    assert sel_hsct.recommended_model_key == "okada_2018"


def test_selector_dialysis_warning_path():
    ep = _episode(dialysis=True)
    sel = auto_select_model(ep, build_weight_metrics("férfi", 175, 80), dose_number=2, has_previous_episode=False)
    assert "Hemodialysis" in sel.rationale


def test_fit_engine_ranking_rmse_mae_and_combined_score():
    ep = _episode()
    ranking = fit_models(
        ep,
        MODELS,
        weights=build_weight_metrics("férfi", 175, 80),
        mic=1.0,
        prior_bonus={"goti_2018": 1.0},
        consistency_bonus={"goti_2018": 1.0},
    )
    assert len(ranking) >= 2
    assert ranking[0].rmse >= 0
    assert ranking[0].mae >= 0
    assert ranking[0].combined_score >= ranking[1].combined_score


def test_history_match_patient_id_and_name_and_antibiotic_filter():
    rows = [
        {"patient_id": "P-1", "drug": "Vancomycin", "inputs": {"patient_name": "Teszt Elek"}},
        {"patient_id": "P-2", "drug": "Vancomycin", "inputs": {"patient_name": "teszt   elek"}},
        {"patient_id": "P-1", "drug": "Linezolid", "inputs": {"patient_name": "Teszt Elek"}},
    ]
    by_id = find_matching_episode_history(rows, "P-1", "", "Vancomycin")
    by_name = find_matching_episode_history(rows, "", "teszt elek", "Vancomycin")
    assert len(by_id) == 1
    assert len(by_name) == 2


def test_recommendation_under_over_exposure_and_auc_mic():
    under = build_recommendation(auc24=300, trough=8, auc_mic=300, target_auc=500, persistent_underexposure=True, persistent_overexposure=False)
    over = build_recommendation(auc24=700, trough=25, auc_mic=700, target_auc=500, persistent_underexposure=False, persistent_overexposure=True)
    assert under.status == "Alulexpozíció"
    assert "alternatív antibiotikum" in under.text
    assert over.status == "Túlexpozíció"
    assert over.toxicity_risk == "emelkedett"


def test_engine_bayesian_path_contains_auto_select_and_fit_summary():
    result = calculate(
        VancomycinInputs(
            sex="férfi",
            age=60,
            weight_kg=80,
            scr_umol=100,
            dose_mg=1000,
            tau_h=12,
            tinf_h=1,
            c1=25,
            t1_start_h=2,
            c2=12,
            t2_start_h=10,
            method="Bayesian",
            patient_id="P-1",
            patient_name="Teszt Elek",
        )
    )
    assert result["auto_selection"]["recommended_model_key"]
    assert result["selected_model_key"]
    assert len(result["fit_summary"]) >= 2


def test_engine_trapezoid_override_does_not_crash_and_sets_explanation():
    result = calculate(
        VancomycinInputs(
            sex="férfi",
            age=60,
            weight_kg=80,
            scr_umol=100,
            dose_mg=1000,
            tau_h=12,
            tinf_h=1,
            c1=25,
            t1_start_h=2,
            c2=12,
            t2_start_h=10,
            method="Auto",
            selected_model_key="trapezoid_classic",
        )
    )
    assert result["selected_model_key"] == "trapezoid_classic"
    assert "Klasszikus trapezoid" in result["final_explanation"]


def test_engine_manual_model_override_is_reflected_in_selected_model():
    result = calculate(
        VancomycinInputs(
            sex="férfi",
            age=60,
            weight_kg=80,
            scr_umol=100,
            dose_mg=1000,
            tau_h=12,
            tinf_h=1,
            c1=25,
            t1_start_h=2,
            c2=12,
            t2_start_h=10,
            method="Bayesian",
            selected_model_key="thomson_2009",
        )
    )
    assert result["selected_model_key"] in ACTIVE_MODEL_KEYS


def test_active_model_registry_and_selector_are_limited_to_supported_r_models():
    active = active_models()
    keys = tuple(model.key for model in active)
    assert keys == ACTIVE_MODEL_KEYS
    sel = auto_select_model(_episode(icu=True), build_weight_metrics("férfi", 175, 80), dose_number=1, has_previous_episode=False)
    assert sel.recommended_model_key in ACTIVE_MODEL_KEYS
    assert set(sel.alternative_model_keys).issubset(set(ACTIVE_MODEL_KEYS))


def test_event_normalization_aliases():
    assert normalize_event_type("Sample") == "sample"
    assert normalize_event_type("trough_level") == "sample"
    assert normalize_event_type("loading dose") == "loading_dose"
    assert normalize_event_type("maintenance") == "maintenance_dose"
    assert normalize_event_type("supplemental_dose") == "extra_dose"
    assert normalize_event_type("extra dose") == "extra_dose"
    assert normalize_event_type("MIC result") == "mic_result"
    assert normalize_event_type("creatinine result") == "creatinine"
    assert normalize_event_type("scr") == "creatinine"


def test_workflow_loading_maintenance_extra_summary_and_plot():
    payload = {
        "sex": "férfi",
        "age": 60,
        "height_cm": 175,
        "weight_kg": 80,
        "scr_umol": 100,
        "dose_mg": 1000,
        "tau_h": 12,
        "tinf_h": 1,
        "c1": 24,
        "t1_h": 2,
        "c2": 12,
        "t2_h": 10,
        "episode_events": [
            {"event_type": "loading dose", "time_h": -12, "dose_mg": 1500, "tinf_h": 2},
            {"event_type": "maintenance", "time_h": 0, "dose_mg": 1000, "tinf_h": 1, "tau_h": 12},
            {"event_type": "extra_dose", "time_h": 6, "dose_mg": 250, "tinf_h": 1},
            {"event_type": "sample", "time_h": 2, "level_mg_l": 24},
            {"event_type": "sample", "time_h": 10, "level_mg_l": 12},
            {"event_type": "MIC result", "time_h": 0, "mic": 1.0},
            {"event_type": "creatinine result", "time_h": 0, "creatinine": 100},
        ],
    }
    result = run_vancomycin_workflow(payload, history_rows=[])
    assert result["event_summary"]["loading_dose_present"]
    assert result["event_summary"]["maintenance_dose_count"] >= 1
    assert result["event_summary"]["extra_dose_count"] >= 1
    assert result["event_summary"]["mic_present"]
    assert result["event_summary"]["creatinine_event_count"] >= 1
    assert len(result["plot"]["single_model"]["dose_events"]) >= 2


def test_workflow_insufficient_samples_returns_structured_error():
    payload = {
        "sex": "férfi",
        "age": 60,
        "height_cm": 175,
        "weight_kg": 80,
        "scr_umol": 100,
        "dose_mg": 1000,
        "tau_h": 12,
        "tinf_h": 1,
        "c1": 20,
        "t1_h": 2,
        "c2": 10,
        "t2_h": 10,
        "episode_events": [
            {"event_type": "maintenance_dose", "time_h": 0, "dose_mg": 1000, "tinf_h": 1},
            {"event_type": "sample", "time_h": 2, "level_mg_l": 20},
        ],
    }
    result = run_vancomycin_workflow(payload, history_rows=[])
    assert result["errors"]
    assert "legalább két érvényes mérési pont" in result["errors"][0]
    assert result["plot"]["errors"]
    assert result["plot"]["obs_y"]
    assert "dose_events" in result["plot"]


def test_workflow_parses_decimal_comma_samples_as_valid_numeric_points():
    payload = {
        "sex": "férfi",
        "age": 60,
        "height_cm": 175,
        "weight_kg": 80,
        "scr_umol": 100,
        "dose_mg": 1000,
        "tau_h": 12,
        "tinf_h": 1,
        "episode_events": [
            {"event_type": "maintenance_dose", "time_h": "0", "dose_mg": "1000", "tinf_h": "1"},
            {"event_type": "sample", "time_h": "2,0", "level_mg_l": "23,5"},
            {"event_type": "sample", "time_h": "10,0", "level_mg_l": "8,0"},
        ],
    }
    episode, summary = build_simple_episode(payload)
    sample_values = [e.value for e in episode.events if e.event_type == "sample"]
    assert summary["total_samples"] == 2
    assert sample_values == [23.5, 8.0]
    assert not any("nem numerikus érték" in msg for msg in summary["validation_warnings"])


def test_engine_missing_mic_has_explicit_auc_mic_status():
    result = calculate(
        VancomycinInputs(
            sex="férfi",
            age=60,
            weight_kg=80,
            scr_umol=100,
            dose_mg=1000,
            tau_h=12,
            tinf_h=1,
            c1=25,
            t1_start_h=2,
            c2=12,
            t2_start_h=10,
            mic=None,
            method="Bayesian",
        )
    )
    assert result["auc24"] > 0
    assert result["auc_mic"] is None
    assert "MIC nincs megadva" in result["auc_mic_status"]


def test_classical_path_plot_payload_keeps_legacy_keys():
    result = calculate(
        VancomycinInputs(
            sex="férfi",
            age=60,
            weight_kg=80,
            scr_umol=100,
            dose_mg=1000,
            tau_h=12,
            tinf_h=1,
            c1=25,
            t1_start_h=2,
            c2=12,
            t2_start_h=10,
            method="Klasszikus",
        )
    )
    plot = result["plot"]
    for key in ["title", "single_model", "model_averaging", "current_x", "current_y", "best_x", "best_y", "obs_x", "obs_y", "metadata", "warnings", "errors"]:
        assert key in plot
