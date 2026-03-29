from tdm_platform.pk.vancomycin.model_library import MODELS
from tdm_platform.pk.vancomycin_engine import VancomycinInputs, calculate


def test_model_dropdown_label_format_metadata_smoke():
    for model in MODELS:
        assert "—" in model.label
        assert "(" in model.label and ")" in model.label


def test_result_contains_single_and_model_averaging_data_for_ui():
    result = calculate(
        VancomycinInputs(
            sex="férfi",
            age=63,
            weight_kg=86,
            height_cm=178,
            scr_umol=110,
            dose_mg=1250,
            tau_h=12,
            tinf_h=1.5,
            c1=26,
            t1_start_h=2,
            c2=14,
            t2_start_h=10,
            method="Bayesian",
        )
    )
    # UI integration smoke: auto-select and ranking block data exists.
    assert result["auto_selection"]["rationale"]
    assert result["fit_summary"]
