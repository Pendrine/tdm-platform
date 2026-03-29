from __future__ import annotations

from tdm_platform.pk.vancomycin.domain import Recommendation


def build_recommendation(
    auc24: float,
    trough: float,
    auc_mic: float | None,
    target_auc: float,
    persistent_underexposure: bool,
    persistent_overexposure: bool,
) -> Recommendation:
    status = "Célzónában"
    text_parts: list[str] = []

    if auc24 < 400:
        status = "Alulexpozíció"
        text_parts.append("Az expozíció valószínűleg alacsony, dózisemelés vagy rövidebb intervallum mérlegelhető.")
    elif auc24 > 600:
        status = "Túlexpozíció"
        text_parts.append("Az expozíció magas, dóziscsökkentés vagy hosszabb intervallum mérlegelendő.")
    else:
        text_parts.append("Az AUC24 a célzónához közeli tartományban van.")

    toxicity = "alacsony"
    if auc24 > 600 or trough > 20:
        toxicity = "emelkedett"
        text_parts.append("A nephrotoxicitás kockázata emelkedett (AUC/trough alapján).")

    auc_mic_assessment = "MIC hiányában nem értékelhető"
    if auc_mic is not None:
        auc_mic_assessment = "AUC/MIC cél teljesül" if auc_mic >= 400 else "AUC/MIC cél nem teljesül"
        text_parts.append(f"AUC/MIC értékelés: {auc_mic_assessment.lower()}.")

    if persistent_underexposure:
        text_parts.append("Tartós alulexpozíció esetén alternatív antibiotikum mérlegelése klinikailag indokolt lehet.")
    if persistent_overexposure:
        text_parts.append("Tartós túlexpozíció/toxicitási kockázat esetén alternatív szer mérlegelése óvatosan javasolható.")

    if target_auc and abs(auc24 - target_auc) > 80:
        text_parts.append("A cél AUC-tól való eltérés miatt rövid távú kontroll TDM javasolt.")

    return Recommendation(
        status=status,
        toxicity_risk=toxicity,
        auc_mic_assessment=auc_mic_assessment,
        text=" ".join(text_parts),
    )
