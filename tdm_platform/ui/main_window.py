from __future__ import annotations

import sys
from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import QApplication, QDialog

from tdm_platform.app_meta import APP_NAME
from tdm_platform.core.auth import UserStore, ensure_special_roles
from tdm_platform.core.history import HistoryStore
from tdm_platform.core.models import HistoryRecord, SMTPSettings
from tdm_platform.pk.amikacin_engine import calculate as calculate_amikacin
from tdm_platform.pk.linezolid_engine import calculate as calculate_linezolid
from tdm_platform.pk.vancomycin_engine import calculate as calculate_vancomycin
from tdm_platform.services.pdf_service import render_simple_report_pdf
from tdm_platform.services.smtp_service import SMTPSettingsStore, get_smtp_settings
from tdm_platform.ui.auth_dialog import AuthDialog
from tdm_platform.ui.components.status_bar import AppStatusBar
from tdm_platform.ui.history_tab import HistoryTabController

from legacy import tdm_platform_v0_9_3_beta_fixed as legacy_ui


def _smtp_as_legacy_dict() -> dict[str, object]:
    smtp = get_smtp_settings()
    return {
        "host": smtp.host,
        "port": smtp.port,
        "smtp_user": smtp.smtp_user,
        "smtp_pass": smtp.smtp_pass,
        "sender": smtp.sender,
        "use_starttls": smtp.use_starttls,
        "use_ssl": smtp.use_ssl,
    }


def _load_settings_file() -> dict[str, object]:
    smtp = SMTPSettingsStore().load()
    return {
        "smtp_host": smtp.host,
        "smtp_port": str(smtp.port),
        "smtp_user": smtp.smtp_user,
        "smtp_from": smtp.sender,
        "smtp_pass": smtp.smtp_pass,
        "smtp_starttls": "1" if smtp.use_starttls else "0",
        "smtp_ssl": "1" if smtp.use_ssl else "0",
    }


def _save_settings_file(settings: dict[str, object]) -> None:
    current = SMTPSettingsStore().load()
    SMTPSettingsStore().save(
        SMTPSettings(
            host=str(settings.get("smtp_host", current.host)).strip(),
            port=int(settings.get("smtp_port", current.port) or current.port),
            smtp_user=str(settings.get("smtp_user", current.smtp_user)).strip(),
            smtp_pass=str(settings.get("smtp_pass", current.smtp_pass)).strip(),
            sender=str(settings.get("smtp_from", current.sender)).strip(),
            use_starttls=str(settings.get("smtp_starttls", "1" if current.use_starttls else "0")).strip().lower() in {"1", "true", "yes", "on"},
            use_ssl=str(settings.get("smtp_ssl", "1" if current.use_ssl else "0")).strip().lower() in {"1", "true", "yes", "on"},
        )
    )


class MainWindow(legacy_ui.TDMMainWindow):
    """Main window facade with modular dependencies wired into the legacy UI."""

    def __init__(self, current_user: Optional[dict] = None):
        self._user_store = UserStore()
        self._history_store = HistoryStore()
        self._history_tab = HistoryTabController(self._history_store)
        super().__init__(current_user=current_user)
        self.setWindowTitle(APP_NAME)
        self.setStatusBar(AppStatusBar(self))

    def load_users(self) -> list[dict]:
        users = self._user_store.load()
        for user in users:
            user.setdefault("active", True)
            user.setdefault("username", str(user.get("email", "")).split("@")[0] if user.get("email") else "")
        return users

    def save_users(self):
        self._user_store.save(self.users_data)

    def load_history(self) -> list[dict]:
        return self._history_tab.load_rows()

    def save_history(self):
        self._history_tab.save_rows(self.history_data)

    def refresh_history_filter(self):
        if hasattr(self, "history_user_filter"):
            self._history_tab.refresh_filter(self.history_user_filter, self.history_data, self.current_user)

    def refresh_history_table(self):
        if hasattr(self, "history_table"):
            selected = self.history_user_filter.currentText() if self.history_user_filter.count() else "Összes"
            self._history_tab.populate_table(
                self.history_table,
                self.history_detail,
                self.history_data,
                selected_user=selected,
                current_user=self.current_user,
            )

    def show_history_detail(self):
        rows = self.history_table.property("history_rows") or []
        idx = self.history_table.currentRow()
        if 0 <= idx < len(rows):
            self._history_tab.render_detail(self.history_detail, rows[idx])

    def append_history_record(self, pk: dict, res: dict):
        record = HistoryRecord(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user=pk.get("user", ""),
            patient_id=pk.get("patient_id", ""),
            drug=res.get("drug", ""),
            method=res.get("method", ""),
            status=res.get("status", ""),
            regimen=res.get("regimen", ""),
            decision=pk.get("decision", ""),
            report=res.get("report", ""),
            inputs={
                "nem": pk.get("sex"),
                "életkor": pk.get("age"),
                "testsúly": pk.get("weight"),
                "magasság": pk.get("height"),
                "kreatinin_µmol/L": pk.get("scr_umol"),
                "MIC": pk.get("mic"),
                "adag_mg": pk.get("dose"),
                "intervallum_h": pk.get("tau"),
                "infúzió_h": pk.get("tinf"),
                "T1": pk.get("t1"),
                "C1": pk.get("c1"),
                "T2": pk.get("t2"),
                "C2": pk.get("c2"),
                "T3": pk.get("t3"),
                "C3": pk.get("c3"),
                "ICU": pk.get("icu"),
                "hematológia": pk.get("hematology"),
                "instabil_vese": pk.get("unstable_renal"),
                "obesitas": pk.get("obesity"),
                "neutropenia": pk.get("neutropenia"),
            },
        )
        self.history_data = self._history_store.append(record)
        self.refresh_history_filter()
        self.refresh_history_table()


def run_app() -> int:
    app = QApplication(sys.argv)
    auth = AuthDialog()
    if auth.exec() != QDialog.Accepted or not auth.current_user:
        return 0
    window = MainWindow(current_user=auth.current_user)
    window.show()
    return app.exec()


legacy_ui.ensure_special_roles = ensure_special_roles
legacy_ui.load_users_file = lambda: UserStore().load()
legacy_ui.save_users_file = lambda users: UserStore().save(users)
legacy_ui.load_settings_file = _load_settings_file
legacy_ui.save_settings_file = _save_settings_file
legacy_ui.get_smtp_settings = _smtp_as_legacy_dict
legacy_ui.render_simple_report_pdf = render_simple_report_pdf
legacy_ui.calculate_vancomycin = calculate_vancomycin
legacy_ui.calculate_linezolid = calculate_linezolid
legacy_ui.calculate_amikacin = calculate_amikacin
