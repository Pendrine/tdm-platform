from __future__ import annotations

import math
from dataclasses import dataclass

from tdm_platform.pk.common import posterior_blend, predict_one_compartment, validate_two_point_levels


@dataclass
class LinezolidInputs:
    age: float
    crcl: float
    dose_mg: float
    tau_h: float
    tinf_h: float
    c1: float | None = None
    t1_h: float | None = None
    c2: float | None = None
    t2_h: float | None = None
    mic: float | None = None
    obesity: bool = False
    method: str = "Gyors TDM"


def calculate(inp: LinezolidInputs) -> dict:
    target_low, target_high = (2, 8) if inp.method != "Bayesian (hematológia)" else (2, 7)
    prior_cl = 4.8 if inp.method != "Bayesian (hematológia)" else 4.0
    if inp.crcl < 40:
        prior_cl *= 0.80
    if inp.age > 70:
        prior_cl *= 0.85
    prior_vd = 45 + (5 if inp.obesity else 0)

    if inp.method == "Gyors TDM":
        trough = inp.c1 if inp.c1 is not None else inp.c2
        if trough is None:
            raise ValueError("Gyors linezolid módhoz legalább egy trough szükséges.")
        auc24 = (inp.dose_mg * 24.0 / inp.tau_h) / prior_cl
        status = "Célzónában" if target_low <= trough <= target_high else ("Alulexpozíció" if trough < target_low else "Túlexpozíció")
        regimen = "600 mg q12h" if status == "Célzónában" else ("600 mg q8-12h" if status == "Alulexpozíció" else "600 mg q24h vagy 300 mg q12h")
        return {
            "status": status,
            "trough": trough,
            "auc24": auc24,
            "cl_l_h": prior_cl,
            "vd_l": prior_vd,
            "regimen": regimen,
        }

    validate_two_point_levels(inp.c1, inp.t1_h, inp.c2, inp.t2_h)
    ke_obs = math.log(inp.c1 / inp.c2) / (inp.t2_h - inp.t1_h)
    cl_obs = max(1.5, ke_obs * prior_vd)
    obs_w = 0.60 if inp.method == "Bayesian (általános)" else 0.50
    cl = posterior_blend(prior_cl, cl_obs, obs_w)
    vd = posterior_blend(prior_vd, cl_obs / ke_obs, 0.45)
    pred = predict_one_compartment(inp.dose_mg, inp.tau_h, inp.tinf_h, cl, vd)
    auc_mic = pred.auc24 / inp.mic if inp.mic else None
    status = "Célzónában" if target_low <= pred.trough <= target_high else ("Alulexpozíció" if pred.trough < target_low else "Túlexpozíció")
    return {
        "status": status,
        "trough": pred.trough,
        "peak": pred.peak,
        "auc24": pred.auc24,
        "auc_mic": auc_mic,
        "cl_l_h": cl,
        "vd_l": vd,
        "half_life": pred.half_life,
    }
