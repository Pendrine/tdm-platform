from __future__ import annotations

import math
from dataclasses import dataclass

from tdm_platform.pk.common import UMOL_PER_MGDL_CREATININE, cockcroft_gault, posterior_blend, predict_one_compartment, validate_two_point_levels
from tdm_platform.pk.vancomycin.weights import build_weight_metrics
from tdm_platform.pk.vancomycin.r_backend_adapter import build_r_input, map_r_output_to_plot_payload, run_r_engine
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
    episode_events: list[dict] | None = None


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


def build_classical_curve(inp: VancomycinInputs, base: dict) -> dict:
    tau_h = max(float(inp.tau_h), 1e-6)
    default_tinf_h = max(min(float(inp.tinf_h), tau_h), 1e-6)
    ke = max(float(base.get("ke") or 0.0), 1e-6)
    cl_l_h = max(float(base.get("cl_l_h") or 0.0), 1e-6)
    true_trough = max(float(base.get("true_trough") or 0.0), 0.0)

    n_points = 100
    dose_events: list[dict] = []
    for event in inp.episode_events or []:
        kind = str(event.get("event_type", "")).lower()
        if "dose" not in kind:
            continue
        try:
            t_h = float(event.get("time_h", 0.0))
        except (TypeError, ValueError):
            continue
        if t_h <= tau_h:
            dose_events.append(
                {
                    "time": t_h,
                    "event_type": kind or "maintenance_dose",
                    "dose": event.get("dose_mg", inp.dose_mg),
                    "tinf": event.get("tinf_h", inp.tinf_h),
                    "tau": inp.tau_h,
                    "event_datetime": event.get("event_datetime"),
                }
            )
    if not dose_events:
        dose_events.append(
            {
                "time": 0.0,
                "event_type": "maintenance_dose",
                "dose": inp.dose_mg,
                "tinf": default_tinf_h,
                "tau": inp.tau_h,
            }
        )
    dose_events = sorted(dose_events, key=lambda ev: float(ev.get("time", 0.0)))
    curve_start = min([0.0] + [float(ev.get("time", 0.0)) for ev in dose_events])
    pred_x = [curve_start + (tau_h - curve_start) * i / (n_points - 1) for i in range(n_points)]

    def _dose_contrib(t: float, dose: float, tinf: float, t0: float) -> float:
        if t <= t0:
            return 0.0
        r0 = dose / max(tinf, 1e-6)
        if t <= t0 + tinf:
            return (r0 / cl_l_h) * (1.0 - math.exp(-ke * (t - t0)))
        return (r0 / cl_l_h) * (1.0 - math.exp(-ke * tinf)) * math.exp(-ke * (t - t0 - tinf))

    raw_y: list[float] = []
    for t in pred_x:
        c = 0.0
        for ev in dose_events:
            d = max(float(ev.get("dose") or 0.0), 0.0)
            tinf = max(min(float(ev.get("tinf") or default_tinf_h), tau_h), 1e-6)
            t0 = float(ev.get("time", 0.0))
            c += _dose_contrib(t, d, tinf, t0)
        raw_y.append(max(0.0, c))

    t1 = float(inp.t1_start_h)
    t2 = float(inp.t2_start_h)
    c1 = max(float(inp.c1), 1e-9)
    c2 = max(float(inp.c2), 1e-9)

    def _interp(arr_x: list[float], arr_y: list[float], t: float) -> float:
        if t <= arr_x[0]:
            return arr_y[0]
        if t >= arr_x[-1]:
            return arr_y[-1]
        for i in range(1, len(arr_x)):
            if t <= arr_x[i]:
                x0, x1 = arr_x[i - 1], arr_x[i]
                y0, y1 = arr_y[i - 1], arr_y[i]
                ratio = (t - x0) / max(1e-9, (x1 - x0))
                return y0 + (y1 - y0) * ratio
        return arr_y[-1]

    r1 = max(_interp(pred_x, raw_y, t1), 1e-9)
    r2 = max(_interp(pred_x, raw_y, t2), 1e-9)
    use_correction = bool(r1 > 1e-6 and r2 > 1e-6 and abs(t2 - t1) > 1e-6)
    if use_correction:
        ln_corr1 = math.log(c1 / r1)
        ln_corr2 = math.log(c2 / r2)
        b_corr = (ln_corr1 - ln_corr2) / max(1e-9, (t1 - t2))
        a_corr = ln_corr1 + b_corr * t1
    else:
        a_corr = 0.0
        b_corr = 0.0
    pred_y: list[float] = []
    for raw, t in zip(raw_y, pred_x):
        if use_correction:
            exp_term = a_corr - b_corr * t
            exp_term = max(-12.0, min(12.0, exp_term))
            y_val = raw * math.exp(exp_term)
        else:
            y_val = raw
        pred_y.append(max(0.0, min(float(y_val), 1e6)))
    if not any(v > 0 for v in pred_y):
        pred_y = [max(0.0, min(v, 1e6)) for v in raw_y]

    obs_x = [float(inp.t1_start_h), float(inp.t2_start_h)]
    obs_y = [float(inp.c1), float(inp.c2)]
    curve_label = "Klasszikus trapezoid (first dose)" if int(inp.dose_number or 0) <= 1 else "Klasszikus trapezoid (steady-state)"
    print(
        "[DEBUG][ENGINE][CLASSIC] single_model dose_events:",
        [{"time": ev.get("time"), "event_type": ev.get("event_type"), "dose": ev.get("dose")} for ev in dose_events],
    )
    print(
        "[DEBUG][ENGINE][CLASSIC] pred range:",
        {"x_min": min(pred_x) if pred_x else None, "x_max": max(pred_x) if pred_x else None, "y_min": min(pred_y) if pred_y else None, "y_max": max(pred_y) if pred_y else None, "use_correction": use_correction},
    )
    return {
        "title": "Vancomycin klasszikus koncentráció-idő profil",
        "single_model": {
            "label": curve_label,
            "pred_x": pred_x,
            "pred_y": pred_y,
            "obs_x": obs_x,
            "obs_y": obs_y,
            "dose_events": dose_events,
            "fit": {"engine": "classical_piecewise"},
        },
        "model_averaging": {"overlays": []},
        "current_x": pred_x,
        "current_y": pred_y,
        "best_x": pred_x,
        "best_y": pred_y,
        "obs_x": obs_x,
        "obs_y": obs_y,
        "dose_events": dose_events,
        "metadata": {"mode": "trapezoid_classic", "start_concentration": true_trough if int(inp.dose_number or 0) > 1 else 0.0},
        "warnings": [],
        "errors": [],
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


def _extract_sample_points(inp: VancomycinInputs) -> list[tuple[float, float]]:
    samples: list[tuple[float, float]] = []
    for event in inp.episode_events or []:
        if str(event.get("event_type", "")).lower() != "sample":
            continue
        t_h = event.get("time_h")
        level = event.get("level_mg_l")
        if t_h is None or level is None:
            continue
        try:
            t_val = float(t_h)
            c_val = float(level)
        except (TypeError, ValueError):
            continue
        if t_val >= 0.0 and c_val > 0.0:
            samples.append((t_val, c_val))
    if len(samples) < 2:
        samples = [(float(inp.t1_start_h), float(inp.c1)), (float(inp.t2_start_h), float(inp.c2))]
    samples.sort(key=lambda item: item[0])
    return samples


def _ke_consistency_label(samples: list[tuple[float, float]]) -> str | None:
    if len(samples) < 3:
        return "not_available"
    (t1, c1), (t2, c2), (t3, c3) = samples[:3]
    if c1 <= 0 or c2 <= 0 or c3 <= 0 or t2 <= t1 or t3 <= t2:
        return "not_available"
    ke_1 = math.log(c1 / c2) / (t2 - t1)
    ke_2 = math.log(c2 / c3) / (t3 - t2)
    mean_ke = max(1e-6, (ke_1 + ke_2) / 2.0)
    rel_diff = abs(ke_1 - ke_2) / mean_ke
    if rel_diff <= 0.25:
        return "consistent"
    if rel_diff <= 0.5:
        return "borderline"
    return "inconsistent"


def _resolve_dose_number(inp: VancomycinInputs) -> int | None:
    if int(inp.dose_number or 0) > 0:
        return int(inp.dose_number)
    inferred = 0
    for event in inp.episode_events or []:
        kind = str(event.get("event_type", "")).lower()
        if "dose" in kind:
            inferred += 1
    return inferred or None


def _build_weight_metrics_payload(inp: VancomycinInputs, vd_l: float) -> dict:
    metrics = build_weight_metrics(inp.sex, inp.height_cm, inp.weight_kg)
    return {
        "abw_kg": metrics.tbw_kg,
        "ibw_kg": metrics.ibw_kg,
        "adjbw_kg": metrics.adjbw_kg,
        "obesity_by_weight_metric": metrics.obesity_flag,
        "vd_l_per_kg_actual": (vd_l / metrics.tbw_kg) if metrics.tbw_kg > 0 else None,
        "vd_l_per_kg_ideal": (vd_l / metrics.ibw_kg) if metrics.ibw_kg > 0 else None,
        "vd_l_per_kg_adjusted": (vd_l / metrics.adjbw_kg) if metrics.adjbw_kg > 0 else None,
    }


def _build_distribution_assessment(inp: VancomycinInputs, vd_l: float, crcl: float) -> dict:
    weights = _build_weight_metrics_payload(inp, vd_l)
    dose_number = _resolve_dose_number(inp)
    early_sampling_flag = float(inp.t1_start_h) <= float(inp.tinf_h) + 1.0
    clinical_flags = []
    if inp.icu:
        clinical_flags.append("icu")
    if inp.unstable_renal:
        clinical_flags.append("unstable_renal")
    if inp.hematology:
        clinical_flags.append("hematology")
    if inp.hsct:
        clinical_flags.append("hsct")
    if inp.obesity or bool(weights.get("obesity_by_weight_metric")):
        clinical_flags.append("obesity")
    if crcl >= 130:
        clinical_flags.append("arc")
    ke_consistency = _ke_consistency_label(_extract_sample_points(inp))

    reason_lines: list[str] = []
    red_flags: list[str] = []
    risk_score = 0
    vd_act = weights.get("vd_l_per_kg_actual")
    if vd_act is not None:
        if vd_act < 0.5:
            reason_lines.append("A Vd/ABW < 0.5 L/kg borderline/atípusos tartományba esik.")
            risk_score += 1
        elif vd_act <= 1.0:
            reason_lines.append("A Vd/ABW 0.5–1.0 L/kg tartományban van, ez klasszikus értelmezéshez elfogadható.")
        else:
            red_flags.append("A Vd/ABW > 1.0 L/kg, ami tágult eloszlási tér/komplex kinetika gyanúját támogatja.")
            risk_score += 3
    if dose_number is not None and dose_number < 4:
        red_flags.append("A klasszikus trapezoid megközelítés inkább legalább a 4. dózis után értelmezhető.")
        risk_score += 2
    elif dose_number is not None:
        reason_lines.append("A dózisszám (>=4) támogatja a klasszikus steady-state értelmezést.")
    if early_sampling_flag:
        red_flags.append("A korai mintavétel az eloszlási fázis hatását erősítheti, ezért az 1-kompartmentes közelítés bizonytalanabb lehet.")
        risk_score += 2
    if len(clinical_flags) >= 2:
        red_flags.append("Több klinikai komplexitási flag pozitív (pl. ICU/instabil vese/hematológia/HSCT/ARC/obesitas).")
        risk_score += 2
    elif len(clinical_flags) == 1:
        reason_lines.append(f"Klinikai komplexitási flag: {clinical_flags[0]}.")
        risk_score += 1
    if ke_consistency == "inconsistent":
        red_flags.append("A szakaszos eliminációs meredekségek eltérése miatt az egyetlen log-lineáris szakasz feltételezése gyengébb.")
        risk_score += 2
    elif ke_consistency == "borderline":
        reason_lines.append("A szakaszos meredekségek csak részben konzisztensen támogatják az 1-kompartmentes közelítést.")
        risk_score += 1

    if risk_score >= 5:
        confidence = "low"
    elif risk_score >= 2:
        confidence = "moderate"
    else:
        confidence = "high"
    complex_kinetics_suspected = confidence == "low" or (vd_act is not None and vd_act > 1.0) or len(clinical_flags) >= 2
    one_compartment_plausible = confidence != "low"

    return {
        "one_compartment_plausible": one_compartment_plausible,
        "confidence": confidence,
        "complex_kinetics_suspected": complex_kinetics_suspected,
        "reason_lines": reason_lines,
        "red_flags": red_flags,
        "supporting_metrics": {
            "vd_l_per_kg_actual": vd_act,
            "vd_l_per_kg_ideal": weights.get("vd_l_per_kg_ideal"),
            "vd_l_per_kg_adjusted": weights.get("vd_l_per_kg_adjusted"),
            "dose_number": dose_number,
            "early_sampling_flag": early_sampling_flag,
            "clinical_complexity_flags": clinical_flags,
            "ke_consistency": ke_consistency,
        },
    }


def _build_trapezoid_assessment(distribution_assessment: dict) -> dict:
    confidence = distribution_assessment.get("confidence")
    reasons = list(distribution_assessment.get("reason_lines", []))
    if confidence == "low":
        reasons.append("Komplex kinetika gyanúja miatt a klasszikus trapezoid közelítés korlátozott.")
    return {
        "recommended": confidence != "low",
        "confidence": confidence,
        "reason_lines": reasons,
    }


def _evaluate_pkpd_target(auc24: float, mic: float | None) -> dict:
    if mic is not None and mic > 0:
        auc_mic = auc24 / mic
        primary_met = auc_mic >= 400.0
        if not primary_met:
            status = "Alulexpozíció"
        elif auc24 > TARGET_AUC_HIGH:
            status = "Túlexpozíció"
        else:
            status = "Célzónában"
        return {
            "status": status,
            "target_basis": "auc_mic_primary",
            "primary_label": "AUC/MIC >= 400",
            "primary_attained": primary_met,
            "safety_label": "AUC24 400–600 (túlzott expozíció guardrail)",
            "safety_high": auc24 > TARGET_AUC_HIGH,
            "auc_mic": auc_mic,
        }
    status = "Célzónában"
    if auc24 < TARGET_AUC_LOW:
        status = "Alulexpozíció"
    elif auc24 > TARGET_AUC_HIGH:
        status = "Túlexpozíció"
    return {
        "status": status,
        "target_basis": "auc24_fallback",
        "primary_label": "AUC24 400–600",
        "primary_attained": TARGET_AUC_LOW <= auc24 <= TARGET_AUC_HIGH,
        "safety_label": "AUC24 400–600",
        "safety_high": auc24 > TARGET_AUC_HIGH,
        "auc_mic": None,
    }


def suggest_regimen(cl_l_h: float, vd_l: float, target_auc: float, crcl: float, rounding_mg: float, mic: float | None = None) -> dict:
    daily_needed = cl_l_h * target_auc
    candidates = []
    seen = set()
    intervals = sorted(set(practical_intervals_by_crcl(crcl) + [12, 24]))
    for tau in intervals:
        raw_dose = daily_needed * (tau / 24.0)
        for factor in (0.8, 1.0, 1.2):
            rounded_dose = max(rounding_mg, round((raw_dose * factor) / rounding_mg) * rounding_mg)
            key = (int(rounded_dose), int(tau))
            if key in seen:
                continue
            seen.add(key)
            tinf = infusion_time_from_dose_hours(rounded_dose)
            pred = predict_one_compartment(rounded_dose, tau, tinf, cl_l_h, vd_l)
            assessment = _evaluate_pkpd_target(pred.auc24, mic)
            auc_mic = assessment["auc_mic"]
            if mic is not None and mic > 0:
                target_gap = max(0.0, 400.0 - (auc_mic or 0.0))
                score = target_gap * 1.2
            else:
                auc_delta = abs(pred.auc24 - target_auc)
                score = auc_delta * 1.0
            if pred.trough < TARGET_TROUGH_LOW:
                score += (TARGET_TROUGH_LOW - pred.trough) * 6.0
            elif pred.trough > TARGET_TROUGH_HIGH:
                score += (pred.trough - TARGET_TROUGH_HIGH) * 9.0
            if pred.peak > 40:
                score += (pred.peak - 40.0) * 1.3
            if pred.auc24 > TARGET_AUC_HIGH:
                score += (pred.auc24 - TARGET_AUC_HIGH) * 0.35
            if mic is not None and mic > 0 and not assessment["primary_attained"] and pred.auc24 > TARGET_AUC_HIGH:
                score += 120.0
            if assessment["primary_attained"]:
                score -= 12.0
            candidates.append({
                "dose": rounded_dose,
                "tau": tau,
                "tinf": tinf,
                "auc24": pred.auc24,
                "peak": pred.peak,
                "trough": pred.trough,
                "auc_mic": auc_mic,
                "target_basis": assessment["target_basis"],
                "primary_target_met": assessment["primary_attained"],
                "toxicity_flag": pred.auc24 > TARGET_AUC_HIGH,
                "efficacy_toxicity_mismatch": bool(mic is not None and mic > 0 and not assessment["primary_attained"] and pred.auc24 > TARGET_AUC_HIGH),
                "score": score,
                "text": (
                    f"{rounded_dose:.0f} mg q{tau:.0f}h — prediktált AUC24: {pred.auc24:.1f}, "
                    f"trough: {pred.trough:.1f}, peak: {pred.peak:.1f}"
                    + (f", AUC/MIC: {auc_mic:.1f}" if auc_mic is not None else "")
                ),
            })
    candidates.sort(key=lambda item: item["score"])
    top_candidates = candidates[: max(3, min(6, len(candidates)))]
    return {"daily_needed": daily_needed, "best": top_candidates[0], "candidates": top_candidates}


def _build_toxicity_assessment(auc24: float, mic: float | None, target_assessment: dict) -> dict:
    auc24_over = auc24 > TARGET_AUC_HIGH
    mic_present = mic is not None and mic > 0
    primary_not_met = not bool(target_assessment.get("primary_attained"))
    mismatch = bool(mic_present and primary_not_met and auc24_over)
    lines: list[str] = []
    if auc24_over:
        lines.append("AUC24 > 600 mg·h/L, ami fokozott toxicitási kockázatra utal.")
    if mismatch:
        lines.append("A kívánt AUC/MIC célérték a jelen expozíció mellett sem teljesül megfelelően.")
        lines.append("További vancomycin expozíciónövelés várhatóan kedvezőtlen lehet.")
        lines.append("Más antibiotikum vagy alternatív terápiás stratégia mérlegelendő.")
    return {
        "toxicity_flag": auc24_over or mismatch,
        "auc24_overexposure": auc24_over,
        "efficacy_toxicity_mismatch": mismatch,
        "message_lines": lines,
        "consider_alternative_therapy": mismatch,
    }


def calculate(inp: VancomycinInputs) -> dict:
    print(f"[DEBUG][ENGINE] method={inp.method} selected_model_key={inp.selected_model_key}")
    if inp.t1_start_h <= inp.tinf_h:
        raise ValueError("Vancomycinnél az 1. minta az infúzió vége után legyen.")
    if inp.t2_start_h >= inp.tau_h:
        raise ValueError("Vancomycinnél a 2. minta a következő dózis előtt legyen (T2 < τ).")

    base = calc_auc_trapezoid(inp)
    if inp.method == "Bayesian":
        print("[DEBUG][ENGINE] ENGINE=R_BACKEND")
        r_payload = build_r_input(inp)
        r_out = run_r_engine(r_payload)
        if r_out.get("status") == "ok" and not r_out.get("errors"):
            scr_mg_dl = inp.scr_umol / UMOL_PER_MGDL_CREATININE
            crcl = cockcroft_gault(age=inp.age, sex=inp.sex, weight_kg=inp.weight_kg, scr_mg_dl=scr_mg_dl)
            cl_l_h = float(r_out.get("posterior_cl_l_h") or 0.0)
            vd_l = float(r_out.get("posterior_vd_l") or 0.0)
            peak = float(r_out.get("predicted_peak") or 0.0)
            trough = float(r_out.get("predicted_trough") or 0.0)
            auc24 = float(r_out.get("auc24") or 0.0)
            auc_mic = r_out.get("auc_mic")
            plot_payload = map_r_output_to_plot_payload(r_out)
            has_plot = bool(plot_payload.get("current_x") or plot_payload.get("obs_x"))
            print("[DEBUG][ENGINE] plot payload keys:", sorted(plot_payload.keys()))
            print("[DEBUG][ENGINE] plot single_model label:", (plot_payload.get("single_model") or {}).get("label"))
            print("[DEBUG][ENGINE] plot len(pred_y):", len((plot_payload.get("single_model") or {}).get("pred_y", []) or []))
            print("[DEBUG][ENGINE] plot len(obs_y):", len((plot_payload.get("single_model") or {}).get("obs_y", []) or []))
            target_assessment = _evaluate_pkpd_target(auc24, inp.mic)
            status = target_assessment["status"]
            toxicity_assessment = _build_toxicity_assessment(auc24, inp.mic, target_assessment)
            print(
                "[DEBUG][ENGINE] R mapped result keys:",
                sorted(["cl_l_h", "vd_l", "auc24", "auc_mic", "peak", "trough", "crcl"]),
            )
            print(
                "[DEBUG][ENGINE] R mapped values:",
                {
                    "cl_l_h": cl_l_h,
                    "vd_l": vd_l,
                    "crcl": crcl,
                    "auc24": auc24,
                    "has_plot": has_plot,
                    "used_r_backend": True,
                    "fallback_used": False,
                },
            )
            weight_metrics = _build_weight_metrics_payload(inp, vd_l)
            distribution_assessment = _build_distribution_assessment(inp, vd_l, crcl)
            trapezoid_assessment = _build_trapezoid_assessment(distribution_assessment)
            suggestion = suggest_regimen(cl_l_h, vd_l, inp.target_auc, crcl, inp.rounding_mg, inp.mic)
            if target_assessment["target_basis"] == "auc_mic_primary":
                trapezoid_assessment["reason_lines"].append("MIC rendelkezésre áll: elsődleges cél az AUC/MIC >= 400; az AUC24 főként túlzott expozíció guardrail.")
            else:
                trapezoid_assessment["reason_lines"].append("MIC hiányában az értékelés elsődlegesen AUC24 400–600 célablak alapján történik.")
            return {
                "status": status,
                "crcl": crcl,
                "auc24": auc24,
                "trough": trough,
                "peak": peak,
                "cl_l_h": cl_l_h,
                "vd_l": vd_l,
                "half_life": 0.0,
                "ke": 0.0,
                "auc_mic": auc_mic,
                "target_assessment": target_assessment,
                "toxicity_assessment": toxicity_assessment,
                "auc_mic_status": "AUC/MIC számolva." if auc_mic is not None else "AUC/MIC nem értékelhető, mert MIC nincs megadva.",
                "suggestion": suggestion,
                "regimen_options": suggestion.get("candidates", []),
                "weight_metrics": weight_metrics,
                "distribution_assessment": distribution_assessment,
                "trapezoid_assessment": trapezoid_assessment,
                "selected_model_key": str(r_out.get("model_key") or "goti_2018"),
                "auto_selection": {
                    "recommended_model_key": str(r_out.get("model_key") or "goti_2018"),
                    "alternative_model_keys": [],
                    "rationale": "Bayesian R backend selector",
                    "bayesian_preferred": True,
                    "trapezoid_eligible": False,
                },
                "fit_summary": [],
                "final_explanation": "Bayesian becslés R backenddel (MAP).",
                "history_summary_by_antibiotic": {},
                "missing_covariates": {},
                "plot": plot_payload,
                "classical_reference": base,
                "event_summary": {},
                "fit_debug": {},
                "warnings": r_out.get("warnings", []),
                "errors": r_out.get("errors", []),
                "debug": r_out.get("debug", {}),
                "uncertainty_note": r_out.get("uncertainty_note"),
                "engine": str(r_out.get("engine") or "R_Bayesian"),
                "engine_source": "R_BACKEND",
                "used_r_backend": True,
                "fallback_used": False,
                "fallback_reason": "",
            }
        # Fail-safe fallback to Python workflow path with explicit warning.
        fallback_reason_code = r_out.get("error_code") or (
            "rscript_not_found_or_unresolved" if any("RSCRIPT_PATH" in str(e) or "Rscript executable not found" in str(e) for e in (r_out.get("errors") or [])) else "r_backend_failed"
        )
        fallback_warning = f"R backend fallback: {', '.join(r_out.get('errors', []) or ['ismeretlen hiba'])}"
        print("[DEBUG][ENGINE] ENGINE=PYTHON_FALLBACK")
    else:
        print("[DEBUG][ENGINE] ENGINE=CLASSICAL_PYTHON")
        fallback_warning = None
        fallback_reason_code = ""
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
            "method": inp.method,
            "selected_model_key": inp.selected_model_key,
            "episode_events": inp.episode_events or [],
        },
        history_rows=inp.history_rows or [],
    )
    if workflow.get("errors") and not workflow.get("best"):
        raise ValueError(workflow["errors"][0])
    best = workflow["best"]
    auto = workflow["auto_selection"]
    classical_forced = inp.selected_model_key == "trapezoid_classic" or inp.method == "Klasszikus"
    classical_auto = (
        inp.method == "Auto"
        and not inp.selected_model_key
        and auto.trapezoid_eligible
        and not auto.bayesian_preferred
        and int(inp.dose_number or 0) >= 2
    )
    use_classical = classical_forced or classical_auto
    if use_classical:
        cl_used = base["cl_l_h"]
        vd_used = base["vd_l"]
        pred_peak = base["true_peak"]
        pred_trough = base["true_trough"]
        pred_auc24 = base["auc24"]
        pred_ke = base["ke"]
        pred_half_life = base["half_life"]
        selected_model_key = "trapezoid_classic"
        final_explanation = "Klasszikus trapezoid (steady-state) számítás kényszerítve; a végső PK értékek ezt a modellt követik."
        plot_payload = build_classical_curve(inp, base)
    else:
        cl_used = best.cl_l_h
        vd_used = best.vd_l
        pred_peak = max(best.predicted_concentrations)
        pred_trough = min(best.predicted_concentrations)
        pred_auc24 = best.auc24
        pred_ke = cl_used / vd_used
        pred_half_life = math.log(2) / pred_ke
        selected_model_key = workflow["final"].selected_model_key
        final_explanation = workflow["final"].explanation
        plot_payload = workflow.get("plot")
    crcl = workflow["crcl"]
    auto_selection = {
        "recommended_model_key": auto.recommended_model_key,
        "alternative_model_keys": list(auto.alternative_model_keys),
        "rationale": auto.rationale,
        "bayesian_preferred": auto.bayesian_preferred,
        "trapezoid_eligible": auto.trapezoid_eligible,
    }
    fit_summary = [
        {
            "model_key": fit.model_key,
            "rmse": fit.rmse,
            "mae": fit.mae,
            "combined_score": fit.combined_score,
            "cl_l_h": fit.cl_l_h,
            "vd_l": fit.vd_l,
            "auc24": fit.auc24,
            "auc_mic": fit.auc_mic,
        }
        for fit in workflow["final"].ranking
    ]
    history_summary_by_antibiotic = workflow.get("history_summary_by_antibiotic", {})
    missing_covariates = workflow.get("missing_covariates", {})

    target_assessment = _evaluate_pkpd_target(pred_auc24, inp.mic)
    status = target_assessment["status"]
    toxicity_assessment = _build_toxicity_assessment(pred_auc24, inp.mic, target_assessment)

    auc_mic = None if inp.mic is None else pred_auc24 / inp.mic
    auc_mic_status = "AUC/MIC nem értékelhető, mert MIC nincs megadva." if inp.mic is None else "AUC/MIC számolva."
    suggestion = suggest_regimen(cl_used, vd_used, inp.target_auc, crcl, inp.rounding_mg, inp.mic)
    weight_metrics = _build_weight_metrics_payload(inp, vd_used)
    distribution_assessment = _build_distribution_assessment(inp, vd_used, crcl)
    trapezoid_assessment = _build_trapezoid_assessment(distribution_assessment)
    if target_assessment["target_basis"] == "auc_mic_primary":
        trapezoid_assessment["reason_lines"].append("MIC rendelkezésre áll: elsődleges cél az AUC/MIC >= 400; az AUC24 főként túlzott expozíció guardrail.")
    else:
        trapezoid_assessment["reason_lines"].append("MIC hiányában az értékelés elsődlegesen AUC24 400–600 célablak alapján történik.")

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
        "target_assessment": target_assessment,
        "toxicity_assessment": toxicity_assessment,
        "auc_mic_status": auc_mic_status,
        "suggestion": suggestion,
        "regimen_options": suggestion.get("candidates", []),
        "weight_metrics": weight_metrics,
        "distribution_assessment": distribution_assessment,
        "trapezoid_assessment": trapezoid_assessment,
        "selected_model_key": selected_model_key,
        "auto_selection": auto_selection,
        "fit_summary": fit_summary,
        "final_explanation": final_explanation,
        "history_summary_by_antibiotic": history_summary_by_antibiotic,
        "missing_covariates": missing_covariates,
        "plot": plot_payload,
        "classical_reference": base,
        "event_summary": workflow.get("event_summary", {}),
        "fit_debug": workflow.get("fit_debug", {}),
        "warnings": (workflow.get("warnings", []) + ([fallback_warning] if fallback_warning else [])),
        "errors": workflow.get("errors", []),
        "debug": workflow.get("debug", {}),
        "engine": "Klasszikus_Python",
        "engine_source": "PYTHON_FALLBACK" if fallback_warning else "CLASSICAL_PYTHON",
        "used_r_backend": False,
        "fallback_used": bool(fallback_warning),
        "fallback_reason": fallback_reason_code or "",
    }
