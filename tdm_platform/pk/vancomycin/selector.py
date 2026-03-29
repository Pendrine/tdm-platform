from __future__ import annotations

from tdm_platform.pk.vancomycin.domain import AntibioticEpisode, AutoSelectionResult, WeightMetrics
from tdm_platform.pk.vancomycin.model_library import MODELS


def auto_select_model(
    episode: AntibioticEpisode,
    weights: WeightMetrics,
    dose_number: int,
    has_previous_episode: bool,
) -> AutoSelectionResult:
    p = episode.patient
    rationale: list[str] = []
    if p.hemodialysis_flag:
        recommended = "okada_2018" if p.hsct_flag else "roberts_2011"
        rationale.append("Hemodialysis flag miatt fokozott óvatosság és kritikus populációs modell preferált.")
    elif p.hsct_flag:
        recommended = "okada_2018"
        rationale.append("HSCT flag alapján az Okada (2018) modell prioritást kap.")
    elif p.hematology_flag:
        recommended = "okada_2018"
        rationale.append("Hematológiai háttér miatt HSCT-hez közeli populációs modell ajánlott.")
    elif p.icu_flag and p.unstable_renal_flag:
        recommended = "roberts_2011"
        rationale.append("ICU + instabil vese miatt kritikus állapotú modell preferált.")
    elif p.icu_flag:
        recommended = "revilla_2010"
        rationale.append("ICU flag alapján ICU-populációs modell került előre.")
    elif weights.obesity_flag:
        recommended = "adane_2015"
        rationale.append("Obesity flag alapján obes modell előnyben.")
    else:
        recommended = "goti_2018"
        rationale.append("Általános hospitalizált populáció: Goti (2018) alapértelmezett.")

    bayesian_preferred = dose_number <= 2 or p.unstable_renal_flag or p.icu_flag
    trapezoid_eligible = dose_number >= 3 and not p.unstable_renal_flag
    if bayesian_preferred:
        rationale.append("Korai/instabil helyzet: Bayes ág preferált.")
    if not trapezoid_eligible:
        rationale.append("Klasszikus trapezoid csak stabilabb, későbbi mintavételnél javasolt.")

    alternatives = tuple(model.key for model in MODELS if model.key != recommended)[:3]
    if has_previous_episode:
        rationale.append("Előző azonos antibiotikum-epizód elérhető, konzisztencia pont is számolható.")

    return AutoSelectionResult(
        recommended_model_key=recommended,
        alternative_model_keys=alternatives,
        rationale=" ".join(rationale),
        bayesian_preferred=bayesian_preferred,
        trapezoid_eligible=trapezoid_eligible,
    )
