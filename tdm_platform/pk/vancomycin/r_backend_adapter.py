from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _default_r_script_path() -> Path:
    return Path(__file__).resolve().parents[3] / "r_pk_engine" / "run_engine.R"


def resolve_rscript_path() -> tuple[str | None, str | None]:
    env_path = os.environ.get("RSCRIPT_PATH", "").strip()
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        if candidate.exists():
            return str(candidate), None
        return None, f"Configured RSCRIPT_PATH not found: {candidate}"
    which_path = shutil.which("Rscript")
    if which_path:
        return str(Path(which_path).resolve()), None
    local_app = os.environ.get("LOCALAPPDATA", "")
    candidates = []
    if local_app:
        candidates.extend(Path(local_app).glob("Programs/R/R-*/bin/Rscript.exe"))
    candidates.extend(Path("C:/Program Files/R").glob("R-*/bin/Rscript.exe"))
    for candidate in sorted(candidates, reverse=True):
        if candidate.exists():
            return str(candidate.resolve()), None
    return None, "Rscript executable not found (env/which/windows autodetect)."


def build_r_input(inp: Any) -> dict[str, Any]:
    return {
        "patient": {
            "id": inp.patient_id,
            "name": inp.patient_name,
            "sex": inp.sex,
            "age": inp.age,
            "weight_kg": inp.weight_kg,
            "height_cm": inp.height_cm,
            "scr_umol": inp.scr_umol,
            "icu": inp.icu,
            "hematology": inp.hematology,
            "hsct": inp.hsct,
            "unstable_renal": inp.unstable_renal,
            "hemodialysis": inp.hemodialysis,
        },
        "mic": inp.mic,
        "dose_number": inp.dose_number,
        "selected_model_key": inp.selected_model_key,
        "method": inp.method,
        "episode_events": inp.episode_events or [],
        "debug_enabled": True,
    }


def map_r_output_to_plot_payload(r_output: dict[str, Any]) -> dict[str, Any]:
    curve = r_output.get("curve", {}) or {}
    observed = r_output.get("observed", {}) or {}
    pred_x = list(curve.get("x", []) or [])
    pred_y = list(curve.get("y", []) or [])
    obs_x = list(observed.get("x", []) or [])
    obs_y = list(observed.get("y", []) or [])
    return {
        "title": "Vancomycin Bayesian (R backend)",
        "single_model": {
            "label": r_output.get("model_key", "bayesian_r"),
            "pred_x": pred_x,
            "pred_y": pred_y,
            "obs_x": obs_x,
            "obs_y": obs_y,
            "dose_events": r_output.get("dose_events", []) or [],
            "fit": {},
        },
        "model_averaging": {"overlays": []},
        "current_x": pred_x,
        "current_y": pred_y,
        "best_x": pred_x,
        "best_y": pred_y,
        "obs_x": obs_x,
        "obs_y": obs_y,
        "dose_events": r_output.get("dose_events", []) or [],
        "metadata": {"engine": "R_Bayesian", "debug": r_output.get("debug", {})},
        "warnings": r_output.get("warnings", []) or [],
        "errors": r_output.get("errors", []) or [],
    }


def run_r_engine(payload: dict[str, Any], r_script_path: Path | None = None) -> dict[str, Any]:
    script = r_script_path or _default_r_script_path()
    resolved_rscript, resolve_error = resolve_rscript_path()
    debug: dict[str, Any] = {
        "script_path": str(script),
        "env_rscript_path": os.environ.get("RSCRIPT_PATH", ""),
        "resolved_rscript_path": resolved_rscript,
        "resolved_rscript_exists": bool(resolved_rscript and Path(resolved_rscript).exists()),
        "command": [],
        "stdout": "",
        "stderr": "",
        "return_code": None,
        "input_summary": {"keys": sorted(payload.keys())},
    }
    print("[DEBUG][R_ADAPTER] env RSCRIPT_PATH:", debug["env_rscript_path"])
    print("[DEBUG][R_ADAPTER] resolved_rscript_path:", resolved_rscript)
    print("[DEBUG][R_ADAPTER] exists(resolved_rscript_path):", debug["resolved_rscript_exists"])
    if resolve_error:
        print("[DEBUG][R_ADAPTER] resolve_error:", resolve_error)
        return {
            "status": "error",
            "errors": [resolve_error],
            "warnings": [],
            "debug": debug,
            "error_code": "rscript_not_found_or_unresolved",
        }
    if not script.exists():
        print(f"[DEBUG][R_ADAPTER] script missing: {script}")
        return {"status": "error", "errors": [f"R script nem található: {script}"], "warnings": [], "debug": debug}
    with tempfile.TemporaryDirectory(prefix="tdm_r_engine_") as td:
        in_path = Path(td) / "input.json"
        out_path = Path(td) / "output.json"
        in_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        cmd = [str(resolved_rscript), str(script), str(in_path), str(out_path)]
        debug["command"] = cmd
        print("[DEBUG][R_ADAPTER] script_path:", script)
        print("[DEBUG][R_ADAPTER] command:", cmd)
        print("[DEBUG][R_ADAPTER] final command[0]:", cmd[0])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except Exception as exc:
            debug["stderr"] = str(exc)
            print("[DEBUG][R_ADAPTER] subprocess exception:", exc)
            return {"status": "error", "errors": [f"R futtatási hiba: {exc}"], "warnings": [], "debug": debug}
        debug["stdout"] = proc.stdout
        debug["stderr"] = proc.stderr
        debug["return_code"] = proc.returncode
        print("[DEBUG][R_ADAPTER] return_code:", proc.returncode)
        print("[DEBUG][R_ADAPTER] stdout:", proc.stdout)
        print("[DEBUG][R_ADAPTER] stderr:", proc.stderr)
        if proc.returncode != 0:
            return {"status": "error", "errors": [f"R backend return code: {proc.returncode}"], "warnings": [], "debug": debug}
        if not out_path.exists():
            return {"status": "error", "errors": ["R backend nem készített output JSON-t."], "warnings": [], "debug": debug}
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            print("[DEBUG][R_ADAPTER] parse_ok: True")
        except Exception as exc:
            print("[DEBUG][R_ADAPTER] parse_ok: False", exc)
            return {"status": "error", "errors": [f"R output parse hiba: {exc}"], "warnings": [], "debug": debug}
        data.setdefault("debug", {})
        data["debug"]["adapter_debug"] = debug
        print("[DEBUG][R_ADAPTER] output_status:", data.get("status"))
        print("[DEBUG][R_ADAPTER] output_engine:", data.get("engine"))
        print("[DEBUG][R_ADAPTER] output_model_key:", data.get("model_key"))
        return data
