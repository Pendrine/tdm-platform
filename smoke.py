from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from tdm_platform import app_meta
from tdm_platform.core.auth import UserStore, generate_temp_password, validate_doctor_email_value
from tdm_platform.core.history import HistoryStore
from tdm_platform.core.models import HistoryRecord, SMTPSettings
from tdm_platform.pk.amikacin_engine import AmikacinInputs, calculate as calculate_amikacin
from tdm_platform.pk.linezolid_engine import LinezolidInputs, calculate as calculate_linezolid
from tdm_platform.pk.vancomycin_engine import VancomycinInputs, calculate as calculate_vancomycin
from tdm_platform.services.pdf_service import _wrap_text
from tdm_platform.services.smtp_service import SMTPSettingsStore
from tdm_platform.storage.json_store import load_json_dict, save_json


class SmokeFailure(AssertionError):
    """Raised when a smoke check fails."""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def run_smoke() -> None:
    print("[smoke] starting checks")

    check(bool(app_meta.APP_VERSION), "APP_VERSION is empty")
    check(
        app_meta.APP_META.schema_version == app_meta.SCHEMA_VERSION,
        "APP_META schema version mismatch",
    )
    print("[smoke] app metadata ok")

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        users = UserStore(tmp_path / "users.json").load()
        check(any(user["role"] == "moderator" for user in users), "moderator user missing")
        check(
            validate_doctor_email_value("Visnyo.Adam@gmail.com") == "visnyo.adam@gmail.com",
            "doctor email normalization failed",
        )
        check(len(generate_temp_password()) == 12, "temporary password length mismatch")
        print("[smoke] auth storage ok")

        history_rows = HistoryStore(tmp_path / "history.json").append(
            HistoryRecord(
                timestamp="2026-03-22 12:00:00",
                user="doctor@example.com",
                patient_id="P-001",
                drug="Vancomycin",
                method="Klasszikus",
                status="Célzónában",
                regimen="1000 mg q12h",
                decision="Marad",
                report="OK",
            )
        )
        check(history_rows[0]["app_version"] == app_meta.APP_VERSION, "history app_version missing")
        check(history_rows[0]["schema_version"] == app_meta.SCHEMA_VERSION, "history schema_version missing")
        print("[smoke] history storage ok")

        settings_path = tmp_path / "settings.json"
        SMTPSettingsStore(settings_path).save(
            SMTPSettings(host="smtp.example.com", sender="tdm@example.com")
        )
        loaded_settings = SMTPSettingsStore(settings_path).load()
        check(loaded_settings.host == "smtp.example.com", "smtp host roundtrip failed")
        check(loaded_settings.sender == "tdm@example.com", "smtp sender roundtrip failed")
        print("[smoke] smtp settings ok")

        data_path = tmp_path / "data.json"
        save_json(data_path, {"a": 1})
        check(load_json_dict(data_path) == {"a": 1}, "json roundtrip failed")
        print("[smoke] json storage ok")

    wrapped = _wrap_text("a" * 160, width=40)
    check(len(wrapped) == 4, "pdf wrapping line count mismatch")
    check(all(len(line) <= 40 for line in wrapped), "pdf wrapping created oversized line")
    print("[smoke] pdf helpers ok")

    vancomycin = calculate_vancomycin(
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
    check(vancomycin["suggestion"]["best"]["dose"] > 0, "vancomycin suggestion missing")
    check(vancomycin["auc24"] > 0, "vancomycin auc24 invalid")
    print("[smoke] vancomycin engine ok")

    linezolid_quick = calculate_linezolid(
        LinezolidInputs(age=55, crcl=70, dose_mg=600, tau_h=12, tinf_h=1, c1=4.5, method="Gyors TDM")
    )
    linezolid_bayes = calculate_linezolid(
        LinezolidInputs(
            age=55,
            crcl=70,
            dose_mg=600,
            tau_h=12,
            tinf_h=1,
            c1=12,
            t1_h=2,
            c2=4,
            t2_h=10,
            method="Bayesian (általános)",
        )
    )
    check(linezolid_quick["status"] == "Célzónában", "linezolid quick mode failed")
    check(linezolid_bayes["auc24"] > 0, "linezolid bayesian auc24 invalid")
    print("[smoke] linezolid engine ok")

    amikacin = calculate_amikacin(
        AmikacinInputs(weight_kg=75, crcl=95, dose_mg=1500, tau_h=24, tinf_h=1, c1=40, t1_h=2, c2=5, t2_h=12)
    )
    check(amikacin["peak"] > amikacin["trough"], "amikacin peak/trough relationship invalid")
    check(amikacin["target_trough_max"] == 2.0, "amikacin target trough mismatch")
    print("[smoke] amikacin engine ok")

    print("[smoke] all checks passed")


if __name__ == "__main__":
    try:
        run_smoke()
    except SmokeFailure as exc:
        print(f"[smoke] FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
