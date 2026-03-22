from __future__ import annotations

import math
from dataclasses import dataclass

from tdm_platform.pk.common import UMOL_PER_MGDL_CREATININE, cockcroft_gault, posterior_blend, predict_one_compartment, validate_two_point_levels

TARGET_AUC_LOW = 400.0
TARGET_AUC_HIGH = 600.0
TARGET_TROUGH_LOW = 10.0
TARGET_TROUGH_HIGH = 20.0


@dataclass
class VancomycinInputs:
    sex: str
    age: float
    weight_kg: float
    scr_umol: float
    dose_mg: float
    tau_h: float
    tinf_h: float
    c1: float
    t1_start_h: float
    c2: float
    t2_start_h: float
    target_auc: float = 500.0
    mic: float | None = None
    icu: bool = False
    obesity: bool = False
    unstable_renal: bool = False
    rounding_mg: float = 250.0
    method: str = "Klasszikus"


def calc_auc_trapezoid(inp: VancomycinInputs) -> dict[str, float]:
    validate_two_point_levels(inp.c1, inp.t1_start_h, inp.c2, inp.t2_start_h)
    ke = math.log(inp.c1 / inp.c2) / (inp.t2_start_h - inp.t1_start_h)
    true_peak = inp.c1 * math.exp(ke * (inp.t1_start_h - inp.tinf_h))
    true_trough = inp.c2 * math.exp(-ke * (inp.tau_h - inp.t2_start_h))
    auc_inf = inp.tinf_h * (true_trough + true_peak) / 2.0
    auc_elim = (true_peak - true_trough) / ke
    auc_tau = auc_inf + auc_elim
    auc24 = auc_tau * (24.0 / inp.tau_h)
    daily_dose = inp.dose_mg * (24.0 / inp.tau_h)
    cl_l_h = daily_dose / auc24
    vd_l = cl_l_h / ke
    half_life = math.log(2) / ke
    return {
        "ke": ke,
        "true_peak": true_peak,
        "true_trough": true_trough,
        "auc24": auc24,
        "cl_l_h": cl_l_h,
        "vd_l": vd_l,
        "half_life": half_life,
    }


def infusion_time_from_dose_hours(dose_mg: float) -> float:
    if dose_mg <= 1000:
        return 1.0
    if dose_mg <= 1500:
        return 1.5
    if dose_mg <= 2000:
        return 2.0
    return 2.5


def practical_intervals_by_crcl(crcl: float) -> list[int]:
    if crcl >= 80:
        return [8, 12]
    if crcl >= 40:
        return [12, 24]
    if crcl >= 20:
        return [24, 36, 48]
    return [48]


def suggest_regimen(cl_l_h: float, vd_l: float, target_auc: float, crcl: float, rounding_mg: float) -> dict:
    daily_needed = cl_l_h * target_auc
    candidates = []
    for tau in practical_intervals_by_crcl(crcl):
        raw_dose = daily_needed * (tau / 24.0)
        rounded_dose = max(rounding_mg, round(raw_dose / rounding_mg) * rounding_mg)
        tinf = infusion_time_from_dose_hours(rounded_dose)
        pred = predict_one_compartment(rounded_dose, tau, tinf, cl_l_h, vd_l)
        score = abs(pred.auc24 - target_auc)
        if pred.trough < TARGET_TROUGH_LOW:
            score += (TARGET_TROUGH_LOW - pred.trough) * 8.0
        elif pred.trough > TARGET_TROUGH_HIGH:
            score += (pred.trough - TARGET_TROUGH_HIGH) * 8.0
        candidates.append({
            "dose": rounded_dose,
            "tau": tau,
            "tinf": tinf,
            "auc24": pred.auc24,
            "peak": pred.peak,
            "trough": pred.trough,
            "score": score,
        })
    candidates.sort(key=lambda item: item["score"])
    return {"daily_needed": daily_needed, "best": candidates[0], "candidates": candidates}


def calculate(inp: VancomycinInputs) -> dict:
    if inp.t1_start_h <= inp.tinf_h:
        raise ValueError("Vancomycinnél az 1. minta az infúzió vége után legyen.")
    if inp.t2_start_h >= inp.tau_h:
        raise ValueError("Vancomycinnél a 2. minta a következő dózis előtt legyen (T2 < τ).")

    base = calc_auc_trapezoid(inp)
    scr_mg_dl = inp.scr_umol / UMOL_PER_MGDL_CREATININE
    crcl = cockcroft_gault(inp.age, inp.sex, inp.weight_kg, scr_mg_dl)
    cl_used = base["cl_l_h"]
    vd_used = base["vd_l"]
    pred_peak = base["true_peak"]
    pred_trough = base["true_trough"]
    pred_auc24 = base["auc24"]
    pred_ke = base["ke"]
    pred_half_life = base["half_life"]

    if inp.method != "Klasszikus":
        vd_prior = inp.weight_kg * (0.7 if inp.method == "Bayesian" else 0.9)
        if inp.obesity:
            vd_prior *= 1.15
        if inp.icu:
            vd_prior *= 1.10
        if inp.unstable_renal:
            vd_prior *= 1.08
        ke_obs = math.log(inp.c1 / inp.c2) / (inp.t2_start_h - inp.t1_start_h)
        cl_prior = max(1.0, crcl * 0.06)
        cl_obs = max(0.5, ke_obs * vd_prior)
        obs_weight = 0.65 if inp.method == "Bayesian" else 0.50
        cl_used = posterior_blend(cl_prior, cl_obs, obs_weight)
        vd_used = posterior_blend(vd_prior, cl_obs / ke_obs, 0.40)
        pred = predict_one_compartment(inp.dose_mg, inp.tau_h, inp.tinf_h, cl_used, vd_used)
        pred_peak = pred.peak
        pred_trough = pred.trough
        pred_auc24 = pred.auc24
        pred_ke = pred.ke
        pred_half_life = pred.half_life

    status = "Célzónában"
    if pred_auc24 < TARGET_AUC_LOW:
        status = "Alulexpozíció"
    elif pred_auc24 > TARGET_AUC_HIGH:
        status = "Túlexpozíció"
    auc_mic = None if inp.mic is None else pred_auc24 / inp.mic
    suggestion = suggest_regimen(cl_used, vd_used, inp.target_auc, crcl, inp.rounding_mg)
    return {
        "status": status,
        "crcl": crcl,
        "auc24": pred_auc24,
        "trough": pred_trough,
        "peak": pred_peak,
        "cl_l_h": cl_used,
        "vd_l": vd_used,
        "half_life": pred_half_life,
        "ke": pred_ke,
        "auc_mic": auc_mic,
        "suggestion": suggestion,
    }
