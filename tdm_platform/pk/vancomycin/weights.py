from __future__ import annotations

from tdm_platform.pk.common import UMOL_PER_MGDL_CREATININE, cockcroft_gault
from tdm_platform.pk.vancomycin.domain import WeightMetrics


def _sex_norm(sex: str) -> str:
    value = str(sex).strip().lower()
    if value in {"female", "nő", "no", "woman"}:
        return "female"
    return "male"


def ideal_body_weight_kg(sex: str, height_cm: float) -> float:
    height_in = max(0.0, height_cm / 2.54)
    base = 45.5 if _sex_norm(sex) == "female" else 50.0
    return max(35.0, base + 2.3 * (height_in - 60.0))


def adjusted_body_weight_kg(tbw_kg: float, ibw_kg: float, factor: float = 0.4) -> float:
    return ibw_kg + factor * max(0.0, tbw_kg - ibw_kg)


def build_weight_metrics(sex: str, height_cm: float, tbw_kg: float) -> WeightMetrics:
    ibw = ideal_body_weight_kg(sex, height_cm)
    adjbw = adjusted_body_weight_kg(tbw_kg, ibw)
    obesity_flag = tbw_kg >= ibw * 1.2
    return WeightMetrics(tbw_kg=tbw_kg, ibw_kg=ibw, adjbw_kg=adjbw, obesity_flag=obesity_flag)


def weight_by_strategy(metrics: WeightMetrics, strategy: str) -> float:
    key = str(strategy).strip().lower()
    if key == "ibw":
        return metrics.ibw_kg
    if key in {"adjbw", "adjbw40", "adjusted"}:
        return metrics.adjbw_kg
    return metrics.tbw_kg


def crcl_from_metrics(age: float, sex: str, scr_umol: float, metrics: WeightMetrics, strategy: str = "tbw") -> float:
    scr_mg_dl = scr_umol / UMOL_PER_MGDL_CREATININE
    return cockcroft_gault(age=age, sex=sex, weight_kg=weight_by_strategy(metrics, strategy), scr_mg_dl=scr_mg_dl)
