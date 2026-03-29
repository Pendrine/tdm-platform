from __future__ import annotations

from datetime import datetime, timedelta

from tdm_platform.pk.vancomycin.domain import AntibioticEpisode, EpisodeEvent, Patient
from tdm_platform.pk.vancomycin.final_ranker import rank_final_model
from tdm_platform.pk.vancomycin.fit_engine import fit_models
from tdm_platform.core.episode_history import find_patient_episodes, summarize_episodes_by_antibiotic
from tdm_platform.pk.vancomycin.model_library import MODELS, get_model
from tdm_platform.pk.vancomycin.model_validation import filter_models_by_available_covariates
from tdm_platform.pk.vancomycin.recommendation_engine import build_recommendation
from tdm_platform.pk.vancomycin.selector import auto_select_model
from tdm_platform.pk.vancomycin.visualization_adapter import build_plot_payload
from tdm_platform.pk.vancomycin.weights import build_weight_metrics, crcl_from_metrics


def build_simple_episode(payload: dict) -> AntibioticEpisode:
    now = datetime.utcnow()
    patient = Patient(
        patient_id=str(payload.get("patient_id", "")).strip(),
        patient_name=str(payload.get("patient_name", "")).strip(),
        sex=str(payload["sex"]),
        age=float(payload["age"]),
        height_cm=float(payload.get("height_cm", 170.0)),
        tbw_kg=float(payload["weight_kg"]),
        scr_umol=float(payload["scr_umol"]),
        icu_flag=bool(payload.get("icu", False)),
        unstable_renal_flag=bool(payload.get("unstable_renal", False)),
        hematology_flag=bool(payload.get("hematology", False)),
        hsct_flag=bool(payload.get("hsct", False)),
        hemodialysis_flag=bool(payload.get("hemodialysis", False)),
        rass_score=payload.get("rass_score"),
        saspi_score=payload.get("saspi_score"),
    )
    events = (
        EpisodeEvent(
            event_type="maintenance_dose",
            timestamp=now,
            value=float(payload["dose_mg"]),
            unit="mg",
            payload={"tau_h": float(payload["tau_h"]), "tinf_h": float(payload["tinf_h"]), "t_from_last_start_h": 0.0},
        ),
        EpisodeEvent(
            event_type="sample",
            timestamp=now + timedelta(hours=float(payload["t1_h"])),
            value=float(payload["c1"]),
            unit="mg/L",
            payload={"t_from_last_start_h": float(payload["t1_h"])},
        ),
        EpisodeEvent(
            event_type="sample",
            timestamp=now + timedelta(hours=float(payload["t2_h"])),
            value=float(payload["c2"]),
            unit="mg/L",
            payload={"t_from_last_start_h": float(payload["t2_h"])},
        ),
    )
    if payload.get("mic") is not None:
        events += (
            EpisodeEvent(event_type="mic_result", timestamp=now, value=float(payload["mic"]), unit="mg/L"),
        )
    return AntibioticEpisode(
        episode_id=str(payload.get("episode_id", "ep-current")),
        antibiotic="Vancomycin",
        patient=patient,
        events=events,
    )


def run_vancomycin_workflow(payload: dict, history_rows: list[dict] | None = None) -> dict:
    history_rows = history_rows or []
    episode = build_simple_episode(payload)
    weights = build_weight_metrics(episode.patient.sex, episode.patient.height_cm, episode.patient.tbw_kg)
    previous = find_patient_episodes(
        history_rows,
        patient_id=episode.patient.patient_id,
        patient_name=episode.patient.patient_name,
        antibiotic=episode.antibiotic,
    )
    previous_all_antibiotics = find_patient_episodes(
        history_rows,
        patient_id=episode.patient.patient_id,
        patient_name=episode.patient.patient_name,
        antibiotic=None,
    )
    dose_number = int(payload.get("dose_number", 3))
    selection = auto_select_model(episode, weights, dose_number=dose_number, has_previous_episode=bool(previous))

    prior_bonus = {selection.recommended_model_key: 1.0}
    for idx, model_key in enumerate(selection.alternative_model_keys):
        prior_bonus[model_key] = max(0.3, 0.8 - idx * 0.15)

    consistency_bonus = {}
    for row in previous:
        key = str(row.get("inputs", {}).get("selected_model_key", "")).strip()
        if key:
            consistency_bonus[key] = max(consistency_bonus.get(key, 0.4), 0.9)

    eligible_models, missing_covariates = filter_models_by_available_covariates(MODELS, episode, weights)
    ranking = fit_models(
        episode,
        eligible_models or MODELS,
        weights,
        mic=payload.get("mic"),
        prior_bonus=prior_bonus,
        consistency_bonus=consistency_bonus,
    )
    if not ranking:
        raise ValueError("A modellillesztéshez legalább két mérési pont szükséges.")

    final = rank_final_model(ranking, clinical_expected_key=selection.recommended_model_key)
    best = ranking[0]
    trough = min(best.predicted_concentrations) if best.predicted_concentrations else 0.0
    recommendation = build_recommendation(
        auc24=best.auc24,
        trough=trough,
        auc_mic=best.auc_mic,
        target_auc=float(payload.get("target_auc", 500.0)),
        persistent_underexposure=len([r for r in previous if "Alulexpozíció" in str(r.get("status", ""))]) >= 2,
        persistent_overexposure=len([r for r in previous if "Túlexpozíció" in str(r.get("status", ""))]) >= 2,
    )

    times = tuple(float(e.payload.get("t_from_last_start_h")) for e in episode.events if e.event_type == "sample")
    values = tuple(float(e.value) for e in episode.events if e.event_type == "sample")
    plot = build_plot_payload(times, values, final, tuple(e for e in episode.events if "dose" in e.event_type))

    crcl = crcl_from_metrics(
        episode.patient.age,
        episode.patient.sex,
        episode.patient.scr_umol,
        weights,
        strategy=get_model(final.selected_model_key).weight_strategy_crcl,
    )

    return {
        "episode": episode,
        "weights": weights,
        "auto_selection": selection,
        "final": final,
        "recommendation": recommendation,
        "plot": plot,
        "best": best,
        "history_matches": previous,
        "history_matches_all_antibiotics": previous_all_antibiotics,
        "history_summary_by_antibiotic": summarize_episodes_by_antibiotic(previous_all_antibiotics),
        "missing_covariates": missing_covariates,
        "crcl": crcl,
    }
