from __future__ import annotations

from tdm_platform.pk.vancomycin.domain import FinalModelDecision, FitResult
from tdm_platform.pk.vancomycin.model_library import get_model


def rank_final_model(ranking: tuple[FitResult, ...], clinical_expected_key: str) -> FinalModelDecision:
    if not ranking:
        raise ValueError("Nem áll rendelkezésre modellillesztési eredmény.")

    selected = ranking[0]
    expected_model = get_model(clinical_expected_key)
    selected_model = get_model(selected.model_key)

    if selected.model_key == clinical_expected_key:
        explanation = (
            f"A betegjellemzők és a fit eredmény konzisztens: a(z) {selected_model.label} modell lett kiválasztva "
            "a végső becsléshez."
        )
    else:
        explanation = (
            f"A klinikai prior alapján a(z) {expected_model.label} lenne várható, de a mért koncentrációk fit-je "
            f"a(z) {selected_model.label} modellhez illeszkedett jobban, ezért ezt választottuk végső modellnek."
        )

    return FinalModelDecision(selected_model_key=selected.model_key, ranking=ranking, explanation=explanation)
