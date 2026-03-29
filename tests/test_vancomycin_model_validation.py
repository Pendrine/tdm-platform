from datetime import datetime

from tdm_platform.pk.vancomycin.domain import AntibioticEpisode, EpisodeEvent, Patient
from tdm_platform.pk.vancomycin.model_library import MODELS
from tdm_platform.pk.vancomycin.model_validation import filter_models_by_available_covariates
from tdm_platform.pk.vancomycin.weights import build_weight_metrics


def test_model_validation_filters_missing_covariates():
    patient = Patient(
        patient_id="P-1",
        patient_name="X",
        sex="férfi",
        age=55,
        height_cm=0,
        tbw_kg=80,
        scr_umol=100,
    )
    episode = AntibioticEpisode(
        episode_id="E1",
        antibiotic="Vancomycin",
        patient=patient,
        events=(EpisodeEvent("sample", datetime.utcnow(), 10.0, "mg/L", {"t_from_last_start_h": 2.0}),),
    )
    eligible, missing = filter_models_by_available_covariates(MODELS, episode, build_weight_metrics("férfi", 170, 80))
    assert len(eligible) >= 1
    assert isinstance(missing, dict)
