import math
from dataclasses import dataclass

UMOL_PER_MGDL_CREATININE = 88.4
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

def cockcroft_gault(age: float, sex: str, weight_kg: float, scr_mg_dl: float) -> float:
    crcl = ((140.0 - age) * weight_kg) / (72.0 * scr_mg_dl)
    if sex == "nő":
        crcl *= 0.85
    return crcl

def calc_auc_trapezoid(inp: VancomycinInputs) -> dict:
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

def calculate(inp: VancomycinInputs) -> dict:
    base = calc_auc_trapezoid(inp)
    scr_mg_dl = inp.scr_umol / UMOL_PER_MGDL_CREATININE
    crcl = cockcroft_gault(inp.age, inp.sex, inp.weight_kg, scr_mg_dl)
    status = "Célzónában"
    if base["auc24"] < TARGET_AUC_LOW:
        status = "Alulexpozíció"
    elif base["auc24"] > TARGET_AUC_HIGH:
        status = "Túlexpozíció"
    auc_mic = None if inp.mic is None else base["auc24"] / inp.mic
    return {
        "status": status,
        "crcl": crcl,
        "auc24": base["auc24"],
        "trough": base["true_trough"],
        "peak": base["true_peak"],
        "cl_l_h": base["cl_l_h"],
        "vd_l": base["vd_l"],
        "half_life": base["half_life"],
        "auc_mic": auc_mic,
    }
