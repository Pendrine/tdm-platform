from __future__ import annotations

from tdm_platform.pk.vancomycin.domain import ModelMetadata

ACTIVE_MODEL_KEYS: tuple[str, ...] = ("goti_2018", "roberts_2011", "okada_2018")


MODELS: tuple[ModelMetadata, ...] = (
    ModelMetadata(
        key="goti_2018",
        label="Hospitalized — Goti (2018)",
        population="Hospitalized",
        author="Goti",
        year=2018,
        antibiotic="Vancomycin",
        compartments=2,
        required_covariates=("age", "sex", "scr_umol", "tbw_kg"),
        weight_strategy_crcl="adjbw",
        weight_strategy_vd="tbw",
        optional_covariates=("unstable_renal_flag",),
        status="active",
    ),
    ModelMetadata(
        key="thomson_2009",
        label="Hospitalized — Thomson (2009)",
        population="Hospitalized",
        author="Thomson",
        year=2009,
        antibiotic="Vancomycin",
        compartments=2,
        required_covariates=("age", "sex", "scr_umol", "tbw_kg"),
        weight_strategy_crcl="tbw",
        weight_strategy_vd="tbw",
        optional_covariates=("unstable_renal_flag",),
        status="experimental",
    ),
    ModelMetadata(
        key="adane_2015",
        label="Obese — Adane (2015)",
        population="Obese",
        author="Adane",
        year=2015,
        antibiotic="Vancomycin",
        compartments=2,
        required_covariates=("age", "sex", "scr_umol", "tbw_kg", "height_cm"),
        weight_strategy_crcl="adjbw",
        weight_strategy_vd="adjbw",
        optional_covariates=("obesity_flag",),
        status="experimental",
    ),
    ModelMetadata(
        key="revilla_2010",
        label="ICU patients — Revilla (2010)",
        population="ICU patients",
        author="Revilla",
        year=2010,
        antibiotic="Vancomycin",
        compartments=2,
        required_covariates=("age", "sex", "scr_umol", "tbw_kg", "icu_flag"),
        weight_strategy_crcl="adjbw",
        weight_strategy_vd="tbw",
        optional_covariates=("unstable_renal_flag",),
        status="experimental",
    ),
    ModelMetadata(
        key="roberts_2011",
        label="Critically ill — Roberts (2011)",
        population="Critically ill",
        author="Roberts",
        year=2011,
        antibiotic="Vancomycin",
        compartments=2,
        required_covariates=("age", "sex", "scr_umol", "tbw_kg", "icu_flag"),
        weight_strategy_crcl="adjbw",
        weight_strategy_vd="tbw",
        optional_covariates=("unstable_renal_flag",),
        status="active",
    ),
    ModelMetadata(
        key="mangin_2014",
        label="Critically ill — Mangin (2014)",
        population="Critically ill",
        author="Mangin",
        year=2014,
        antibiotic="Vancomycin",
        compartments=2,
        required_covariates=("age", "sex", "scr_umol", "tbw_kg", "icu_flag"),
        weight_strategy_crcl="adjbw",
        weight_strategy_vd="tbw",
        optional_covariates=("unstable_renal_flag",),
        status="experimental",
    ),
    ModelMetadata(
        key="okada_2018",
        label="Hematopoietic stem-cell transplant — Okada (2018)",
        population="Hematopoietic stem-cell transplant",
        author="Okada",
        year=2018,
        antibiotic="Vancomycin",
        compartments=2,
        required_covariates=("age", "sex", "scr_umol", "tbw_kg", "hsct_flag"),
        weight_strategy_crcl="adjbw",
        weight_strategy_vd="tbw",
        dialysis_warning="Hemodialysis esetén külön modell / manuális felülvizsgálat szükséges.",
        optional_covariates=("hemodialysis_flag", "rass_score", "saspi_score"),
        status="active",
    ),
)


def get_model(model_key: str) -> ModelMetadata:
    return next(model for model in MODELS if model.key == model_key)


def active_models() -> tuple[ModelMetadata, ...]:
    return tuple(model for model in MODELS if model.key in ACTIVE_MODEL_KEYS and model.status == "active")
