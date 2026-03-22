from __future__ import annotations

import math
from dataclasses import dataclass

UMOL_PER_MGDL_CREATININE = 88.4


@dataclass(frozen=True)
class PKResult:
    peak: float
    trough: float
    auc24: float
    ke: float
    half_life: float


def parse_float(text: str, optional: bool = False) -> float | None:
    normalized = str(text).strip().replace(",", ".")
    if normalized == "":
        if optional:
            return None
        raise ValueError("Hiányzó numerikus érték.")
    return float(normalized)


def cockcroft_gault(age: float, sex: str, weight_kg: float, scr_mg_dl: float) -> float:
    crcl = ((140.0 - age) * weight_kg) / (72.0 * scr_mg_dl)
    if str(sex).strip().lower() == "nő":
        crcl *= 0.85
    return crcl


def posterior_blend(prior: float, observed: float, observed_weight: float) -> float:
    observed_weight = max(0.0, min(1.0, observed_weight))
    return prior * (1.0 - observed_weight) + observed * observed_weight


def predict_one_compartment(dose_mg: float, tau_h: float, tinf_h: float, cl_l_h: float, vd_l: float) -> PKResult:
    ke = cl_l_h / vd_l
    tinf_h = max(tinf_h, 0.5)
    rate = dose_mg / tinf_h
    peak = (rate / cl_l_h) * (1.0 - math.exp(-ke * tinf_h)) / (1.0 - math.exp(-ke * tau_h))
    trough = peak * math.exp(-ke * (tau_h - tinf_h))
    auc24 = dose_mg * (24.0 / tau_h) / cl_l_h
    return PKResult(peak=peak, trough=trough, auc24=auc24, ke=ke, half_life=math.log(2) / ke)


def validate_two_point_levels(c1: float | None, t1: float | None, c2: float | None, t2: float | None) -> None:
    if None in {c1, t1, c2, t2}:
        raise ValueError("Ehhez a módhoz legalább két koncentráció és két időpont kell.")
    if t2 <= t1:
        raise ValueError("A 2. mintavételnek később kell lennie, mint az 1.-nek.")
    if c1 <= 0 or c2 <= 0:
        raise ValueError("A koncentrációknak pozitívnak kell lenniük.")
    if c1 <= c2:
        raise ValueError("Az 1. szintnek magasabbnak kell lennie, mint a 2. szintnek.")
