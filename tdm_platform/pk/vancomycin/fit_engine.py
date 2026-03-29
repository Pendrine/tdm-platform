from __future__ import annotations

import math
from statistics import fmean

from tdm_platform.pk.common import predict_one_compartment
from tdm_platform.pk.vancomycin.domain import AntibioticEpisode, FitResult, ModelMetadata, WeightMetrics
from tdm_platform.pk.vancomycin.weights import crcl_from_metrics, weight_by_strategy


def _sample_points(episode: AntibioticEpisode) -> tuple[tuple[float, float], ...]:
    points: list[tuple[float, float]] = []
    for event in episode.events:
        if event.event_type == "sample" and isinstance(event.value, (float, int)):
            rel_h = float(event.payload.get("t_from_last_start_h", 0.0))
            points.append((rel_h, float(event.value)))
    return tuple(sorted(points, key=lambda item: item[0]))


def _predict_at_times(dose_mg: float, tau_h: float, tinf_h: float, cl_l_h: float, vd_l: float, times_h: tuple[float, ...]) -> tuple[float, ...]:
    steady = predict_one_compartment(dose_mg, tau_h, tinf_h, cl_l_h, vd_l)
    ke = steady.ke
    rate = dose_mg / max(tinf_h, 0.5)
    pred: list[float] = []
    for t in times_h:
        if t <= tinf_h:
            c = (rate / cl_l_h) * (1.0 - math.exp(-ke * t)) / (1.0 - math.exp(-ke * tau_h))
        else:
            c = steady.peak * math.exp(-ke * (t - tinf_h))
        pred.append(c)
    return tuple(pred)


def fit_models(
    episode: AntibioticEpisode,
    models: tuple[ModelMetadata, ...],
    weights: WeightMetrics,
    mic: float | None,
    prior_bonus: dict[str, float],
    consistency_bonus: dict[str, float],
) -> tuple[FitResult, ...]:
    sample_points = _sample_points(episode)
    if len(sample_points) < 2:
        return tuple()

    dose_event = next((e for e in episode.events if e.event_type in {"maintenance_dose", "loading_dose", "extra_dose"}), None)
    dose_mg = float(dose_event.value if dose_event and isinstance(dose_event.value, (int, float)) else 1000.0)
    tau_h = float(dose_event.payload.get("tau_h", 12.0) if dose_event else 12.0)
    tinf_h = float(dose_event.payload.get("tinf_h", 1.0) if dose_event else 1.0)

    times = tuple(point[0] for point in sample_points)
    observed = tuple(point[1] for point in sample_points)

    fitted: list[FitResult] = []
    for model in models:
        crcl = crcl_from_metrics(episode.patient.age, episode.patient.sex, episode.patient.scr_umol, weights, model.weight_strategy_crcl)
        base_cl = max(1.0, crcl * 0.06)
        vd_weight = weight_by_strategy(weights, model.weight_strategy_vd)
        base_vd = vd_weight * (0.75 if model.compartments >= 2 else 0.7)

        severity_factor = 1.0
        if episode.patient.icu_flag:
            severity_factor *= 0.95
        if episode.patient.unstable_renal_flag:
            severity_factor *= 0.9
        if "obese" in model.population.lower() and not weights.obesity_flag:
            severity_factor *= 0.92

        cl = base_cl * severity_factor
        vd = base_vd * (1.05 if episode.patient.icu_flag else 1.0)

        predicted = _predict_at_times(dose_mg, tau_h, tinf_h, cl, vd, times)
        residuals = tuple(o - p for o, p in zip(observed, predicted))
        rmse = math.sqrt(fmean(r * r for r in residuals))
        mae = fmean(abs(r) for r in residuals)
        auc24 = predict_one_compartment(dose_mg, tau_h, tinf_h, cl, vd).auc24
        auc_mic = None if mic is None or mic <= 0 else auc24 / mic
        fit_score = 1.0 / (1.0 + rmse + mae)
        clinical_prior_score = prior_bonus.get(model.key, 0.5)
        plausibility_score = max(0.0, 1.0 - abs(auc24 - 500.0) / 1000.0)
        consistency_score = consistency_bonus.get(model.key, 0.5)
        combined_score = 0.35 * clinical_prior_score + 0.35 * fit_score + 0.2 * plausibility_score + 0.1 * consistency_score

        fitted.append(
            FitResult(
                model_key=model.key,
                predicted_concentrations=predicted,
                residuals=residuals,
                rmse=rmse,
                mae=mae,
                cl_l_h=cl,
                vd_l=vd,
                auc24=auc24,
                auc_mic=auc_mic,
                fit_score=fit_score,
                clinical_prior_score=clinical_prior_score,
                plausibility_score=plausibility_score,
                consistency_score=consistency_score,
                combined_score=combined_score,
            )
        )

    return tuple(sorted(fitted, key=lambda item: item.combined_score, reverse=True))
