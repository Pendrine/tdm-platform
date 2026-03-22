from __future__ import annotations

import math
from dataclasses import dataclass

from tdm_platform.pk.common import posterior_blend, predict_one_compartment, validate_two_point_levels


@dataclass
class AmikacinInputs:
    weight_kg: float
    crcl: float
    dose_mg: float
    tau_h: float
    tinf_h: float
    c1: float
    t1_h: float
    c2: float
    t2_h: float
    method: str = "Extended-interval Bayesian"


def calculate(inp: AmikacinInputs) -> dict:
    validate_two_point_levels(inp.c1, inp.t1_h, inp.c2, inp.t2_h)
    vd_prior = inp.weight_kg * (0.30 if inp.method == "Konvencionális Bayesian" else 0.35)
    ke_obs = math.log(inp.c1 / inp.c2) / (inp.t2_h - inp.t1_h)
    cl_obs = max(0.5, ke_obs * vd_prior)
    cl_prior = inp.crcl * 0.06
    cl = posterior_blend(cl_prior, cl_obs, 0.60 if inp.method == "Extended-interval Bayesian" else 0.65)
    vd = posterior_blend(vd_prior, cl_obs / ke_obs, 0.45)
    pred = predict_one_compartment(inp.dose_mg, inp.tau_h, max(inp.tinf_h, 0.5), cl, vd)

    if inp.method == "Extended-interval Bayesian":
        target_peak = (50, 64)
        target_trough_max = 2.0
    else:
        target_peak = (20, 30)
        target_trough_max = 5.0

    status = (
        "Célzónában"
        if target_peak[0] <= pred.peak <= target_peak[1] and pred.trough <= target_trough_max
        else ("Alulexpozíció" if pred.peak < target_peak[0] else "Túlexpozíció")
    )
    return {
        "status": status,
        "peak": pred.peak,
        "trough": pred.trough,
        "auc24": pred.auc24,
        "cl_l_h": cl,
        "vd_l": vd,
        "half_life": pred.half_life,
        "target_peak": target_peak,
        "target_trough_max": target_trough_max,
    }
