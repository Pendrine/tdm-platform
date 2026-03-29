from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class WeightMetrics:
    tbw_kg: float
    ibw_kg: float
    adjbw_kg: float
    obesity_flag: bool


@dataclass(frozen=True)
class Patient:
    patient_id: str
    patient_name: str
    sex: str
    age: float
    height_cm: float
    tbw_kg: float
    scr_umol: float
    icu_flag: bool = False
    unstable_renal_flag: bool = False
    hematology_flag: bool = False
    hsct_flag: bool = False
    hemodialysis_flag: bool = False
    rass_score: float | None = None
    saspi_score: float | None = None


@dataclass(frozen=True)
class EpisodeEvent:
    event_type: str
    timestamp: datetime
    value: float | str | None = None
    unit: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AntibioticEpisode:
    episode_id: str
    antibiotic: str
    patient: Patient
    events: tuple[EpisodeEvent, ...]


@dataclass(frozen=True)
class ModelMetadata:
    key: str
    label: str
    population: str
    author: str
    year: int
    antibiotic: str
    compartments: int
    required_covariates: tuple[str, ...]
    weight_strategy_crcl: str
    weight_strategy_vd: str
    dialysis_warning: str | None = None
    optional_covariates: tuple[str, ...] = ()


@dataclass(frozen=True)
class AutoSelectionResult:
    recommended_model_key: str
    alternative_model_keys: tuple[str, ...]
    rationale: str
    bayesian_preferred: bool
    trapezoid_eligible: bool


@dataclass(frozen=True)
class FitResult:
    model_key: str
    predicted_concentrations: tuple[float, ...]
    residuals: tuple[float, ...]
    rmse: float
    mae: float
    cl_l_h: float
    vd_l: float
    auc24: float
    auc_mic: float | None
    fit_score: float
    clinical_prior_score: float
    plausibility_score: float
    consistency_score: float
    combined_score: float


@dataclass(frozen=True)
class FinalModelDecision:
    selected_model_key: str
    ranking: tuple[FitResult, ...]
    explanation: str


@dataclass(frozen=True)
class Recommendation:
    status: str
    toxicity_risk: str
    auc_mic_assessment: str
    text: str

