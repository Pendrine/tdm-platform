from __future__ import annotations

from dataclasses import asdict

from tdm_platform.pk.vancomycin.domain import AntibioticEpisode, ModelMetadata, WeightMetrics


def validate_model_inputs(model: ModelMetadata, episode: AntibioticEpisode, weights: WeightMetrics) -> tuple[bool, tuple[str, ...]]:
    patient_payload = asdict(episode.patient)
    weight_payload = asdict(weights)
    merged = {**patient_payload, **weight_payload}

    missing: list[str] = []
    for covariate in model.required_covariates:
        value = merged.get(covariate)
        if value is None or value == "":
            missing.append(covariate)
    return (len(missing) == 0, tuple(missing))


def filter_models_by_available_covariates(
    models: tuple[ModelMetadata, ...],
    episode: AntibioticEpisode,
    weights: WeightMetrics,
) -> tuple[tuple[ModelMetadata, ...], dict[str, tuple[str, ...]]]:
    eligible: list[ModelMetadata] = []
    missing_map: dict[str, tuple[str, ...]] = {}
    for model in models:
        ok, missing = validate_model_inputs(model, episode, weights)
        if ok:
            eligible.append(model)
        else:
            missing_map[model.key] = missing
    return tuple(eligible), missing_map
