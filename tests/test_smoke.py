from pathlib import Path

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
import pytest


def test_smoke_import():
    assert app_meta.APP_VERSION
    assert app_meta.APP_META.schema_version == app_meta.SCHEMA_VERSION


def test_user_store_ensures_moderator(tmp_path: Path):
    store = UserStore(tmp_path / "users.json")
    users = store.load()
    assert any(user["role"] == "moderator" for user in users)
    assert validate_doctor_email_value("Visnyo.Adam@gmail.com") == "visnyo.adam@gmail.com"
    assert len(generate_temp_password()) == 12


def test_history_store_appends_metadata(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.json")
    rows = store.append(
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
    assert rows[0]["app_version"] == app_meta.APP_VERSION
    assert rows[0]["schema_version"] == app_meta.SCHEMA_VERSION


def test_settings_store_roundtrip(tmp_path: Path):
    path = tmp_path / "settings.json"
    SMTPSettingsStore(path).save(SMTPSettings(host="smtp.example.com", sender="tdm@example.com"))
    loaded = SMTPSettingsStore(path).load()
    assert loaded.host == "smtp.example.com"
    assert loaded.sender == "tdm@example.com"


def test_json_store_dict_roundtrip(tmp_path: Path):
    path = tmp_path / "data.json"
    save_json(path, {"a": 1})
    assert load_json_dict(path) == {"a": 1}


def test_pdf_wrap_text_breaks_long_lines():
    lines = _wrap_text("a" * 160, width=40)
    assert len(lines) == 4
    assert all(len(line) <= 40 for line in lines)


def test_vancomycin_engine_returns_suggestion():
    result = calculate_vancomycin(
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
    assert result["suggestion"]["best"]["dose"] > 0
    assert result["auc24"] > 0


def test_linezolid_engine_supports_quick_and_bayesian_modes():
    quick = calculate_linezolid(LinezolidInputs(age=55, crcl=70, dose_mg=600, tau_h=12, tinf_h=1, c1=4.5, method="Gyors TDM"))
    bayes = calculate_linezolid(
        LinezolidInputs(age=55, crcl=70, dose_mg=600, tau_h=12, tinf_h=1, c1=12, t1_h=2, c2=4, t2_h=10, method="Bayesian (általános)")
    )
    assert quick["status"] == "Célzónában"
    assert bayes["auc24"] > 0


def test_amikacin_engine_calculates_pk():
    result = calculate_amikacin(
        AmikacinInputs(weight_kg=75, crcl=95, dose_mg=1500, tau_h=24, tinf_h=1, c1=40, t1_h=2, c2=5, t2_h=12)
    )
    assert result["peak"] > result["trough"]
    assert result["target_trough_max"] == 2.0


def test_legacy_verification_email_reports_clear_smtp_auth_fallback(monkeypatch):
    legacy_app = pytest.importorskip("legacy.tdm_platform_v0_9_3_beta_fixed")
    monkeypatch.setattr(
        legacy_app,
        "get_smtp_settings",
        lambda: {
            "host": "smtp.example.com",
            "port": 587,
            "smtp_user": "doctor@example.com",
            "smtp_pass": "wrong-pass",
            "sender": "doctor@example.com",
            "use_ssl": False,
            "use_starttls": True,
        },
    )

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def ehlo(self):
            return None

        def starttls(self, context=None):
            return None

        def login(self, username, password):
            raise legacy_app.smtplib.SMTPAuthenticationError(535, b"5.7.8 authentication failed")

    monkeypatch.setattr(legacy_app.smtplib, "SMTP", FakeSMTP)
    ok, message = legacy_app.AuthDialog.send_verification_email(object(), "user@example.com", "ABC123")

    assert not ok
    assert "SMTP hitelesítés sikertelen" in message
    assert "ABC123" in message


def test_legacy_v092_verification_email_reports_clear_smtp_auth_fallback(monkeypatch):
    legacy_app = pytest.importorskip("legacy.tdm_platform_v0_9_3_beta_fixed")
    monkeypatch.setenv("TDM_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("TDM_SMTP_PORT", "587")
    monkeypatch.setenv("TDM_SMTP_USER", "doctor@example.com")
    monkeypatch.setenv("TDM_SMTP_PASS", "wrong-pass")
    monkeypatch.setenv("TDM_SMTP_FROM", "doctor@example.com")
    monkeypatch.setenv("TDM_SMTP_STARTTLS", "1")
    monkeypatch.setenv("TDM_SMTP_SSL", "0")

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def ehlo(self):
            return None

        def starttls(self, context=None):
            return None

        def login(self, username, password):
            raise legacy_app.smtplib.SMTPAuthenticationError(535, b"5.7.8 authentication failed")

    monkeypatch.setattr(legacy_app.smtplib, "SMTP", FakeSMTP)
    ok, message = legacy_app.AuthDialog.send_verification_email(object(), "user@example.com", "XYZ789")

    assert not ok
    assert "SMTP hitelesítés sikertelen" in message
    assert "XYZ789" in message
