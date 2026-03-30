import json
from pathlib import Path

from tdm_platform.pk.vancomycin.r_backend_adapter import build_r_input, map_r_output_to_plot_payload, run_r_engine
from tdm_platform.pk.vancomycin_engine import VancomycinInputs, calculate


def test_build_r_input_contains_canonical_event_types():
    inp = VancomycinInputs(
        sex="férfi",
        age=60,
        weight_kg=80,
        scr_umol=100,
        dose_mg=1000,
        tau_h=12,
        tinf_h=1,
        c1=25,
        t1_start_h=2,
        c2=12,
        t2_start_h=10,
        method="Bayesian",
        episode_events=[{"event_type": "maintenance_dose", "time_h": 0, "dose_mg": 1000}],
    )
    payload = build_r_input(inp)
    assert payload["method"] == "Bayesian"
    assert payload["episode_events"][0]["event_type"] == "maintenance_dose"


def test_run_r_engine_missing_script_returns_structured_error(tmp_path: Path):
    result = run_r_engine({"method": "Bayesian"}, r_script_path=tmp_path / "missing.R")
    assert result["status"] == "error"
    assert result["errors"]
    assert "debug" in result


def test_map_r_output_to_plot_payload_keeps_debug_and_curves():
    r_out = {
        "model_key": "goti_2018",
        "curve": {"x": [0, 1, 2], "y": [20, 15, 10]},
        "observed": {"x": [2], "y": [11]},
        "dose_events": [{"event_type": "maintenance_dose", "time": 0, "dose": 1000}],
        "warnings": ["w"],
        "errors": [],
        "debug": {"selector_debug": {}},
    }
    plot = map_r_output_to_plot_payload(r_out)
    assert plot["single_model"]["pred_y"]
    assert plot["metadata"]["debug"]
    assert "current_y" in plot


def test_bayesian_engine_falls_back_without_crashing():
    result = calculate(
        VancomycinInputs(
            sex="férfi",
            age=60,
            weight_kg=80,
            scr_umol=100,
            dose_mg=1000,
            tau_h=12,
            tinf_h=1,
            c1=25,
            t1_start_h=2,
            c2=12,
            t2_start_h=10,
            method="Bayesian",
            selected_model_key="goti_2018",
        )
    )
    # In CI env without Rscript, fallback still returns structured result.
    assert "warnings" in result
    assert "plot" in result
