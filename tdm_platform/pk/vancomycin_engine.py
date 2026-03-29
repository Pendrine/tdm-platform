from __future__ import annotations

import math
from dataclasses import dataclass

from tdm_platform.pk.common import UMOL_PER_MGDL_CREATININE, cockcroft_gault, posterior_blend, predict_one_compartment, validate_two_point_levels
from tdm_platform.pk.vancomycin.workflow import run_vancomycin_workflow

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
    hematology: bool = False
    hsct: bool = False
    hemodialysis: bool = False
    dose_number: int = 3
    height_cm: float = 170.0
    patient_id: str = ""
    patient_name: str = ""
    rounding_mg: float = 250.0
    method: str = "Klasszikus"
    selected_model_key: str | None = None
    rass_score: float | None = None
    saspi_score: float | None = None
    history_rows: list[dict] | None = None


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

    # Legacy-compatible branch for strict classical mode.
    base = calc_auc_trapezoid(inp)
    scr_mg_dl = inp.scr_umol / UMOL_PER_MGDL_CREATININE
    crcl = cockcroft_gault(inp.age, inp.sex, inp.weight_kg, scr_mg_dl)

    if inp.method == "Klasszikus":
        cl_used = base["cl_l_h"]
        vd_used = base["vd_l"]
        pred_peak = base["true_peak"]
        pred_trough = base["true_trough"]
        pred_auc24 = base["auc24"]
        pred_ke = base["ke"]
        pred_half_life = base["half_life"]
        selected_model_key = "trapezoid_classic"
        auto_selection = {
            "recommended_model_key": selected_model_key,
            "alternative_model_keys": [],
            "rationale": "Klasszikus kétszintes, steady-state trapezoid módszer.",
            "bayesian_preferred": False,
            "trapezoid_eligible": True,
        }
        fit_summary = []
        final_explanation = "A választott módszer klasszikus kétpontos trapezoid számítás volt."
        history_summary_by_antibiotic = {}
        missing_covariates = {}
    else:
        workflow = run_vancomycin_workflow(
            {
                "patient_id": inp.patient_id,
                "patient_name": inp.patient_name,
                "sex": inp.sex,
                "age": inp.age,
                "height_cm": inp.height_cm,
                "weight_kg": inp.weight_kg,
                "scr_umol": inp.scr_umol,
                "dose_mg": inp.dose_mg,
                "tau_h": inp.tau_h,
                "tinf_h": inp.tinf_h,
                "c1": inp.c1,
                "t1_h": inp.t1_start_h,
                "c2": inp.c2,
                "t2_h": inp.t2_start_h,
                "target_auc": inp.target_auc,
                "mic": inp.mic,
                "icu": inp.icu,
                "obesity": inp.obesity,
                "unstable_renal": inp.unstable_renal,
                "hematology": inp.hematology,
                "hsct": inp.hsct,
                "hemodialysis": inp.hemodialysis,
                "dose_number": inp.dose_number,
                "rass_score": inp.rass_score,
                "saspi_score": inp.saspi_score,
            },
            history_rows=inp.history_rows or [],
        )
        best = workflow["best"]
        cl_used = best.cl_l_h
        vd_used = best.vd_l
        pred_peak = max(best.predicted_concentrations)
        pred_trough = min(best.predicted_concentrations)
        pred_auc24 = best.auc24
        pred_ke = cl_used / vd_used
        pred_half_life = math.log(2) / pred_ke
        crcl = workflow["crcl"]
        selected_model_key = workflow["final"].selected_model_key
        auto_selection = {
            "recommended_model_key": workflow["auto_selection"].recommended_model_key,
            "alternative_model_keys": list(workflow["auto_selection"].alternative_model_keys),
            "rationale": workflow["auto_selection"].rationale,
            "bayesian_preferred": workflow["auto_selection"].bayesian_preferred,
            "trapezoid_eligible": workflow["auto_selection"].trapezoid_eligible,
        }
        fit_summary = [
            {
                "model_key": fit.model_key,
                "rmse": fit.rmse,
                "mae": fit.mae,
                "combined_score": fit.combined_score,
                "auc24": fit.auc24,
                "auc_mic": fit.auc_mic,
            }
            for fit in workflow["final"].ranking
        ]
        final_explanation = workflow["final"].explanation
        history_summary_by_antibiotic = workflow.get("history_summary_by_antibiotic", {})
        missing_covariates = workflow.get("missing_covariates", {})

    status = "Célzónában"
    if pred_auc24 < TARGET_AUC_LOW:
        status = "Alulexpozíció"
    elif pred_auc24 > TARGET_AUC_HIGH:
        status = "Túlexpozíció"

    auc_mic = None if inp.mic is None else pred_auc24 / inp.mic
    suggestion = suggest_regimen(cl_used, vd_used, inp.target_auc, crcl, inp.rounding_mg)

    vd_prior = inp.weight_kg * (0.7 if inp.method == "Bayesian" else 0.9)
    ke_obs = math.log(inp.c1 / inp.c2) / (inp.t2_start_h - inp.t1_start_h)
    cl_prior = max(1.0, crcl * 0.06)
    cl_obs = max(0.5, ke_obs * vd_prior)
    _ = posterior_blend(cl_prior, cl_obs, 0.6)

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
        "selected_model_key": selected_model_key,
        "auto_selection": auto_selection,
        "fit_summary": fit_summary,
        "final_explanation": final_explanation,
        "history_summary_by_antibiotic": history_summary_by_antibiotic,
        "missing_covariates": missing_covariates,
    }
