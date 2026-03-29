from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
)
from shiboken6 import isValid
import plotly.graph_objects as go
import plotly.io as pio

from tdm_platform.app_meta import APP_NAME
from tdm_platform.core.auth import UserStore, ensure_special_roles
from tdm_platform.core.history import HistoryStore
from tdm_platform.core.models import HistoryRecord, SMTPSettings
from tdm_platform.core.permissions import is_primary_moderator
from tdm_platform.pk.amikacin_engine import calculate as calculate_amikacin
from tdm_platform.pk.linezolid_engine import calculate as calculate_linezolid
from tdm_platform.pk.vancomycin_engine import VancomycinInputs, calculate as calculate_vancomycin
from tdm_platform.services.pdf_service import render_simple_report_pdf
from tdm_platform.services.smtp_service import SMTPSettingsStore, get_smtp_settings
from tdm_platform.storage.paths import (
    StorageMigrationError,
    configure_storage_root,
    get_active_storage_root,
)
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
        self._configure_history_toolbar_buttons()
        self.setWindowTitle(APP_NAME)
        self.setStatusBar(AppStatusBar(self))

    def _configure_history_toolbar_buttons(self) -> None:
        if hasattr(self, "clear_form_btn"):
            self.clear_form_btn.setText("Űrlap betöltése")
        if hasattr(self, "save_history_changes_btn"):
            self.save_history_changes_btn.setText("Kijelölt sor frissítése")
        if hasattr(self, "delete_history_btn"):
            self.delete_history_btn.setText("Törlés")
        for name in ("reload_history_btn", "save_history_btn", "new_save_btn", "save_btn"):
            button = getattr(self, name, None)
            if button is not None:
                button.setVisible(False)
                button.setEnabled(False)

    def _rebind_storage_backed_stores(self) -> None:
        self._user_store = UserStore()
        self._history_store = HistoryStore()
        self._history_tab = HistoryTabController(self._history_store)

    def _build_settings_dialog_content(self, parent_widget):
        super()._build_settings_dialog_content(parent_widget)

        self._clear_storage_widget_refs()

        self.storage_box = QGroupBox("Adattárolási hely")
        storage_layout = QFormLayout(self.storage_box)

        self.storage_root_edit = QLineEdit()
        self.storage_root_edit.setReadOnly(True)
        self.storage_browse_btn = QPushButton("Tallózás")
        self.storage_browse_btn.clicked.connect(self._browse_storage_directory)
        self.storage_save_btn = QPushButton("Tárolási hely beállítása")
        self.storage_save_btn.clicked.connect(self._save_storage_directory)

        picker_row = QHBoxLayout()
        picker_row.addWidget(self.storage_root_edit)
        picker_row.addWidget(self.storage_browse_btn)

        storage_layout.addRow("Aktív storage root", picker_row)
        storage_layout.addRow("", self.storage_save_btn)

        parent_layout = parent_widget.layout()
        if parent_layout is not None:
            parent_layout.insertWidget(max(parent_layout.count() - 1, 0), self.storage_box)
        parent_widget.destroyed.connect(lambda *_: self._clear_storage_widget_refs())

        self._refresh_storage_controls()

    def refresh_settings_tab(self):
        super().refresh_settings_tab()
        self._refresh_storage_controls()

    def _refresh_storage_controls(self) -> None:
        if not self._storage_widgets_are_alive():
            return

        active_root = get_active_storage_root()
        self.storage_root_edit.setText(str(active_root))
        primary = is_primary_moderator(self.current_user)

        self.storage_box.setVisible(primary)
        self.storage_box.setEnabled(primary)

    def _storage_widgets_are_alive(self) -> bool:
        widgets = [
            getattr(self, "storage_box", None),
            getattr(self, "storage_root_edit", None),
            getattr(self, "storage_browse_btn", None),
            getattr(self, "storage_save_btn", None),
        ]
        return all(widget is not None and isValid(widget) for widget in widgets)

    def _clear_storage_widget_refs(self) -> None:
        self.storage_box = None
        self.storage_root_edit = None
        self.storage_browse_btn = None
        self.storage_save_btn = None

    def _browse_storage_directory(self) -> None:
        current = self.storage_root_edit.text().strip() or str(get_active_storage_root())
        directory = QFileDialog.getExistingDirectory(self, "Központi adattárolási hely kiválasztása", current)
        if directory:
            self.storage_root_edit.setText(directory)

    def _save_storage_directory(self) -> None:
        if not is_primary_moderator(self.current_user):
            QMessageBox.warning(self, "Jogosultság", "Az adattárolási helyet csak a főmoderátor módosíthatja.")
            return

        target_raw = self.storage_root_edit.text().strip()
        if not target_raw:
            QMessageBox.warning(self, "Adattárolás", "Adj meg egy célmappát az adattároláshoz.")
            return

        try:
            new_root = configure_storage_root(Path(target_raw))
        except StorageMigrationError as exc:
            QMessageBox.warning(self, "Adattárolási hiba", str(exc))
            return
        except Exception as exc:  # defensive fallback for GUI error message
            QMessageBox.warning(self, "Adattárolási hiba", f"Váratlan hiba történt: {exc}")
            return

        self._rebind_storage_backed_stores()
        self.users_data = ensure_special_roles(self.load_users())
        self.history_data = self.load_history()
        self.refresh_history_filter()
        self.refresh_history_table()
        self.refresh_settings_tab()

        QMessageBox.information(
            self,
            "Adattárolás",
            f"Az adattárolási hely frissítve lett: {new_root}\nA meglévő adatok átmásolása megtörtént.",
        )

    def load_users(self) -> list[dict]:
        users = self._user_store.load()
        for user in users:
            user.setdefault("active", True)
            user.setdefault("username", str(user.get("email", "")).split("@")[0] if user.get("email") else "")
        return users

    @staticmethod
    def _normalize_email(email: object) -> str:
        return str(email or "").strip().lower()

    def _username_for_email(self, email: object) -> str:
        normalized = self._normalize_email(email)
        for user in self.users_data:
            if self._normalize_email(user.get("email", "")) == normalized:
                username = str(user.get("username", "")).strip()
                if username:
                    return username
                break
        return normalized.split("@", 1)[0] if "@" in normalized else normalized

    def _display_name_for_user(self, user: Optional[dict]) -> str:
        if not user:
            return "—"
        username = str(user.get("username", "")).strip()
        if username:
            return username
        return self._username_for_email(user.get("email", ""))

    def save_users(self):
        self._user_store.save(self.users_data)

    def load_history(self) -> list[dict]:
        rows = self._history_tab.load_rows()
        return rows

    def save_history(self):
        self._history_tab.save_rows(self.history_data)

    def refresh_history_filter(self):
        if hasattr(self, "history_user_filter"):
            self._history_tab.refresh_filter(
                self.history_user_filter,
                self.history_data,
                self.current_user,
                username_resolver=self._username_for_email,
            )

    def refresh_history_table(self):
        if hasattr(self, "history_table"):
            selected = self.history_user_filter.currentData() if self.history_user_filter.count() else "all"
            self._history_tab.populate_table(
                self.history_table,
                self.history_detail,
                self.history_data,
                selected_user=selected,
                current_user=self.current_user,
                username_resolver=self._username_for_email,
            )

    def show_history_detail(self):
        rows = self.history_table.property("history_rows") or []
        idx = self.history_table.currentRow()
        if 0 <= idx < len(rows):
            self._history_tab.render_detail(self.history_detail, rows[idx], username_resolver=self._username_for_email)

    def update_user_status_ui(self):
        super().update_user_status_ui()
        if self.current_user and hasattr(self, "user_status_label"):
            role_txt = self.current_user.get("role", "orvos")
            username = self._display_name_for_user(self.current_user)
            self.user_status_label.setText(f"Bejelentkezve: {username} ({self.current_user.get('email','')}) – {role_txt}")

    def refresh_settings_tab(self):
        super().refresh_settings_tab()
        if self.current_user and hasattr(self, "settings_name_label"):
            self.settings_name_label.setText(self._display_name_for_user(self.current_user))

    def refresh_user_admin_tables(self):
        super().refresh_user_admin_tables()
        if not hasattr(self, "settings_users_table"):
            return
        for row in range(self.settings_users_table.rowCount()):
            email_item = self.settings_users_table.item(row, 1)
            if email_item is None:
                continue
            username_item = self.settings_users_table.item(row, 0)
            if username_item is None:
                continue
            username_item.setText(self._username_for_email(email_item.text()))

    def collect_common(self) -> dict:
        payload = super().collect_common()
        if self.current_user:
            payload["user"] = self._normalize_email(self.current_user.get("email", ""))
        return payload

    def load_selected_history_into_form(self):
        super().load_selected_history_into_form()
        rows = self.history_table.property("history_rows") or []
        idx = self.history_table.currentRow()
        if 0 <= idx < len(rows):
            selected_record_id = str(rows[idx].get("record_id", "")).strip()
            self.history_table.setProperty("selected_history_record_id", selected_record_id)
            print(f"[DEBUG][HISTORY] selected record_id={selected_record_id}")
        if hasattr(self, "tabs") and hasattr(self, "input_tab"):
            self.tabs.setCurrentWidget(self.input_tab)
            print("[DEBUG][HISTORY] switched to input tab")

    def _resolve_selected_history_record_for_update(self) -> dict:
        selected_record_id = str(self.history_table.property("selected_history_record_id") or "").strip()
        if not selected_record_id:
            rows = self.history_table.property("history_rows") or []
            idx = self.history_table.currentRow()
            if idx < 0 or idx >= len(rows):
                raise ValueError("Nincs kijelölt rekord. Válassz ki egy módosítandó sort.")
            selected_record_id = str(rows[idx].get("record_id", "")).strip()
            self.history_table.setProperty("selected_history_record_id", selected_record_id)
        persisted_ids = [str(item.get("record_id", "")).strip() for item in self.history_data if isinstance(item, dict)]
        print(f"[DEBUG][HISTORY] persisted record_ids={persisted_ids}")
        target = next((item for item in self.history_data if str(item.get("record_id", "")).strip() == selected_record_id), None)
        print(f"[DEBUG][HISTORY] target record found={'yes' if target is not None else 'no'}")
        if target is None:
            raise ValueError("A kijelölt rekord nem található a mentendő history listában.")
        return target

    def extract_editable_metadata_from_form(self) -> dict[str, object]:
        mic_raw = self.mic_edit.text().strip()
        if not mic_raw:
            mic_value = None
        else:
            try:
                mic_value = float(mic_raw.replace(",", "."))
            except ValueError as exc:
                raise ValueError("A MIC mezőben számérték szükséges.") from exc
        return {
            "patient_id": self.patient_edit.text().strip(),
            "decision": self.decision_edit.toPlainText().strip(),
            "mic": mic_value,
            "icu": self.icu_check.isChecked(),
            "hematology": self.hematology_check.isChecked(),
            "unstable_renal": self.unstable_renal_check.isChecked(),
            "obesity": self.obesity_check.isChecked(),
            "neutropenia": self.neutropenia_check.isChecked(),
        }

    def update_selected_history_from_form(self):
        try:
            if not self.current_user:
                raise ValueError("Előbb jelentkezz be.")
            rec = self._resolve_selected_history_record_for_update()
            print(f"[DEBUG][HISTORY] updating selected record_id={rec.get('record_id', '')}")

            rec_user = self._normalize_email(rec.get("user", ""))
            cur_user = self._normalize_email((self.current_user or {}).get("email", ""))
            role = str((self.current_user or {}).get("role", "")).strip().lower()
            can_edit_all = role in {"moderator", "infektologus"}
            if not can_edit_all and rec_user and rec_user != cur_user:
                raise ValueError("Csak a saját bejegyzésedet módosíthatod.")

            editable = self.extract_editable_metadata_from_form()
            print(f"[DEBUG][HISTORY] editable fields payload={editable}")
            print(f"[DEBUG][HISTORY] history record before update={rec}")

            rec["user"] = cur_user or rec_user
            rec["patient_id"] = editable["patient_id"]
            rec["decision"] = editable["decision"]

            inputs = dict(rec.get("inputs") or {})
            inputs["MIC"] = editable["mic"]
            inputs["ICU"] = editable["icu"]
            inputs["hematológia"] = editable["hematology"]
            inputs["instabil_vese"] = editable["unstable_renal"]
            inputs["obesitas"] = editable["obesity"]
            inputs["neutropenia"] = editable["neutropenia"]
            rec["inputs"] = inputs
            print(f"[DEBUG][HISTORY] history record after update={rec}")

            self.save_history()
            print("[DEBUG][HISTORY] history persisted to storage")
            self.history_data = self.load_history()
            print(f"[DEBUG][HISTORY] history reloaded from storage rows={len(self.history_data)}")
            self.refresh_history_filter()
            self.refresh_history_table()
            QMessageBox.information(self, "Előző mérések", "A kijelölt bejegyzés frissítve lett.")
        except Exception as exc:
            QMessageBox.warning(self, "Frissítési hiba", str(exc))

    def logout_user(self):
        self.logout_to_login()

    def logout_to_login(self):
        confirm = QMessageBox.question(
            self,
            "Kijelentkezés",
            "Biztosan kijelentkezel?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.current_user = None
        self.update_user_status_ui()
        self.refresh_history_table()
        self.hide()
        auth = AuthDialog()
        if auth.exec() == QDialog.Accepted and auth.current_user:
            self.current_user = dict(auth.current_user)
            self.users_data = ensure_special_roles(self.load_users())
            self.history_data = self.load_history()
            self.refresh_history_filter()
            self.refresh_history_table()
            self.update_user_status_ui()
            self.show()
            return
        QApplication.instance().quit()


    def render_plot(self, spec: dict):
        if spec.get("single_model") and spec.get("model_averaging"):
            single = spec["single_model"]
            avg = spec["model_averaging"]
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=single["pred_x"], y=single["pred_y"], mode="lines", name=f"Single: {single['label']}"))
            fig.add_trace(go.Scatter(x=single["obs_x"], y=single["obs_y"], mode="markers", name="Observed", marker=dict(size=10)))
            for overlay in avg.get("overlays", []):
                fig.add_trace(
                    go.Scatter(
                        x=overlay["x"],
                        y=overlay["y"],
                        mode="lines",
                        name=f"Avg {overlay['label']} (w={overlay['weight']:.2f})",
                        line=dict(width=1, dash="dot"),
                        opacity=0.6,
                    )
                )
            fig.update_layout(
                title=f"{spec.get('title', 'Vancomycin')} — Single model + Model averaging",
                xaxis_title="Óra",
                yaxis_title="Koncentráció (mg/L)",
                template="plotly_white",
                margin=dict(l=30, r=30, t=50, b=30),
            )
            self.plot_view.setHtml(pio.to_html(fig, include_plotlyjs="cdn", full_html=False))
            return
        return super().render_plot(spec)

    def calc_vancomycin(self, pk: dict, method: str) -> dict:
        result = calculate_vancomycin(
            VancomycinInputs(
                sex=str(pk["sex"]),
                age=float(pk["age"]),
                weight_kg=float(pk["weight"]),
                scr_umol=float(pk["scr_umol"]),
                dose_mg=float(pk["dose"]),
                tau_h=float(pk["tau"]),
                tinf_h=float(pk["tinf"]),
                c1=float(pk["c1"]),
                t1_start_h=float(pk["t1"]),
                c2=float(pk["c2"]),
                t2_start_h=float(pk["t2"]),
                target_auc=float(pk.get("target_auc", 500.0)),
                mic=pk.get("mic"),
                icu=bool(pk.get("icu")),
                obesity=bool(pk.get("obesity")),
                unstable_renal=bool(pk.get("unstable_renal")),
                hematology=bool(pk.get("hematology")),
                patient_id=str(pk.get("patient_id", "")),
                method=method,
                height_cm=float(pk.get("height", 170.0)),
                history_rows=self.history_data,
            )
        )

        auto = result.get("auto_selection", {})
        fit_summary = result.get("fit_summary", [])
        fit_lines = [
            f"- {item['model_key']}: RMSE {item['rmse']:.2f}, MAE {item['mae']:.2f}, score {item['combined_score']:.3f}"
            for item in fit_summary[:5]
        ]
        history_summary = result.get("history_summary_by_antibiotic", {})
        history_text = ", ".join(f"{k}: {v}" for k, v in history_summary.items()) if history_summary else "nincs korábbi epizód"

        report = [
            f"VANCOMYCIN – {method}",
            "",
            "Auto-select",
            f"- Ajánlott modell: {auto.get('recommended_model_key', '-')}",
            f"- Alternatívák: {', '.join(auto.get('alternative_model_keys', [])) if auto.get('alternative_model_keys') else 'nincs'}",
            f"- Bayesian preferált: {'igen' if auto.get('bayesian_preferred') else 'nem'}",
            f"- Trapezoid használható: {'igen' if auto.get('trapezoid_eligible') else 'nem'}",
            f"- Indoklás: {auto.get('rationale', '-')}",
            "",
            "PK/PD",
            f"- AUC24: {result['auc24']:.1f} mg·h/L",
            f"- AUC/MIC: {'n.a.' if result['auc_mic'] is None else format(result['auc_mic'], '0.1f')}",
            f"- Peak: {result['peak']:.1f} mg/L | Trough: {result['trough']:.1f} mg/L",
            f"- CL: {result['cl_l_h']:.2f} L/h | Vd: {result['vd_l']:.2f} L | CrCl: {result['crcl']:.1f} mL/perc",
            "",
            "Final ranker",
            f"- Kiválasztott modell: {result.get('selected_model_key', '-')}",
            f"- Magyarázat: {result.get('final_explanation', '-')}",
            "",
            "Model fit rangsor",
            *(fit_lines or ["- nincs modellillesztési adat"]),
            "",
            "Előzmény panel (minden antibiotikum)",
            f"- Korábbi epizódok: {history_text}",
            "",
            "Recommendation",
            f"- Státusz: {result['status']}",
            f"- Javasolt séma: {result['suggestion']['best']['dose']:.0f} mg q{result['suggestion']['best']['tau']:.0f}h",
        ]

        plot = result.get("plot") or {
            "title": "Vancomycin koncentráció-idő profil",
            "current_x": [pk["t1"], pk["t2"]],
            "current_y": [result["peak"], result["trough"]],
            "best_x": [pk["t1"], pk["t2"]],
            "best_y": [result["peak"], result["trough"]],
            "obs_x": [pk["t1"], pk["t2"]],
            "obs_y": [pk["c1"], pk["c2"]],
        }

        return {
            "drug": "Vancomycin",
            "method": method,
            "status": result["status"],
            "primary": f"AUC24 {result['auc24']:.1f}",
            "secondary": f"CL {result['cl_l_h']:.2f} L/h",
            "regimen": f"{result['suggestion']['best']['dose']:.0f} mg q{result['suggestion']['best']['tau']:.0f}h",
            "status_sub": auto.get("rationale", result["status"]),
            "report": "\n".join(report),
            "pk": result,
            "suggestion": result["suggestion"],
            "plot": plot,
        }

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
                "selected_model_key": res.get("pk", {}).get("selected_model_key"),
                "auto_selection": res.get("pk", {}).get("auto_selection"),
            },
        )
        self.history_data = self._history_store.append(record)
        if hasattr(self, "history_table"):
            self.history_table.setProperty("selected_history_record_id", None)
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
