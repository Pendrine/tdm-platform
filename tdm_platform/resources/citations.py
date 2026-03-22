from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Citation:
    title: str
    journal: str
    year: str
    pmid: str = ""
    doi: str = ""
    note: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


EVIDENCE = {
    "Vancomycin": {
        "Klasszikus": [
            Citation(
                title="Therapeutic monitoring of vancomycin for serious MRSA infections: a revised consensus guideline and review",
                journal="Am J Health Syst Pharm",
                year="2020",
                pmid="32191793",
                note="AUC/MIC 400–600 cél; a klasszikus kétpontos számítás auditálható fallback.",
            )
        ],
        "Bayesian": [
            Citation(
                title="Therapeutic monitoring of vancomycin for serious MRSA infections: a revised consensus guideline and review",
                journal="Am J Health Syst Pharm",
                year="2020",
                pmid="32191793",
            ),
            Citation(
                title="Trough Concentration versus Ratio of Area Under the Curve to Minimum Inhibitory Concentration for Vancomycin Dosing",
                journal="Can J Hosp Pharm",
                year="2022",
                pmid="35387369",
            ),
        ],
    },
    "Linezolid": {
        "Gyors TDM": [
            Citation(
                title="Expert consensus statement on therapeutic drug monitoring and individualization of linezolid",
                journal="Front Public Health",
                year="2022",
                pmid="36033811",
            )
        ],
        "Bayesian (hematológia)": [
            Citation(
                title="Pharmacokinetics and hematologic toxicity of linezolid in children receiving anti-cancer chemotherapy",
                journal="J Antimicrob Chemother",
                year="2025",
                pmid="40698816",
            )
        ],
    },
    "Amikacin": {
        "Extended-interval Bayesian": [
            Citation(
                title="Population pharmacokinetic modeling and optimal sampling strategy for Bayesian estimation of amikacin exposure in critically ill septic patients",
                journal="Ther Drug Monit",
                year="2010",
                pmid="20962708",
                doi="10.1097/FTD.0b013e3181f675c2",
            ),
            Citation(
                title="A simulation study on model-informed precision dosing of amikacin in critically ill patients",
                journal="Br J Clin Pharmacol",
                year="2024",
                pmid="38304967",
            ),
        ],
    },
}
