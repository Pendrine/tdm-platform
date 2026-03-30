import json
from pathlib import Path
from unittest.mock import patch

from tdm_platform.pk.vancomycin.r_backend_adapter import build_r_input, map_r_output_to_plot_payload, resolve_rscript_path, run_r_engine
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


def test_resolve_rscript_path_prefers_existing_env(monkeypatch, tmp_path: Path):
    fake = tmp_path / "Rscript.exe"
    fake.write_text("x", encoding="utf-8")
    monkeypatch.setenv("RSCRIPT_PATH", str(fake))
    resolved, err = resolve_rscript_path()
    assert err is None
    assert resolved == str(fake.resolve())


def test_resolve_rscript_path_errors_on_missing_env(monkeypatch):
    monkeypatch.setenv("RSCRIPT_PATH", "/definitely/missing/Rscript.exe")
    resolved, err = resolve_rscript_path()
    assert resolved is None
    assert "Configured RSCRIPT_PATH not found" in (err or "")


def test_resolve_rscript_path_falls_back_to_which(monkeypatch):
    monkeypatch.delenv("RSCRIPT_PATH", raising=False)
    with patch("tdm_platform.pk.vancomycin.r_backend_adapter.shutil.which", return_value="/usr/bin/Rscript"):
        resolved, err = resolve_rscript_path()
    assert err is None
    assert resolved


def test_run_r_engine_uses_resolved_rscript_in_command(monkeypatch, tmp_path: Path):
    script = tmp_path / "run_engine.R"
    script.write_text("placeholder", encoding="utf-8")
    fake_rscript = tmp_path / "Rscript.exe"
    fake_rscript.write_text("x", encoding="utf-8")
    monkeypatch.setenv("RSCRIPT_PATH", str(fake_rscript))

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(cmd, capture_output, text, check):
        out_path = Path(cmd[3])
        out_path.write_text(json.dumps({"status": "ok", "engine": "R_Bayesian", "model_key": "goti_2018"}), encoding="utf-8")
        return _Proc()

    with patch("tdm_platform.pk.vancomycin.r_backend_adapter.subprocess.run", side_effect=_fake_run):
        result = run_r_engine({"method": "Bayesian"}, r_script_path=script)
    assert result["status"] == "ok"
    assert result["debug"]["adapter_debug"]["command"][0] == str(fake_rscript.resolve())


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
    assert result["engine_source"] in {"R_BACKEND", "PYTHON_FALLBACK", "CLASSICAL_PYTHON"}


def test_bayesian_branch_not_classical_when_r_backend_ok():
    fake_r = {
        "status": "ok",
        "engine": "R_Bayesian",
        "model_key": "goti_2018",
        "auc24": 500.0,
        "auc_mic": 500.0,
        "predicted_peak": 30.0,
        "predicted_trough": 12.0,
        "posterior_cl_l_h": 5.0,
        "posterior_vd_l": 70.0,
        "curve": {"x": [0, 1], "y": [30, 20]},
        "observed": {"x": [1], "y": [22]},
        "dose_events": [],
        "warnings": [],
        "errors": [],
        "debug": {"selector_debug": {"manual": False}},
    }
    with patch("tdm_platform.pk.vancomycin_engine.run_r_engine", return_value=fake_r):
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
            )
        )
    assert result["engine_source"] == "R_BACKEND"
    assert result["used_r_backend"] is True
    assert result["fallback_used"] is False
    assert result["cl_l_h"] == 5.0
    assert result["vd_l"] == 70.0
    assert result["peak"] == 30.0
    assert result["trough"] == 12.0
    assert result["auc24"] == 500.0
    assert result["auc_mic"] == 500.0
    assert result["crcl"] is not None
    assert result["fit_summary"] == []


def test_bayesian_r_output_builds_complete_plot_payload():
    fake_r = {
        "status": "ok",
        "engine": "R_Bayesian",
        "model_key": "goti_2018",
        "auc24": 480.0,
        "auc_mic": None,
        "predicted_peak": 28.0,
        "predicted_trough": 11.0,
        "posterior_cl_l_h": 4.8,
        "posterior_vd_l": 65.0,
        "curve": {"x": [0, 6, 12], "y": [28, 17, 11]},
        "observed": {"x": [2, 10], "y": [24, 13]},
        "dose_events": [{"event_type": "maintenance_dose", "time": 0, "dose": 1000}],
        "warnings": [],
        "errors": [],
        "debug": {"selector_debug": {"manual": False}},
    }
    with patch("tdm_platform.pk.vancomycin_engine.run_r_engine", return_value=fake_r):
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
            )
        )
    plot = result["plot"]
    assert plot["single_model"]["pred_x"] == [0, 6, 12]
    assert plot["single_model"]["pred_y"] == [28, 17, 11]
    assert plot["single_model"]["obs_x"] == [2, 10]
    assert plot["single_model"]["obs_y"] == [24, 13]
    assert plot["dose_events"]
    assert plot["current_x"] == [0, 6, 12]
    assert plot["current_y"] == [28, 17, 11]
    assert plot["best_x"] == [0, 6, 12]
    assert plot["best_y"] == [28, 17, 11]
    assert plot["obs_x"] == [2, 10]
    assert plot["obs_y"] == [24, 13]
    assert "metadata" in plot
    assert "debug" in plot["metadata"]


def test_classical_branch_is_classical_python():
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
            method="Klasszikus",
        )
    )
    assert result["engine_source"] == "CLASSICAL_PYTHON"


def test_bayesian_with_selected_model_tries_r_backend():
    with patch("tdm_platform.pk.vancomycin_engine.run_r_engine", return_value={"status": "error", "errors": ["forced"], "warnings": [], "debug": {}}) as mocked:
        calculate(
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
    assert mocked.called


def test_bayesian_missing_rscript_sets_fallback_reason(monkeypatch):
    monkeypatch.setenv("RSCRIPT_PATH", "/definitely/missing/Rscript.exe")
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
        )
    )
    assert result["fallback_reason"] == "rscript_not_found_or_unresolved"
