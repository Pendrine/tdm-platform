from __future__ import annotations

from tdm_platform.pk.vancomycin.domain import EpisodeEvent, FinalModelDecision
from tdm_platform.pk.vancomycin.model_library import get_model


def build_plot_payload(
    observation_times: tuple[float, ...],
    observation_values: tuple[float, ...],
    final_decision: FinalModelDecision | None,
    dose_events: tuple[EpisodeEvent, ...],
    metadata: dict | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> dict:
    if final_decision is None:
        return {
            "title": "Vancomycin model fit",
            "single_model": None,
            "model_averaging": {"overlays": []},
            "current_x": list(observation_times),
            "current_y": [],
            "best_x": list(observation_times),
            "best_y": [],
            "obs_x": list(observation_times),
            "obs_y": list(observation_values),
            "metadata": metadata or {},
            "warnings": warnings or [],
            "errors": errors or ["Nincs elérhető végső modell döntés."],
        }
    single = final_decision.ranking[0]
    overlays = []
    for fit in final_decision.ranking[:4]:
        overlays.append(
            {
                "model_key": fit.model_key,
                "label": get_model(fit.model_key).label,
                "x": list(observation_times),
                "y": list(fit.predicted_concentrations),
                "weight": round(fit.combined_score, 4),
                "rmse": round(fit.rmse, 3),
                "mae": round(fit.mae, 3),
            }
        )

    dose_markers = [
        {
            "event_type": e.event_type,
            "time": e.payload.get("t_from_last_start_h", 0.0),
            "dose": e.value,
        }
        for e in dose_events
    ]

    return {
        "title": "Vancomycin model fit",
        "single_model": {
            "label": get_model(single.model_key).label,
            "obs_x": list(observation_times),
            "obs_y": list(observation_values),
            "pred_x": list(observation_times),
            "pred_y": list(single.predicted_concentrations),
            "dose_events": dose_markers,
            "fit": {"rmse": single.rmse, "mae": single.mae},
        },
        "model_averaging": {
            "overlays": overlays,
            "final_model": get_model(single.model_key).label,
            "obs_x": list(observation_times),
            "obs_y": list(observation_values),
        },
        # Legacy fallback keys:
        "current_x": list(observation_times),
        "current_y": list(single.predicted_concentrations),
        "best_x": list(observation_times),
        "best_y": list(final_decision.ranking[1].predicted_concentrations if len(final_decision.ranking) > 1 else single.predicted_concentrations),
        "obs_x": list(observation_times),
        "obs_y": list(observation_values),
        "metadata": metadata or {},
        "warnings": warnings or [],
        "errors": errors or [],
    }
