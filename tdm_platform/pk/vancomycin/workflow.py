from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from tdm_platform.pk.vancomycin.domain import AntibioticEpisode, EpisodeEvent, Patient
from tdm_platform.pk.vancomycin.final_ranker import rank_final_model
from tdm_platform.pk.vancomycin.fit_engine import fit_models_with_debug
from tdm_platform.core.episode_history import find_patient_episodes, summarize_episodes_by_antibiotic
from tdm_platform.pk.vancomycin.model_library import active_models, get_model
from tdm_platform.pk.vancomycin.model_validation import filter_models_by_available_covariates
from tdm_platform.pk.vancomycin.recommendation_engine import build_recommendation
from tdm_platform.pk.vancomycin.selector import auto_select_model
from tdm_platform.pk.vancomycin.visualization_adapter import build_plot_payload
from tdm_platform.pk.vancomycin.weights import build_weight_metrics, crcl_from_metrics


EVENT_TYPE_ALIASES = {
    "sample": "sample",
    "level": "sample",
    "trough_level": "sample",
    "loading dose": "loading_dose",
    "loading_dose": "loading_dose",
    "maintenance": "maintenance_dose",
    "maintenance dose": "maintenance_dose",
    "maintenance_dose": "maintenance_dose",
    "extra_dose": "extra_dose",
    "extra dose": "extra_dose",
    "supplemental_dose": "extra_dose",
    "mic": "mic_result",
    "mic_result": "mic_result",
    "mic result": "mic_result",
    "creatinine": "creatinine",
    "creatinine result": "creatinine",
    "scr": "creatinine",
    "serum_creatinine": "creatinine",
}


def normalize_event_type(raw_event_type: object) -> str:
    key = str(raw_event_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    key = key.replace("__", "_")
    key_sp = key.replace("_", " ")
    return EVENT_TYPE_ALIASES.get(key, EVENT_TYPE_ALIASES.get(key_sp, key))


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_simple_episode(payload: dict) -> tuple[AntibioticEpisode, dict[str, Any]]:
    now = datetime.utcnow()
    validation_warnings: list[str] = []
    ignored_event_types: list[str] = []
    recognized_event_types: list[str] = []

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
    events: list[EpisodeEvent] = []
    raw_events = list(payload.get("episode_events") or [])
    if raw_events:
        for idx, raw in enumerate(raw_events):
            raw_event_type = str(raw.get("event_type", "")).strip()
            event_type = normalize_event_type(raw_event_type)
            recognized_event_types.append(event_type)
            t_from_start = _float_or_none(raw.get("time_h"))
            if t_from_start is None:
                validation_warnings.append(f"Esemény #{idx+1}: hibás time_h, alapértelmezett 0.0 került használatra.")
                t_from_start = 0.0
            value: float | None = None
            unit = "mg"
            if event_type == "sample":
                value = _float_or_none(raw.get("level_mg_l"))
                unit = "mg/L"
            elif event_type == "mic_result":
                value = _float_or_none(raw.get("mic"))
                unit = "mg/L"
            elif event_type == "creatinine":
                value = _float_or_none(raw.get("creatinine"))
                unit = "µmol/L"
            elif event_type in {"loading_dose", "maintenance_dose", "extra_dose"}:
                value = _float_or_none(raw.get("dose_mg"))
                unit = "mg"
            else:
                ignored_event_types.append(raw_event_type or "<empty>")
                validation_warnings.append(f"Esemény #{idx+1}: ismeretlen event_type='{raw_event_type}', kihagyva.")
                continue
            if value is None:
                validation_warnings.append(f"Esemény #{idx+1}: nem numerikus érték az event_type='{event_type}' eseménynél, kihagyva.")
                continue
            events.append(
                EpisodeEvent(
                    event_type=event_type,
                    timestamp=now + timedelta(hours=t_from_start),
                    value=value,
                    unit=unit,
                    payload={
                        "t_from_last_start_h": t_from_start,
                        "tinf_h": _float_or_none(raw.get("tinf_h", payload.get("tinf_h", 1.0))) or 1.0,
                        "tau_h": _float_or_none(raw.get("tau_h", payload.get("tau_h", 12.0))) or 12.0,
                    },
                )
            )
    else:
        events = [
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
        ]
    if payload.get("mic") is not None and not any(e.event_type == "mic_result" for e in events):
        events.append(EpisodeEvent(event_type="mic_result", timestamp=now, value=float(payload["mic"]), unit="mg/L"))

    event_summary = {
        "total_events": len(events),
        "total_samples": len([e for e in events if e.event_type == "sample"]),
        "total_dose_events": len([e for e in events if e.event_type in {"loading_dose", "maintenance_dose", "extra_dose"}]),
        "loading_dose_present": any(e.event_type == "loading_dose" for e in events),
        "maintenance_dose_count": len([e for e in events if e.event_type == "maintenance_dose"]),
        "extra_dose_count": len([e for e in events if e.event_type == "extra_dose"]),
        "mic_present": any(e.event_type == "mic_result" for e in events),
        "creatinine_event_count": len([e for e in events if e.event_type == "creatinine"]),
        "recognized_event_types": sorted(set(recognized_event_types)),
        "ignored_event_types": sorted(set(ignored_event_types)),
        "validation_warnings": validation_warnings,
    }
    episode = AntibioticEpisode(
        episode_id=str(payload.get("episode_id", "ep-current")),
        antibiotic="Vancomycin",
        patient=patient,
        events=tuple(events),
    )
    return episode, event_summary


def run_vancomycin_workflow(payload: dict, history_rows: list[dict] | None = None) -> dict:
    history_rows = history_rows or []
    warnings: list[str] = []
    errors: list[str] = []
    episode, event_summary = build_simple_episode(payload)
    warnings.extend(event_summary.get("validation_warnings", []))
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
    models_for_selection = active_models()
    active_model_keys = {model.key for model in models_for_selection}
    selection = auto_select_model(episode, weights, dose_number=dose_number, has_previous_episode=bool(previous))
    raw_selected_model = payload.get("selected_model_key")
    manual_model_key = str(raw_selected_model).strip() if raw_selected_model is not None else None
    if manual_model_key in {"", "None", "null"}:
        manual_model_key = None
    if manual_model_key and manual_model_key not in active_model_keys and manual_model_key != "trapezoid_classic":
        warnings.append(f"A kiválasztott modell nem aktív: {manual_model_key}; aktív modellkészlet használata.")
        manual_model_key = None
    if manual_model_key and manual_model_key != "trapezoid_classic":
        selection = replace(
            selection,
            recommended_model_key=manual_model_key,
            rationale=f"{selection.rationale} Manuális felülbírálás történt: {manual_model_key}.",
        )

    prior_bonus = {selection.recommended_model_key: 1.0}
    for idx, model_key in enumerate(selection.alternative_model_keys):
        prior_bonus[model_key] = max(0.3, 0.8 - idx * 0.15)
    if manual_model_key:
        prior_bonus[manual_model_key] = 1.2

    consistency_bonus = {}
    for row in previous:
        key = str(row.get("inputs", {}).get("selected_model_key", "")).strip()
        if key:
            consistency_bonus[key] = max(consistency_bonus.get(key, 0.4), 0.9)

    eligible_models, missing_covariates = filter_models_by_available_covariates(models_for_selection, episode, weights)
    fit_result = fit_models_with_debug(
        episode,
        eligible_models or models_for_selection,
        weights,
        mic=payload.get("mic"),
        prior_bonus=prior_bonus,
        consistency_bonus=consistency_bonus,
    )
    ranking = fit_result["ranking"]
    warnings.extend(fit_result.get("warnings", []))
    errors.extend(fit_result.get("errors", []))
    if not ranking:
        error_message = errors[0] if errors else "A modellillesztéshez legalább két érvényes mérési pont szükséges."
        times = tuple(float(e.payload.get("t_from_last_start_h", 0.0)) for e in episode.events if e.event_type == "sample")
        values = tuple(float(e.value) for e in episode.events if e.event_type == "sample" and isinstance(e.value, (int, float)))
        dose_events = tuple(e for e in episode.events if "dose" in e.event_type)
        print("[DEBUG][WORKFLOW] ranking length: 0")
        print("[DEBUG][WORKFLOW] event_summary:", event_summary)
        print("[DEBUG][WORKFLOW] fit_debug:", fit_result.get("debug", {}))
        print("[DEBUG][WORKFLOW] errors:", [error_message])
        print("[DEBUG][WORKFLOW] warnings:", warnings)
        return {
            "episode": episode,
            "weights": weights,
            "auto_selection": selection,
            "final": None,
            "recommendation": None,
            "plot": build_plot_payload(times, values, None, dose_events, metadata={"event_summary": event_summary}, warnings=warnings, errors=[error_message]),
            "best": None,
            "history_matches": previous,
            "history_matches_all_antibiotics": previous_all_antibiotics,
            "history_summary_by_antibiotic": summarize_episodes_by_antibiotic(previous_all_antibiotics),
            "missing_covariates": missing_covariates,
            "crcl": None,
            "event_summary": event_summary,
            "fit_debug": fit_result.get("debug", {}),
            "warnings": warnings,
            "errors": [error_message],
            "debug": {"ranking_length": 0},
        }

    if manual_model_key and manual_model_key != "trapezoid_classic":
        forced = next((fit for fit in ranking if fit.model_key == manual_model_key), None)
        if forced is not None:
            remaining = tuple(fit for fit in ranking if fit.model_key != manual_model_key)
            ranking = (forced, *remaining)

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
    plot = build_plot_payload(
        times,
        values,
        final,
        tuple(e for e in episode.events if "dose" in e.event_type),
        metadata={"event_summary": event_summary},
        warnings=warnings,
        errors=errors,
    )

    crcl = crcl_from_metrics(
        episode.patient.age,
        episode.patient.sex,
        episode.patient.scr_umol,
        weights,
        strategy=get_model(final.selected_model_key).weight_strategy_crcl,
    )
    print("[DEBUG][WORKFLOW] ranking length:", len(ranking))
    print("[DEBUG][WORKFLOW] event_summary:", event_summary)
    print("[DEBUG][WORKFLOW] fit_debug:", fit_result.get("debug", {}))
    print("[DEBUG][WORKFLOW] errors:", errors)
    print("[DEBUG][WORKFLOW] warnings:", warnings)

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
        "event_summary": event_summary,
        "fit_debug": fit_result.get("debug", {}),
        "warnings": warnings,
        "errors": errors,
        "debug": {"ranking_length": len(ranking)},
    }
