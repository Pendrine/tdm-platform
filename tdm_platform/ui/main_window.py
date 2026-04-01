from __future__ import annotations

import sys
import traceback
import base64
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QDate, QDateTime, QTime, QTimer, QUrl
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDateTimeEdit,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from shiboken6 import isValid
import plotly.graph_objects as go
import plotly.io as pio
try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    MATPLOTLIB_UI_OK = True
except Exception:
    MATPLOTLIB_UI_OK = False

from tdm_platform.app_meta import APP_NAME
from tdm_platform.core.auth import UserStore, ensure_special_roles
from tdm_platform.core.history import HistoryStore
from tdm_platform.core.models import HistoryRecord, SMTPSettings
from tdm_platform.core.permissions import is_primary_moderator
from tdm_platform.pk.amikacin_engine import calculate as calculate_amikacin
from tdm_platform.pk.linezolid_engine import calculate as calculate_linezolid
from tdm_platform.pk.vancomycin_engine import VancomycinInputs, calculate as calculate_vancomycin
from tdm_platform.pk.vancomycin.model_library import MODELS, active_models
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
        self._last_pk_payload: dict = {}
        self._last_plot_spec: dict = {}
        self._configure_history_toolbar_buttons()
        self._modernize_vancomycin_ui()
        self.setWindowTitle(APP_NAME)
        self.setStatusBar(AppStatusBar(self))

    def _modernize_vancomycin_ui(self) -> None:
        self._remove_empirical_controls_from_action_bar()
        # Keep method selector visible so Bayesian/Klasszikus choice is explicit.
        if hasattr(self, "tabs"):
            for idx in reversed(range(self.tabs.count())):
                if self.tabs.tabText(idx) == "Empirikus támogatás":
                    self.tabs.removeTab(idx)
            if hasattr(self, "plot_tab") and self.tabs.indexOf(self.plot_tab) < 0:
                self.tabs.insertTab(2, self.plot_tab, "Vizualizáció")
            for idx in range(self.tabs.count()):
                if self.tabs.tabText(idx) == "Előző mérések":
                    self.tabs.setTabText(idx, "Előző események")
            desired = ["Bemenet", "Eredmények", "Vizualizáció", "Előző események", "Export", "Info és citációk"]
            for i, name in enumerate(desired):
                for j in range(self.tabs.count()):
                    if self.tabs.tabText(j) == name and j != i:
                        self.tabs.tabBar().moveTab(j, i)
                        break
        self._add_fit_button_to_action_bar()
        self._build_results_blocks()
        self._move_summary_cards_to_results()
        self._remove_results_plot_panel()
        self._build_visualization_tab()
        self._build_episode_events_panel()
        self._add_relative_reference_field()
        self._add_loading_and_dosecount_fields()
        self._extend_flag_controls()
        self._set_default_sampling_datetimes()
        self._remove_input_context_block()
        self._bind_input_panel_to_episode_events()

    def _remove_empirical_controls_from_action_bar(self) -> None:
        action_bar = self.calc_btn.parentWidget() if hasattr(self, "calc_btn") else None
        if action_bar is None or action_bar.layout() is None:
            return
        layout = action_bar.layout()
        for idx in reversed(range(layout.count())):
            item = layout.itemAt(idx)
            widget = item.widget()
            if widget is None:
                continue
            is_empirical_label = isinstance(widget, QLabel) and "Empirikus stratégia" in widget.text()
            is_empirical_combo = widget is getattr(self, "empirical_mode_combo", None)
            if is_empirical_label or is_empirical_combo:
                layout.removeWidget(widget)
                if is_empirical_combo:
                    widget.setParent(None)
                    widget.setVisible(False)
                else:
                    widget.setParent(None)
                    widget.deleteLater()
        if hasattr(self, "empirical_mode_combo"):
            try:
                self.empirical_mode_combo.currentTextChanged.disconnect(self.refresh_context_panels)
            except Exception:
                pass

    def _remove_method_controls_from_action_bar(self) -> None:
        action_bar = self.calc_btn.parentWidget() if hasattr(self, "calc_btn") else None
        if action_bar is None or action_bar.layout() is None:
            return
        layout = action_bar.layout()
        for idx in reversed(range(layout.count())):
            item = layout.itemAt(idx)
            widget = item.widget()
            if widget is None:
                continue
            is_method_label = isinstance(widget, QLabel) and widget.text().strip() == "Módszer"
            is_method_combo = widget is getattr(self, "method_combo", None)
            if is_method_label or is_method_combo:
                layout.removeWidget(widget)
                if is_method_combo:
                    widget.setParent(None)
                    widget.setVisible(False)
                else:
                    widget.setParent(None)
                    widget.deleteLater()

    def _bind_input_panel_to_episode_events(self) -> None:
        bound = [
            getattr(self, "dose_edit", None),
            getattr(self, "tinf_edit", None),
            getattr(self, "mic_edit", None),
            getattr(self, "scr_edit", None),
            getattr(self, "level1_rel_edit", None),
            getattr(self, "level2_rel_edit", None),
            getattr(self, "t1_edit", None),
            getattr(self, "t2_edit", None),
            getattr(self, "loading_dose_edit", None),
            getattr(self, "loading_time_edit", None),
            getattr(self, "dose_count_edit", None),
        ]
        for attr_name in (
            "level1_clin_edit",
            "level2_clin_edit",
            "level1_clinic_edit",
            "level2_clinic_edit",
            "sample1_conc_edit",
            "sample2_conc_edit",
        ):
            bound.append(getattr(self, attr_name, None))
        for edit in bound:
            if edit is None:
                continue
            if hasattr(edit, "editingFinished"):
                edit.editingFinished.connect(self._sync_input_panel_to_episode_events)
            if hasattr(edit, "textChanged"):
                edit.textChanged.connect(lambda *_: self._sync_input_panel_to_episode_events())

    def _get_active_sample_times_and_levels(self) -> tuple[str, str, str, str, str]:
        t1 = self.t1_edit.text().strip() if hasattr(self, "t1_edit") else ""
        t2 = self.t2_edit.text().strip() if hasattr(self, "t2_edit") else ""
        clinical_candidates = [
            ("level1_clin_edit", "level2_clin_edit"),
            ("level1_clinic_edit", "level2_clinic_edit"),
            ("sample1_conc_edit", "sample2_conc_edit"),
        ]
        for c1_name, c2_name in clinical_candidates:
            c1_widget = getattr(self, c1_name, None)
            c2_widget = getattr(self, c2_name, None)
            if c1_widget is None or c2_widget is None:
                continue
            c1 = c1_widget.text().strip() if hasattr(c1_widget, "text") else ""
            c2 = c2_widget.text().strip() if hasattr(c2_widget, "text") else ""
            if hasattr(c1_widget, "isVisible") and hasattr(c2_widget, "isVisible"):
                if c1_widget.isVisible() and c2_widget.isVisible() and (c1 or c2):
                    return t1, c1, t2, c2, "clinical"
            else:
                if c1 or c2:
                    return t1, c1, t2, c2, "clinical"
            if not hasattr(c1_widget, "isVisible") and (c1 or c2):
                return t1, c1, t2, c2, "clinical"
        c1_rel = self.level1_rel_edit.text().strip() if hasattr(self, "level1_rel_edit") else ""
        c2_rel = self.level2_rel_edit.text().strip() if hasattr(self, "level2_rel_edit") else ""
        return t1, c1_rel, t2, c2_rel, "relative"

    def _add_loading_and_dosecount_fields(self) -> None:
        form = self.dose_edit.parentWidget().layout() if hasattr(self, "dose_edit") else None
        if not isinstance(form, QFormLayout):
            return
        if not hasattr(self, "loading_dose_edit"):
            self.loading_dose_edit = QLineEdit()
            self.loading_dose_edit.setPlaceholderText("pl. 1500")
            form.addRow("Loading dose (mg)", self.loading_dose_edit)
        if not hasattr(self, "loading_time_edit"):
            self.loading_time_edit = QLineEdit()
            self.loading_time_edit.setPlaceholderText("t0 előtt hány órával (negatív lehet)")
            form.addRow("Loading ideje (óra)", self.loading_time_edit)
        if not hasattr(self, "dose_count_edit"):
            self.dose_count_edit = QLineEdit()
            self.dose_count_edit.setPlaceholderText("pl. 3")
            form.addRow("Eddigi dózisszám", self.dose_count_edit)

    def _remove_input_context_block(self) -> None:
        if hasattr(self, "quick_context") and self.quick_context is not None:
            parent_layout = self.quick_context.parentWidget().layout()
            if parent_layout is not None:
                parent_layout.removeWidget(self.quick_context)
            self.quick_context.setParent(None)
            self.quick_context.deleteLater()
            self.quick_context = None

    def _remove_results_plot_panel(self) -> None:
        if not hasattr(self, "plot_view") or self.plot_view is None:
            return
        self.plot_view.setParent(None)
        self.plot_view.hide()
        if not hasattr(self, "open_visualization_btn"):
            self.open_visualization_btn = QPushButton("Megnyitás a Vizualizáció fülön")
            self.open_visualization_btn.clicked.connect(lambda: self.tabs.setCurrentWidget(self.plot_tab))
            layout = self.results_tab.layout()
            if layout is not None:
                layout.addWidget(self.open_visualization_btn)

    def _move_summary_cards_to_results(self) -> None:
        return

    def _add_fit_button_to_action_bar(self) -> None:
        if hasattr(self, "model_fit_btn"):
            return
        action_bar = self.calc_btn.parentWidget() if hasattr(self, "calc_btn") else None
        if action_bar is None or action_bar.layout() is None:
            return
        self.model_fit_btn = QPushButton("Modellválasztás / Modellillesztés")
        self.model_fit_btn.clicked.connect(self._run_model_selection_only)
        layout = action_bar.layout()
        insert_at = max(0, layout.indexOf(self.calc_btn))
        layout.insertWidget(insert_at, self.model_fit_btn)

    def _build_episode_events_panel(self) -> None:
        if hasattr(self, "episode_events_table"):
            return
        parent_widget = None
        if hasattr(self, "quick_context") and self.quick_context is not None:
            parent_widget = self.quick_context.parentWidget()
        elif hasattr(self, "card_primary"):
            parent_widget = self.card_primary.parentWidget()
        parent_layout = parent_widget.layout() if parent_widget is not None else None
        if parent_layout is None:
            return
        box = QGroupBox("Aktuális epizód eseménylista")
        layout = QVBoxLayout(box)
        btn_row = QHBoxLayout()
        self.refresh_events_btn = QPushButton("Frissítés")
        self.refresh_events_btn.clicked.connect(self._sync_input_panel_to_episode_events)
        btn_row.addWidget(self.refresh_events_btn)
        self.add_event_btn = QPushButton("Sor hozzáadás")
        self.add_event_btn.clicked.connect(lambda: self._append_episode_event("sample"))
        btn_row.addWidget(self.add_event_btn)
        self.delete_event_btn = QPushButton("Kiválasztott esemény törlése")
        self.delete_event_btn.clicked.connect(self._delete_selected_event)
        btn_row.addWidget(self.delete_event_btn)
        layout.addLayout(btn_row)
        self.episode_events_table = QTableWidget(0, 8)
        self.episode_events_table.setHorizontalHeaderLabels(
            ["Időpont", "Esemény típusa", "Dózis (mg)", "Infúziós idő (h)", "Szint (mg/L)", "MIC", "Kreatinin", "Megjegyzés"]
        )
        self._sync_from_table_lock = False
        self.episode_events_table.itemChanged.connect(self._sync_inputs_from_event_table)
        layout.addWidget(self.episode_events_table)
        parent_layout.addWidget(box, 2)

    @staticmethod
    def _event_type_options() -> list[tuple[str, str]]:
        return [
            ("maintenance dose", "maintenance_dose"),
            ("loading dose", "loading_dose"),
            ("extra dose", "extra_dose"),
            ("sample", "sample"),
            ("MIC result", "mic_result"),
            ("creatinine result", "creatinine"),
        ]

    def _set_event_type_widget(self, row: int, event_type: str) -> None:
        if not hasattr(self, "episode_events_table"):
            return
        combo = QComboBox()
        for label, value in self._event_type_options():
            combo.addItem(label, value)
        normalized = str(event_type or "").strip().lower().replace("-", "_").replace(" ", "_")
        idx = combo.findData(normalized)
        if idx < 0:
            for i in range(combo.count()):
                text_norm = combo.itemText(i).strip().lower().replace("-", "_").replace(" ", "_")
                if text_norm == normalized:
                    idx = i
                    break
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.currentIndexChanged.connect(lambda *_: self._sync_inputs_from_event_table(None))
        self.episode_events_table.setCellWidget(row, 1, combo)

    def _add_relative_reference_field(self) -> None:
        if hasattr(self, "relative_reference_dt"):
            return
        rel_layout = self.relative_box.layout() if hasattr(self, "relative_box") else None
        if not isinstance(rel_layout, QFormLayout):
            return
        self.relative_reference_dt = QDateTimeEdit()
        self.relative_reference_dt.setCalendarPopup(True)
        rel_layout.insertRow(0, "Utolsó dózis kezdete (t0)", self.relative_reference_dt)

    def _set_default_sampling_datetimes(self) -> None:
        today = QDate.currentDate()
        start = QDateTime(today, QTime(8, 0))
        s1 = QDateTime(today, QTime(10, 0))
        s2 = QDateTime(today, QTime(19, 0))
        if hasattr(self, "last_infusion_dt"):
            self.last_infusion_dt.setDateTime(start)
        if hasattr(self, "sample1_dt"):
            self.sample1_dt.setDateTime(s1)
        if hasattr(self, "sample2_dt"):
            self.sample2_dt.setDateTime(s2)
        if hasattr(self, "relative_reference_dt"):
            self.relative_reference_dt.setDateTime(start)

    def _extend_flag_controls(self) -> None:
        flags_layout = self.icu_check.parentWidget().layout() if hasattr(self, "icu_check") else None
        if not isinstance(flags_layout, QFormLayout):
            return
        if hasattr(self, "obesity_check") and self.obesity_check is not None:
            # Obesity flag is auto-derived from BMI to avoid duplicate/manual mismatch.
            self.obesity_check.setChecked(False)
            self.obesity_check.hide()
        if not hasattr(self, "hsct_check"):
            self.hsct_check = QCheckBox("HSCT")
            flags_layout.addRow("", self.hsct_check)
        if not hasattr(self, "arc_check"):
            self.arc_check = QCheckBox("ARC / augmented renal clearance")
            flags_layout.addRow("", self.arc_check)

    def _computed_obesity_flag(self) -> bool:
        weight = self._safe_optional_float(self.weight_edit.text()) if hasattr(self, "weight_edit") else None
        height = self._safe_optional_float(self.height_edit.text()) if hasattr(self, "height_edit") else None
        if weight is None or height is None or height <= 0:
            return False
        bmi = weight / ((height / 100.0) ** 2)
        return bmi >= 30.0

    def _append_episode_event(self, event_type: str) -> None:
        previous_lock = getattr(self, "_sync_from_table_lock", False)
        self._sync_from_table_lock = True
        row = self.episode_events_table.rowCount()
        self.episode_events_table.insertRow(row)
        sample_t1, sample_c1, _, _, _ = self._get_active_sample_times_and_levels()
        values = {
            "loading_dose": ["0.0", "loading_dose", self.dose_edit.text().strip() or "1000", self.tinf_edit.text().strip() or "1.0", "", "", "", ""],
            "maintenance_dose": ["0.0", "maintenance_dose", self.dose_edit.text().strip() or "1000", self.tinf_edit.text().strip() or "1.0", "", "", "", ""],
            "extra_dose": ["0.0", "extra_dose", self.dose_edit.text().strip() or "500", self.tinf_edit.text().strip() or "1.0", "", "", "", ""],
            "sample": [sample_t1 or "2.0", "sample", "", "", sample_c1 or "20", "", "", ""],
            "mic_result": ["0.0", "mic_result", "", "", "", self.mic_edit.text().strip() or "1.0", "", ""],
            "creatinine_result": ["0.0", "creatinine", "", "", "", "", self.scr_edit.text().strip() or "90", ""],
        }.get(event_type, ["", event_type, "", "", "", "", "", ""])
        for col, val in enumerate(values):
            if col == 1:
                self._set_event_type_widget(row, val)
            else:
                self.episode_events_table.setItem(row, col, QTableWidgetItem(val))
        self._sync_from_table_lock = previous_lock

    def _delete_selected_event(self) -> None:
        row = self.episode_events_table.currentRow()
        if row >= 0:
            self.episode_events_table.removeRow(row)

    def _sync_inputs_from_event_table(self, _item: QTableWidgetItem | None) -> None:
        if getattr(self, "_sync_from_table_lock", False):
            return
        events = self._collect_episode_events()
        sample_events = []
        for event in events:
            kind = str(event.get("event_type", "")).lower()
            if "sample" in kind:
                t_h = self._safe_optional_float(event.get("time_h"))
                c_h = self._safe_optional_float(event.get("level_mg_l"))
                if t_h is not None and c_h is not None:
                    sample_events.append((t_h, c_h))
            elif "dose" in kind and "loading" not in kind:
                if event.get("dose_mg"):
                    self.dose_edit.setText(str(event.get("dose_mg")))
                if event.get("tinf_h"):
                    self.tinf_edit.setText(str(event.get("tinf_h")))
            elif "loading" in kind:
                self.loading_dose_edit.setText(str(event.get("dose_mg", "")))
                self.loading_time_edit.setText(str(event.get("time_h", "")))
            elif "mic" in kind:
                self.mic_edit.setText(str(event.get("mic", "")))
            elif "creatinine" in kind or kind == "scr":
                self.scr_edit.setText(str(event.get("creatinine", "")))
        sample_events.sort(key=lambda x: x[0])
        if len(sample_events) >= 1:
            self.t1_edit.setText(str(sample_events[0][0]))
            self.level1_rel_edit.setText(str(sample_events[0][1]))
        if len(sample_events) >= 2:
            self.t2_edit.setText(str(sample_events[1][0]))
            self.level2_rel_edit.setText(str(sample_events[1][1]))

    def _build_results_blocks(self) -> None:
        if hasattr(self, "results_splitter"):
            return
        layout = self.results_tab.layout()
        if layout is None:
            return
        result_text_widget = getattr(self, "result_text", None)
        if result_text_widget is not None and isValid(result_text_widget):
            result_text_widget.setParent(None)
        plot_widget = getattr(self, "plot_view", None)
        if plot_widget is not None and isValid(plot_widget):
            plot_widget.setParent(None)
        for card_name in ("card_status", "card_regimen", "card_primary", "card_secondary"):
            card = getattr(self, card_name, None)
            if card is not None and isValid(card):
                card.setParent(None)
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.results_splitter = QSplitter()
        layout.addWidget(self.results_splitter, 1)
        left_box = QWidget()
        left_layout = QVBoxLayout(left_box)
        left_layout.addWidget(QLabel("Részletes interpretáció"))
        if result_text_widget is None or not isValid(result_text_widget):
            result_text_widget = QPlainTextEdit()
            result_text_widget.setReadOnly(True)
            self.result_text = result_text_widget
        else:
            self.result_text = result_text_widget
        self.result_text.setMinimumWidth(620)
        self.result_text.setMinimumHeight(520)
        left_layout.addWidget(self.result_text, 1)
        self.results_splitter.addWidget(left_box)
        right_box = QWidget()
        right_layout = QVBoxLayout(right_box)
        cards_grid = QGridLayout()
        cards = [self.card_status, self.card_regimen, self.card_primary, self.card_secondary]
        for i, card in enumerate(cards):
            card.setParent(None)
            cards_grid.addWidget(card, i // 2, i % 2)
        right_layout.addLayout(cards_grid)
        self.auto_select_browser = QTextBrowser()
        self.model_override_combo = QComboBox()
        self._refresh_model_override_options("Bayesian")
        self.model_override_combo.currentIndexChanged.connect(self._on_manual_model_override_changed)
        self.final_decision_browser = QTextBrowser()
        self.model_meta_browser = QTextBrowser()
        self.fit_table = QTableWidget(0, 9)
        self.fit_table.setHorizontalHeaderLabels(["Modell", "RMSE", "MAE", "Combined", "CL", "Vd", "AUC24", "AUC/MIC", "Státusz"])
        self.recommendation_browser = QTextBrowser()
        self.history_summary_browser = QTextBrowser()
        self.pkpd_table = QTableWidget(3, 3)
        self.pkpd_table.setHorizontalHeaderLabels(["AUC24", "AUC/MIC", "Peak"])
        self.pkpd_table.setVerticalHeaderLabels(["PK/PD", "Kinetika", "Renális"])
        for widget in [
            self.auto_select_browser,
            self.final_decision_browser,
            self.model_meta_browser,
            self.pkpd_table,
            self.model_override_combo,
            self.recommendation_browser,
            self.fit_table,
            self.history_summary_browser,
        ]:
            right_layout.addWidget(widget)
        right_layout.addStretch(1)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right_box)
        self.results_splitter.addWidget(right_scroll)
        self.results_splitter.setSizes([760, 520])

    def _build_visualization_tab(self) -> None:
        if hasattr(self, "viz_mode_tabs"):
            return
        layout = self.plot_tab.layout()
        if layout is None:
            layout = QVBoxLayout(self.plot_tab)
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        top = QHBoxLayout()
        self.view_combo = QComboBox()
        self.view_combo.addItems(["Concentration-time", "AUC"])
        self.toggle_obs = QCheckBox("Observed pontok")
        self.toggle_obs.setChecked(True)
        self.toggle_fit = QCheckBox("Modeled / fitted görbe")
        self.toggle_fit.setChecked(True)
        self.toggle_projection = QCheckBox("Future projection")
        self.toggle_dose_events = QCheckBox("Dose events")
        self.toggle_overlay = QCheckBox("Overlay modellek")
        self.toggle_overlay.setChecked(True)
        self.toggle_current_samples = QCheckBox("Aktuális epizód mintapontjai")
        self.toggle_current_samples.setChecked(True)
        self.toggle_history_samples = QCheckBox("Korábbi azonos beteg mintapontjai")
        self.toggle_regimen_conc = QCheckBox("Ajánlott sémák prediktált koncentrációi")
        self.toggle_regimen_auc = QCheckBox("Ajánlott sémák prediktált AUC overlay")
        self.toggle_dose_annotations = QCheckBox("Dózisesemény annotációk")
        top.addWidget(self.view_combo)
        for chk in [
            self.toggle_obs,
            self.toggle_fit,
            self.toggle_projection,
            self.toggle_dose_events,
            self.toggle_overlay,
            self.toggle_current_samples,
            self.toggle_history_samples,
            self.toggle_regimen_conc,
            self.toggle_regimen_auc,
            self.toggle_dose_annotations,
        ]:
            top.addWidget(chk)
        top.addStretch(1)
        layout.addLayout(top)
        self.viz_mode_tabs = QTabWidget()
        self.viz_single = QTextBrowser()
        self.viz_averaging = QTextBrowser()
        self.viz_mode_tabs.addTab(self.viz_single, "Single model")
        self.viz_mode_tabs.addTab(self.viz_averaging, "Model averaging")
        self.viz_mode_tabs.currentChanged.connect(lambda *_: self.render_plot(self._last_plot_spec or {}))
        self.view_combo.currentIndexChanged.connect(lambda *_: self.render_plot(self._last_plot_spec or {}))
        for chk in [
            self.toggle_obs,
            self.toggle_fit,
            self.toggle_projection,
            self.toggle_dose_events,
            self.toggle_overlay,
            self.toggle_current_samples,
            self.toggle_history_samples,
            self.toggle_regimen_conc,
            self.toggle_regimen_auc,
            self.toggle_dose_annotations,
        ]:
            chk.stateChanged.connect(lambda *_: self.render_plot(self._last_plot_spec or {}))
        layout.addWidget(self.viz_mode_tabs)
        if hasattr(self, "plot_view") and isinstance(self.plot_view, QWebEngineView):
            self.viz_plot_view = self.plot_view
            self.viz_plot_view.setVisible(True)
        else:
            self.viz_plot_view = QWebEngineView(self.plot_tab)
        print("[DEBUG][PLOT] viz_plot_view widget class:", type(self.viz_plot_view).__name__)
        self.viz_plot_view.setMinimumHeight(460)
        self.viz_plot_view.setHtml("<p>Még nincs számítási eredmény.</p>")
        layout.addWidget(self.viz_plot_view, 1)
        if hasattr(self, "tabs"):
            try:
                self.tabs.currentChanged.connect(self._on_main_tabs_changed)
            except Exception:
                pass
        self.model_avg_table = QTableWidget(0, 6)
        self.model_avg_table.setHorizontalHeaderLabels(["Modell", "Súly", "RMSE", "MAE", "AUC24", "AUC/MIC"])
        layout.addWidget(self.model_avg_table)

    def _run_model_selection_only(self) -> None:
        try:
            if self.antibiotic_combo.currentText() != "Vancomycin":
                self._reset_non_vancomycin_views()
                return
            abx = self.antibiotic_combo.currentText()
            pk = self.collect_pk_inputs()
            self._last_pk_payload = pk
            method = self.method_combo.currentText() if hasattr(self, "method_combo") else "Bayesian"
            self._refresh_model_override_options(method)
            print(
                f"[DEBUG][UI] _run_model_selection_only method_combo={method} "
                f"selected_model_key={(self.model_override_combo.currentData() if hasattr(self, 'model_override_combo') else None)}"
            )
            res = self.calc_vancomycin(pk, method or "Bayesian")
            self.results = res
            self.latest_report = res["report"]
            self.result_text.setPlainText(res["report"])
            self.card_primary.update_card(res["primary"], f"{abx} – {method}")
            self.card_secondary.update_card(res["secondary"], res.get("status_sub", ""))
            self.card_regimen.update_card(res["regimen"], "Elsődleges javaslat")
            self.card_status.update_card(res["status"], res.get("status_sub", ""))
            self._update_structured_result_views(res.get("pk", {}))
            self.render_plot(res.get("plot", {}))
        except Exception as exc:
            traceback.print_exc()
            message = str(exc).strip() or "Váratlan hiba történt a modellillesztés közben."
            QMessageBox.warning(self, "Modellillesztés hiba", message)

    def _on_manual_model_override_changed(self) -> None:
        if self.antibiotic_combo.currentText() != "Vancomycin":
            return
        self._run_model_selection_only()

    def _refresh_model_override_options(self, method: str) -> None:
        if not hasattr(self, "model_override_combo"):
            return
        combo = self.model_override_combo
        previous_value = combo.currentData() if combo.count() else None
        combo.blockSignals(True)
        try:
            combo.clear()
            method_norm = str(method or "").strip()
            if method_norm == "Klasszikus":
                combo.setVisible(False)
                combo.addItem("Klasszikus trapezoid (steady-state)", "trapezoid_classic")
            else:
                combo.setVisible(True)
                combo.addItem("Automatikus javaslat", "")
                for model in active_models():
                    combo.addItem(model.label, model.key)
            if combo.count() > 0:
                restored_idx = combo.findData(previous_value) if previous_value is not None else -1
                combo.setCurrentIndex(restored_idx if restored_idx >= 0 else 0)
        finally:
            combo.blockSignals(False)

    def methods_for_antibiotic(self, abx: str) -> list[str]:
        if abx == "Vancomycin":
            return ["Klasszikus", "Bayesian"]
        return ["Nincs implementálva"]

    def on_antibiotic_change(self):
        super().on_antibiotic_change()
        is_vanco = self.antibiotic_combo.currentText() == "Vancomycin"
        if is_vanco and hasattr(self, "method_combo"):
            self._refresh_model_override_options(self.method_combo.currentText())
        self._set_default_sampling_datetimes()
        if hasattr(self, "model_fit_btn"):
            self.model_fit_btn.setVisible(is_vanco)
        self._reset_non_vancomycin_views() if not is_vanco else None

    def update_sampling_visibility(self):
        super().update_sampling_visibility()
        self._set_default_sampling_datetimes()

    def _reset_non_vancomycin_views(self) -> None:
        self.results = {}
        self.latest_report = ""
        self.result_text.setPlainText("Ehhez az antibiotikumhoz még nincs modell implementálva.")
        if hasattr(self, "plot_view"):
            self.plot_view.setHtml("<p>Még nincs számítási eredmény.</p>")
        if hasattr(self, "viz_single"):
            self.viz_single.setHtml("<p>Még nincs számítási eredmény.</p>")
        if hasattr(self, "viz_averaging"):
            self.viz_averaging.setHtml("<p>Még nincs számítási eredmény.</p>")
        if hasattr(self, "fit_table"):
            self.fit_table.setRowCount(0)
        if hasattr(self, "model_avg_table"):
            self.model_avg_table.setRowCount(0)
        if hasattr(self, "recommendation_browser"):
            self.recommendation_browser.setHtml("<p>Nincs recommendation ehhez az antibiotikumhoz.</p>")

    def reset_defaults(self):
        super().reset_defaults()
        self._set_default_sampling_datetimes()
        if hasattr(self, "method_combo"):
            if self.method_combo.findText("Bayesian") >= 0:
                self.method_combo.setCurrentText("Bayesian")
            elif self.method_combo.currentText().strip() == "" and self.method_combo.count() > 0:
                self.method_combo.setCurrentIndex(0)
            self._refresh_model_override_options(self.method_combo.currentText())
        if hasattr(self, "episode_events_table"):
            self.episode_events_table.setRowCount(0)
            self._append_episode_event("maintenance_dose")
            self._append_episode_event("sample")
            self._append_episode_event("sample")
            self._sync_input_panel_to_episode_events()
        self._reset_non_vancomycin_views() if self.antibiotic_combo.currentText() != "Vancomycin" else None

    def collect_pk_inputs(self) -> dict:
        if hasattr(self, "episode_events_table"):
            self._flush_episode_table_edits()
        payload = self._collect_common_with_events()
        payload["method"] = self.method_combo.currentText() if hasattr(self, "method_combo") else "Bayesian"
        payload["selected_model_key"] = (self.model_override_combo.currentData() if hasattr(self, "model_override_combo") else None) or None
        sample_events = [e for e in (payload.get("episode_events") or []) if "sample" in str(e.get("event_type", "")).lower()]
        sample_values = [e.get("level_mg_l") for e in sample_events]
        print(f"[DEBUG][UI] collect_pk_inputs method={payload.get('method')} selected_model_key={payload.get('selected_model_key')}")
        print(f"[DEBUG][UI] collect_pk_inputs sample_count={len(sample_events)} sample_values={sample_values}")
        return payload

    def _flush_episode_table_edits(self) -> None:
        if not hasattr(self, "episode_events_table"):
            return
        table = self.episode_events_table
        current = table.currentItem()
        if current is not None:
            table.closePersistentEditor(current)
        table.clearFocus()
        QApplication.processEvents()
        print("[DEBUG][UI] episode table edits flushed.")

    def _collect_episode_events(self) -> list[dict]:
        events: list[dict] = []
        if not hasattr(self, "episode_events_table"):
            return events
        print("[DEBUG][UI] event rows count before parse:", self.episode_events_table.rowCount())
        for row in range(self.episode_events_table.rowCount()):
            def txt(col: int) -> str:
                if col == 1:
                    widget = self.episode_events_table.cellWidget(row, 1)
                    if isinstance(widget, QComboBox):
                        return str(widget.currentData() or widget.currentText()).strip()
                item = self.episode_events_table.item(row, col)
                return item.text().strip() if item else ""

            events.append(
                {
                    "time_h": txt(0),
                    "event_type": txt(1),
                    "dose_mg": txt(2),
                    "tinf_h": txt(3),
                    "level_mg_l": txt(4),
                    "mic": txt(5),
                    "creatinine": txt(6),
                    "note": txt(7),
                }
            )
        parsed_sample_rows = len([e for e in events if "sample" in str(e.get("event_type", "")).lower() and str(e.get("level_mg_l", "")).strip() != ""])
        parsed_dose_rows = len([e for e in events if "dose" in str(e.get("event_type", "")).lower() and str(e.get("dose_mg", "")).strip() != ""])
        parsed_creatinine_rows = len([e for e in events if "creatinine" in str(e.get("event_type", "")).lower() and str(e.get("creatinine", "")).strip() != ""])
        print(
            "[DEBUG][UI] parsed event rows summary:",
            {
                "parsed_sample_rows": parsed_sample_rows,
                "parsed_dose_rows": parsed_dose_rows,
                "parsed_creatinine_rows": parsed_creatinine_rows,
            },
        )
        return events

    @staticmethod
    def _safe_optional_float(raw: object) -> float | None:
        txt = str(raw or "").strip().replace(",", ".")
        if txt == "":
            return None
        try:
            return float(txt)
        except ValueError:
            return None

    def _safe_required_float(self, raw: object, field: str) -> float:
        value = self._safe_optional_float(raw)
        if value is None:
            raise ValueError(f"A(z) {field} mező kötelező és numerikus értéket vár.")
        return value

    @staticmethod
    def _fmt_float(value: object, digits: int = 2, na: str = "n/a") -> str:
        try:
            if value is None:
                return na
            return f"{float(value):.{digits}f}"
        except (TypeError, ValueError):
            return na

    def _sync_input_panel_to_episode_events(self) -> None:
        if not hasattr(self, "episode_events_table"):
            return
        if getattr(self, "_sync_from_table_lock", False):
            return
        self._sync_from_table_lock = True
        try:
            if self.episode_events_table.rowCount() == 0:
                self._append_episode_event("maintenance_dose")
                self._append_episode_event("sample")
                self._append_episode_event("sample")
            # Maintain at least one maintenance dose row.
            self._set_event_type_widget(0, "maintenance_dose")
            self.episode_events_table.setItem(0, 2, QTableWidgetItem(self.dose_edit.text().strip()))
            self.episode_events_table.setItem(0, 3, QTableWidgetItem(self.tinf_edit.text().strip()))
            # First two sample rows.
            sample_rows = []
            for r in range(self.episode_events_table.rowCount()):
                widget = self.episode_events_table.cellWidget(r, 1)
                kind = str(widget.currentData() or widget.currentText()).strip().lower() if isinstance(widget, QComboBox) else ""
                if "sample" in kind:
                    sample_rows.append(r)
            while len(sample_rows) < 2:
                self._append_episode_event("sample")
                sample_rows.append(self.episode_events_table.rowCount() - 1)
            sample_t1, sample_c1, sample_t2, sample_c2, sample_source = self._get_active_sample_times_and_levels()
            self.episode_events_table.setItem(sample_rows[0], 0, QTableWidgetItem(sample_t1))
            self.episode_events_table.setItem(sample_rows[0], 4, QTableWidgetItem(sample_c1))
            self.episode_events_table.setItem(sample_rows[1], 0, QTableWidgetItem(sample_t2))
            self.episode_events_table.setItem(sample_rows[1], 4, QTableWidgetItem(sample_c2))
            print(
                "[DEBUG][UI] sample sync source:",
                {"source": sample_source, "t1": sample_t1, "c1": sample_c1, "t2": sample_t2, "c2": sample_c2},
            )
            # Loading dose row (optional)
            loading_value = self.loading_dose_edit.text().strip() if hasattr(self, "loading_dose_edit") else ""
            if loading_value:
                loading_time = self.loading_time_edit.text().strip() if hasattr(self, "loading_time_edit") else "-12"
                for r in range(self.episode_events_table.rowCount()):
                    widget = self.episode_events_table.cellWidget(r, 1)
                    kind = str(widget.currentData() or widget.currentText()).strip().lower() if isinstance(widget, QComboBox) else ""
                    if "loading" in kind:
                        self.episode_events_table.setItem(r, 0, QTableWidgetItem(loading_time))
                        self.episode_events_table.setItem(r, 2, QTableWidgetItem(loading_value))
                        break
                else:
                    self._append_episode_event("loading_dose")
                    r = self.episode_events_table.rowCount() - 1
                    self._set_event_type_widget(r, "loading_dose")
                    self.episode_events_table.setItem(r, 0, QTableWidgetItem(loading_time))
                    self.episode_events_table.setItem(r, 2, QTableWidgetItem(loading_value))

            # MIC and creatinine rows (upsert).
            def _upsert_row(label: str, col: int, value: str) -> None:
                for r in range(self.episode_events_table.rowCount()):
                    widget = self.episode_events_table.cellWidget(r, 1)
                    kind = str(widget.currentData() or widget.currentText()).strip().lower() if isinstance(widget, QComboBox) else ""
                    if kind == label:
                        self.episode_events_table.setItem(r, col, QTableWidgetItem(value))
                        return
                self._append_episode_event(label.replace(" ", "_"))
                r = self.episode_events_table.rowCount() - 1
                self._set_event_type_widget(r, label)
                self.episode_events_table.setItem(r, col, QTableWidgetItem(value))

            if self.mic_edit.text().strip():
                _upsert_row("mic_result", 5, self.mic_edit.text().strip())
            if self.scr_edit.text().strip():
                _upsert_row("creatinine", 6, self.scr_edit.text().strip())
        finally:
            self._sync_from_table_lock = False

    def _sync_legacy_fields_from_episode_events(self, payload: dict) -> None:
        try:
            self.dose_edit.setText(str(payload.get("dose", self.dose_edit.text())))
            self.tinf_edit.setText(str(payload.get("tinf", self.tinf_edit.text())))
            self.scr_edit.setText(str(payload.get("scr_umol", self.scr_edit.text())))
            if payload.get("mic") is not None:
                self.mic_edit.setText(str(payload.get("mic")))
            self.t1_edit.setText(str(payload.get("t1", self.t1_edit.text())))
            self.t2_edit.setText(str(payload.get("t2", self.t2_edit.text())))
            self.level1_rel_edit.setText(str(payload.get("c1", self.level1_rel_edit.text())))
            self.level2_rel_edit.setText(str(payload.get("c2", self.level2_rel_edit.text())))
            if payload.get("t3") is not None:
                self.t3_edit.setText(str(payload.get("t3")))
            if payload.get("c3") is not None:
                self.level3_edit.setText(str(payload.get("c3")))
        except Exception:
            return

    def _collect_common_with_events(self) -> dict:
        payload = {
            "patient_id": self.patient_edit.text().strip(),
            "decision": self.decision_edit.toPlainText().strip(),
            "sex": self.sex_combo.currentText(),
            "age": self._safe_required_float(self.age_edit.text(), "Életkor"),
            "weight": self._safe_required_float(self.weight_edit.text(), "Testsúly"),
            "height": self._safe_required_float(self.height_edit.text(), "Magasság"),
            "scr_umol": self._safe_required_float(self.scr_edit.text(), "Kreatinin"),
            "mic": self._safe_optional_float(self.mic_edit.text()),
            "dose": self._safe_required_float(self.dose_edit.text(), "Dózis"),
            "tau": self._safe_required_float(self.tau_edit.text(), "Intervallum"),
            "tinf": self._safe_required_float(self.tinf_edit.text(), "Infúziós idő"),
            "target_auc": self._safe_optional_float(self.target_auc_edit.text()) or 500.0,
            "rounding": self._safe_optional_float(self.rounding_edit.text()) or 250.0,
            "loading_dose": self._safe_optional_float(self.loading_dose_edit.text()) if hasattr(self, "loading_dose_edit") else None,
            "loading_time_h": self._safe_optional_float(self.loading_time_edit.text()) if hasattr(self, "loading_time_edit") else None,
            "dose_count": int(self._safe_optional_float(self.dose_count_edit.text()) or 0) if hasattr(self, "dose_count_edit") else 0,
            "c1": self._safe_required_float(self.level1_rel_edit.text(), "1. szint"),
            "c2": self._safe_required_float(self.level2_rel_edit.text(), "2. szint"),
            "c3": self._safe_optional_float(self.level3_edit.text()),
            "t1": self._safe_required_float(self.t1_edit.text(), "T1"),
            "t2": self._safe_required_float(self.t2_edit.text(), "T2"),
            "t3": self._safe_optional_float(self.t3_edit.text()),
            "icu": self.icu_check.isChecked(),
            "hematology": self.hematology_check.isChecked(),
            "unstable_renal": self.unstable_renal_check.isChecked(),
            "obesity": self._computed_obesity_flag(),
            "neutropenia": self.neutropenia_check.isChecked(),
        }
        if hasattr(self, "episode_events_table") and self.episode_events_table.rowCount() == 0:
            self._sync_input_panel_to_episode_events()
        if payload["height"] > 0:
            bmi = payload["weight"] / ((payload["height"] / 100.0) ** 2)
            payload["obesity"] = bmi >= 30.0
        payload["patient_name"] = self.patient_edit.text().strip()
        payload["episode_events"] = self._collect_episode_events()
        payload["hsct"] = bool(self.hsct_check.isChecked()) if hasattr(self, "hsct_check") else False
        payload["arc"] = bool(self.arc_check.isChecked()) if hasattr(self, "arc_check") else False
        current_dose_events = len([e for e in payload["episode_events"] if "dose" in str(e.get("event_type", "")).lower()])
        prior_dose_events = 0
        patient_id = str(payload.get("patient_id", "")).strip()
        for row in getattr(self, "history_data", []) or []:
            if str(row.get("drug", "")).strip().lower() != "vancomycin":
                continue
            if patient_id and str(row.get("patient_id", "")).strip() != patient_id:
                continue
            prev_events = (row.get("inputs") or {}).get("episode_events") or []
            prior_dose_events += len([e for e in prev_events if "dose" in str(e.get("event_type", "")).lower()])
        payload["prior_dose_events"] = prior_dose_events
        payload["dose_number"] = payload.get("dose_count") or (current_dose_events + prior_dose_events) or 1
        sample_events = []
        dose_events = []
        for event in payload["episode_events"]:
            e_type = str(event.get("event_type", "")).lower()
            try:
                t_h = float(str(event.get("time_h", "")).replace(",", "."))
            except ValueError:
                continue
            if "sample" in e_type:
                try:
                    c = float(str(event.get("level_mg_l", "")).replace(",", "."))
                except ValueError:
                    continue
                sample_events.append((t_h, c))
            if "dose" in e_type:
                dose_events.append(event)
            if "mic" in e_type:
                try:
                    payload["mic"] = float(str(event.get("mic", "")).replace(",", "."))
                except ValueError:
                    pass
            if "creatinine" in e_type:
                try:
                    payload["scr_umol"] = float(str(event.get("creatinine", "")).replace(",", "."))
                except ValueError:
                    pass
        sample_events.sort(key=lambda x: x[0])
        _, raw_c1, _, raw_c2, sample_source = self._get_active_sample_times_and_levels()
        raw_ui_sample_values = [raw_c1, raw_c2]
        normalized_sample_values = [self._safe_optional_float(v) for v in raw_ui_sample_values]
        print("[DEBUG][UI] raw UI sample values:", {"source": sample_source, "values": raw_ui_sample_values})
        print("[DEBUG][UI] normalized UI sample values:", normalized_sample_values)
        print("[DEBUG][UI] built event rows:", payload["episode_events"])
        if len(sample_events) >= 2:
            payload["t1"], payload["c1"] = sample_events[0]
            payload["t2"], payload["c2"] = sample_events[1]
            if len(sample_events) >= 3:
                payload["t3"], payload["c3"] = sample_events[2]
            event_sample_values = [sample_events[0][1], sample_events[1][1]]
            if normalized_sample_values[:2] != event_sample_values:
                print(
                    "[WARN][UI] sample binding mismatch: ui_fields_vs_event_rows",
                    {"ui": normalized_sample_values[:2], "events": event_sample_values},
                )
            self.level1_rel_edit.setText(str(sample_events[0][1]))
            self.level2_rel_edit.setText(str(sample_events[1][1]))
            self.t1_edit.setText(str(sample_events[0][0]))
            self.t2_edit.setText(str(sample_events[1][0]))
        if dose_events:
            last_dose = dose_events[-1]
            try:
                payload["dose"] = float(str(last_dose.get("dose_mg", payload["dose"])).replace(",", "."))
            except ValueError:
                pass
            try:
                payload["tinf"] = float(str(last_dose.get("tinf_h", payload["tinf"])).replace(",", "."))
            except ValueError:
                pass
        if self.sample_mode_combo.currentIndex() == 1 and hasattr(self, "relative_reference_dt"):
            t0 = self.relative_reference_dt.dateTime().toPython()
            payload["reference_time"] = t0.isoformat()
        return payload

    def calculate(self):
        try:
            abx = self.antibiotic_combo.currentText()
            if abx != "Vancomycin":
                self._reset_non_vancomycin_views()
                self.tabs.setCurrentWidget(self.results_tab)
                return
            pk = self.collect_pk_inputs()
            self._last_pk_payload = pk
            method = self.method_combo.currentText() if hasattr(self, "method_combo") else "Bayesian"
            self._refresh_model_override_options(method)
            print(
                f"[DEBUG][UI] calculate method_combo={method} "
                f"selected_model_key={(self.model_override_combo.currentData() if hasattr(self, 'model_override_combo') else None)}"
            )
            res = self.calc_vancomycin(pk, method or "Bayesian")
            self.results = res
            self.latest_report = res["report"]
            self.result_text.setPlainText(res["report"])
            self.card_primary.update_card(res["primary"], f"{abx} – {method}")
            self.card_secondary.update_card(res["secondary"], res.get("status_sub", ""))
            self.card_regimen.update_card(res["regimen"], "Elsődleges javaslat")
            self.card_status.update_card(res["status"], res.get("status_sub", ""))
            self.render_plot(res["plot"])
            self.append_history_record(pk, res)
            self.export_status.setText("Riport elkészült és naplózva lett.")
            self.tabs.setCurrentWidget(self.results_tab)
        except Exception as exc:
            QMessageBox.critical(self, "Hiba", str(exc))

    def refresh_context_panels(self):
        if not hasattr(self, "antibiotic_combo"):
            return
        abx = self.antibiotic_combo.currentText()
        method = self.method_combo.currentText()
        if abx == "Vancomycin":
            self._refresh_model_override_options(method)
        if hasattr(self, "guide_browser"):
            self.guide_browser.setHtml(self.build_guide_html(abx, method))
        if hasattr(self, "evidence_browser"):
            self.evidence_browser.setHtml(self.build_evidence_html(abx, method))

    def build_guide_html(self, abx: str, method: str) -> str:
        if abx != "Vancomycin":
            return "<h2>Info</h2><p>Ehhez az antibiotikumhoz még nincs modell implementálva.</p>"
        items = []
        for model in active_models():
            flags = ", ".join(model.required_covariates)
            items.append(
                f"<li><b>{model.label}</b><br>"
                f"Populáció: {model.population}<br>"
                f"Javasolt: metadata-alapú illeszkedés esetén.<br>"
                f"Nem ideális: ha a kötelező covariate-ek hiányoznak.<br>"
                f"Flag/covariate: {flags}</li>"
            )
        return "<h2>Vancomycin modellek (selector alap)</h2><ul>" + "".join(items) + "</ul>"

    def build_evidence_html(self, abx: str, method: str) -> str:
        if abx != "Vancomycin":
            return "<h2>Citációk</h2><p>Ehhez az antibiotikumhoz még nincs modell-specifikus citáció.</p>"
        parts = ["<h2>Bayesian/populációs modellek</h2>"]
        for model in active_models():
            parts.append(
                f"<p><b>{model.label}</b><br>"
                f"Szerző/év: {model.author} ({model.year})<br>"
                f"Populáció: {model.population}<br>"
                f"Forrás: modell metadata könyvtár.</p>"
            )
        return "".join(parts)

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
        if self.current_user and hasattr(self, "user_status_label") and self.user_status_label is not None and isValid(self.user_status_label):
            role_txt = self.current_user.get("role", "orvos")
            username = self._display_name_for_user(self.current_user)
            self.user_status_label.setText(f"Bejelentkezve: {username} ({self.current_user.get('email','')}) – {role_txt}")

    def refresh_settings_tab(self):
        super().refresh_settings_tab()
        if self.current_user and hasattr(self, "settings_name_label") and self.settings_name_label is not None and isValid(self.settings_name_label):
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
        payload = self._collect_common_with_events()
        self._sync_legacy_fields_from_episode_events(payload)
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
            self._restore_episode_events_from_history(rows[idx])
            print(f"[DEBUG][HISTORY] selected record_id={selected_record_id}")
        if hasattr(self, "tabs") and hasattr(self, "input_tab"):
            self.tabs.setCurrentWidget(self.input_tab)
            print("[DEBUG][HISTORY] switched to input tab")

    def _restore_episode_events_from_history(self, row: dict) -> None:
        if not hasattr(self, "episode_events_table"):
            return
        inputs = row.get("inputs") or {}
        events = inputs.get("episode_events") or []
        self.episode_events_table.setRowCount(0)
        for event in events:
            self._append_episode_event(str(event.get("event_type", "sample")))
            current = self.episode_events_table.rowCount() - 1
            mapping = [
                event.get("time_h", ""),
                event.get("event_type", ""),
                event.get("dose_mg", ""),
                event.get("tinf_h", ""),
                event.get("level_mg_l", ""),
                event.get("mic", ""),
                event.get("creatinine", ""),
                event.get("note", ""),
            ]
            for col, value in enumerate(mapping):
                if col == 1:
                    self._set_event_type_widget(current, str(value))
                else:
                    self.episode_events_table.setItem(current, col, QTableWidgetItem(str(value)))
        self._set_default_sampling_datetimes()
        synced = self._collect_common_with_events()
        self._sync_legacy_fields_from_episode_events(synced)

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
            "obesity": self._computed_obesity_flag(),
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


    def _on_main_tabs_changed(self, _idx: int) -> None:
        pending = getattr(self, "_pending_plot_spec", None)
        if pending is not None and self._is_visualization_tab_active() and self._is_plot_view_visible():
            print("[DEBUG][PLOT] main tab became visible; rendering deferred plot.")
            self._pending_plot_spec = None
            self._plot_render_deferred = False
            self.render_plot(pending)

    def _is_plot_view_visible(self) -> bool:
        view = getattr(self, "viz_plot_view", None)
        if view is None:
            return False
        return bool(getattr(view, "isVisible", lambda: True)())

    def _is_plot_webengine(self) -> bool:
        return isinstance(getattr(self, "viz_plot_view", None), QWebEngineView)

    def _is_visualization_tab_active(self) -> bool:
        if not hasattr(self, "tabs") or not hasattr(self, "plot_tab"):
            return True
        return self.tabs.currentWidget() is self.plot_tab

    def _update_plot_summary(self, single: dict, avg: dict, trace_count: int, renderer_state: str) -> None:
        mode_text = "Model averaging" if (hasattr(self, "viz_mode_tabs") and self.viz_mode_tabs.currentIndex() == 1) else "Single model"
        if hasattr(self, "viz_single"):
            self.viz_single.setHtml(f"<h3>{single.get('label','Single model')}</h3><p>Renderer: {renderer_state} | Mód: {mode_text} | Trace-ek: {trace_count}</p>")
        if hasattr(self, "viz_averaging"):
            self.viz_averaging.setHtml("<br/>".join([f"{ov.get('label','-')}: w={ov.get('weight',0):.3f}" for ov in avg.get("overlays", [])]) or "Nincs model averaging adat.")

    def _schedule_plot_fallback(self, request_id: int) -> None:
        state = (getattr(self, "_plot_request_states", {}) or {}).get(request_id, {})
        print(f"[DEBUG][PLOT] delayed fallback scheduled: id={request_id} state={state}")
        timer = getattr(self, "_plot_fallback_timer", None)
        if timer is not None:
            timer.stop()
        self._plot_fallback_request_id = request_id
        self._plot_fallback_timer = QTimer(self)
        self._plot_fallback_timer.setSingleShot(True)
        self._plot_fallback_timer.timeout.connect(lambda rid=request_id: self._execute_plot_fallback(rid))
        self._plot_fallback_timer.start(600)

    def _execute_plot_fallback(self, request_id: int) -> None:
        states = getattr(self, "_plot_request_states", {}) or {}
        state = states.get(request_id, {})
        if request_id != getattr(self, "_active_plot_request_id", -1):
            print(f"[DEBUG][PLOT] delayed fallback skipped: id={request_id} reason=stale_request state={state}")
            return
        if state.get("succeeded") or state.get("fallback_executed") or not state.get("pending", False):
            print(f"[DEBUG][PLOT] delayed fallback skipped: id={request_id} reason=resolved state={state}")
            return
        if not self._is_plot_view_visible() or not MATPLOTLIB_UI_OK:
            return
        pred_x = state.get("pred_x", [])
        pred_y = state.get("pred_y", [])
        obs_x = state.get("obs_x", [])
        obs_y = state.get("obs_y", [])
        view = getattr(self, "viz_plot_view", None)
        if not pred_x or not pred_y or view is None:
            return
        print(f"[DEBUG][PLOT] fallback executed: id={request_id}")
        mfig = plt.figure(figsize=(8, 4), dpi=120)
        ax = mfig.add_subplot(111)
        ax.plot(pred_x, pred_y, linewidth=2.0, color="#2563eb")
        if obs_x and obs_y:
            ax.scatter(obs_x, obs_y, color="#16a34a")
        buffer = BytesIO()
        mfig.tight_layout()
        mfig.savefig(buffer, format="png")
        plt.close(mfig)
        png_b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
        view.setHtml(f"<img src='data:image/png;base64,{png_b64}'/>")
        state["pending"] = False
        state["fallback_executed"] = True
        self._plot_renderer_state = "Matplotlib fallback"
        self._update_plot_summary(state.get("single", {}), state.get("avg", {}), int(state.get("trace_count", 0)), self._plot_renderer_state)
        print(f"[DEBUG][PLOT] final renderer state: {self._plot_renderer_state}")

    def _collect_history_sample_points(self) -> list[tuple[float, float, str]]:
        points: list[tuple[float, float, str]] = []
        patient_id = str((self._last_pk_payload or {}).get("patient_id", "")).strip()
        if not patient_id:
            return points
        for row in self.history_data or []:
            if str(row.get("drug", "")).lower() != "vancomycin":
                continue
            if str(row.get("patient_id", "")).strip() != patient_id:
                continue
            events = (row.get("inputs") or {}).get("episode_events") or []
            ts = str(row.get("timestamp", ""))
            method = str(row.get("method", ""))
            for ev in events:
                if "sample" not in str(ev.get("event_type", "")).lower():
                    continue
                t_h = self._safe_optional_float(ev.get("time_h"))
                c = self._safe_optional_float(ev.get("level_mg_l"))
                if t_h is None or c is None:
                    continue
                points.append((t_h, c, f"{ts} | {method}"))
        return points

    def _build_dose_event_traces(self, fig: go.Figure, dose_events: list[dict], y_anchor: float) -> None:
        color_map = {"loading_dose": "#f59e0b", "maintenance_dose": "#2563eb", "extra_dose": "#ef4444"}
        grouped: dict[str, list[tuple[float, str]]] = {"loading_dose": [], "maintenance_dose": [], "extra_dose": []}
        for ev in dose_events:
            t = float(ev.get("time", 0.0))
            et = str(ev.get("event_type", "maintenance_dose")).lower()
            grouped.setdefault(et, []).append((t, f"{et} | dose={ev.get('dose','-')} mg | tinf={ev.get('tinf','-')}h | tau={ev.get('tau','-')}"))
            color = color_map.get(et, "#64748b")
            fig.add_vline(x=t, line_dash="dash", line_color=color, opacity=0.7)
            if hasattr(self, "toggle_dose_annotations") and self.toggle_dose_annotations.isChecked():
                fig.add_annotation(
                    x=t,
                    y=1.02,
                    xref="x",
                    yref="paper",
                    text=f"{et}<br>{ev.get('dose','-')} mg",
                    showarrow=False,
                    font=dict(size=9, color=color),
                )
        for et, entries in grouped.items():
            if not entries:
                continue
            fig.add_trace(
                go.Scatter(
                    x=[e[0] for e in entries],
                    y=[y_anchor] * len(entries),
                    mode="markers",
                    name=f"Dose: {et}",
                    marker=dict(size=10, symbol="triangle-down", color=color_map.get(et, "#64748b")),
                    text=[e[1] for e in entries],
                    hovertemplate="%{text}<br>t=%{x}h<extra></extra>",
                )
            )

    def _build_regimen_overlay_traces(self, fig: go.Figure, view_mode: str) -> None:
        if not self.results or not self.results.get("pk"):
            return
        pk = self.results["pk"]
        show_conc = bool(hasattr(self, "toggle_regimen_conc") and self.toggle_regimen_conc.isChecked())
        show_auc = bool(hasattr(self, "toggle_regimen_auc") and self.toggle_regimen_auc.isChecked())
        options = (pk.get("regimen_options") or [])[:3]
        for idx, opt in enumerate(options):
            tau = float(opt.get("tau") or 12.0)
            peak = float(opt.get("peak") or 0.0)
            trough = float(opt.get("trough") or 0.0)
            x = [0.0, tau / 2.0, tau]
            y = [peak, (peak + trough) / 2.0, trough]
            if view_mode == "auc":
                if not show_auc:
                    continue
                fig.add_trace(go.Scatter(x=x, y=y, fill="tozeroy", mode="lines", opacity=0.15 if idx else 0.3, name=f"Regimen AUC {idx+1}"))
            else:
                if not show_conc:
                    continue
                fig.add_trace(go.Scatter(x=x, y=y, mode="lines", opacity=0.35 if idx else 0.8, name=f"Regimen {idx+1}: {opt.get('dose',0):.0f} mg q{tau:.0f}h"))

    def render_plot(self, spec: dict):
        if getattr(self, "_plot_render_in_progress", False):
            print("[DEBUG][PLOT] render skipped: already in progress.")
            return
        self._plot_render_in_progress = True
        try:
            self._last_plot_spec = spec or {}
            render_signature = (
                str(spec.get("title", "")),
                bool(hasattr(self, "viz_mode_tabs") and self.viz_mode_tabs.currentIndex() == 1),
                str(self.view_combo.currentText()) if hasattr(self, "view_combo") else "",
            )
            if (not self._is_visualization_tab_active()) or (not self._is_plot_view_visible()):
                if getattr(self, "_plot_render_deferred", False) and getattr(self, "_last_render_signature", None) == render_signature:
                    return
                self._pending_plot_spec = spec or {}
                self._plot_render_deferred = True
                self._last_render_signature = render_signature
                print("[DEBUG][PLOT] deferred render set.")
                return
            self._plot_render_deferred = False
            single = spec.get("single_model") or {}
            avg = spec.get("model_averaging") or {}
            pred_x = list(single.get("pred_x") or spec.get("current_x", []) or [])
            pred_y = list(single.get("pred_y") or spec.get("current_y", []) or [])
            obs_x = list(single.get("obs_x") or spec.get("obs_x", []) or [])
            obs_y = list(single.get("obs_y") or spec.get("obs_y", []) or [])
            dose_events = list(single.get("dose_events") or spec.get("dose_events", []) or [])
            show_averaging = hasattr(self, "viz_mode_tabs") and self.viz_mode_tabs.currentIndex() == 1
            view_mode = "auc" if hasattr(self, "view_combo") and self.view_combo.currentText() == "AUC" else "concentration"
            fig = go.Figure()
            if show_averaging and (not hasattr(self, "toggle_overlay") or self.toggle_overlay.isChecked()):
                for overlay in avg.get("overlays", []):
                    fig.add_trace(go.Scatter(x=overlay.get("x", []), y=overlay.get("y", []), mode="lines", name=f"Avg {overlay.get('label','model')}", opacity=0.55))
            elif (not hasattr(self, "toggle_fit") or self.toggle_fit.isChecked()) and pred_x and pred_y:
                fig.add_trace(go.Scatter(x=pred_x, y=pred_y, mode="lines", name=str(single.get("label") or "Fitted"), line=dict(width=2.5)))
            observed_master = not hasattr(self, "toggle_obs") or self.toggle_obs.isChecked()
            if observed_master and (not hasattr(self, "toggle_current_samples") or self.toggle_current_samples.isChecked()) and obs_x and obs_y:
                fig.add_trace(go.Scatter(x=obs_x, y=obs_y, mode="markers", name="Aktuális observed", marker=dict(size=10, color="#16a34a")))
            if observed_master and hasattr(self, "toggle_history_samples") and self.toggle_history_samples.isChecked():
                hp = self._collect_history_sample_points()
                if hp:
                    fig.add_trace(go.Scatter(x=[p[0] for p in hp], y=[p[1] for p in hp], mode="markers", name="Korábbi beteg minták", marker=dict(size=8, color="#a855f7", symbol="diamond"), text=[p[2] for p in hp], hovertemplate="%{text}<br>t=%{x}h, C=%{y}<extra></extra>"))
            if (not hasattr(self, "toggle_dose_events") or self.toggle_dose_events.isChecked()) and dose_events:
                self._build_dose_event_traces(fig, dose_events, max(pred_y + obs_y + [1.0]) * 1.05)
            if view_mode == "auc" and pred_x and pred_y:
                fig.add_trace(go.Scatter(x=pred_x, y=pred_y, fill="tozeroy", mode="lines", opacity=0.25, name="AUC area"))
            self._build_regimen_overlay_traces(fig, view_mode)
            mic_value = (self.results or {}).get("pk", {}).get("auc_mic")
            subtitle = f"AUC/MIC: {self._fmt_float(mic_value, 1, na='n.a.')}" if mic_value is not None else "MIC nincs megadva"
            fig.update_layout(title=f"{spec.get('title', 'Vancomycin PK timeline')} — {'Model averaging' if show_averaging else 'Single model'}<br><sup>{subtitle}</sup>", xaxis_title="Idő (óra)", yaxis_title="Koncentráció (mg/L)" if view_mode == "concentration" else "Expozíció (relatív)", template="plotly_white", margin=dict(l=20, r=20, t=70, b=30), height=620)
            view = getattr(self, "viz_plot_view", None)
            if view is None or not hasattr(view, "setHtml"):
                return
            print("[DEBUG][PLOT] render target widget class:", type(view).__name__)
            request_id = int(getattr(self, "_plot_request_counter", 0)) + 1
            self._plot_request_counter = request_id
            self._active_plot_request_id = request_id
            print(f"[DEBUG][PLOT] render request started: id={request_id}")
            plot_config = {"displayModeBar": True, "scrollZoom": True, "responsive": True, "displaylogo": False}
            html = pio.to_html(
                fig,
                include_plotlyjs="inline",
                full_html=True,
                default_height="620px",
                default_width="100%",
                div_id="vanco_plot_chart",
                config=plot_config,
            )
            print("[DEBUG][PLOT] html length:", len(html))
            print("[DEBUG][PLOT] contains 'plotly':", "plotly" in html.lower())
            try:
                view.setHtml(html, QUrl.fromLocalFile(str(Path.cwd()) + "/"))
            except TypeError:
                view.setHtml(html)
            self._plot_renderer_state = "Plotly loading" if self._is_plot_webengine() else "Non-Plotly HTML widget"
            self._plot_retry_done = False
            self._plot_request_states = getattr(self, "_plot_request_states", {})
            self._plot_request_states[request_id] = {
                "single": single,
                "avg": avg,
                "trace_count": len(fig.data),
                "pred_x": pred_x,
                "pred_y": pred_y,
                "obs_x": obs_x,
                "obs_y": obs_y,
                "pending": True,
                "succeeded": False,
                "fallback_executed": False,
            }
            self._update_plot_summary(single, avg, len(fig.data), self._plot_renderer_state)
            if self._is_plot_webengine() and hasattr(view, "loadFinished") and not getattr(self, "_plot_load_finished_hooked", False):
                def _on_load_finished(ok: bool):
                    active_id = int(getattr(self, "_active_plot_request_id", -1))
                    print(f"[DEBUG][PLOT] loadFinished({ok}): id={active_id}")
                    state = (getattr(self, "_plot_request_states", {}) or {}).get(active_id, {})
                    if not state:
                        return
                    print(f"[DEBUG][PLOT] request state before handling: id={active_id} state={state}")
                    if ok:
                        if state.get("fallback_executed"):
                            print(f"[DEBUG][PLOT] late success ignored after fallback: id={active_id}")
                            return
                        timer = getattr(self, "_plot_fallback_timer", None)
                        if timer is not None and timer.isActive() and getattr(self, "_plot_fallback_request_id", -1) == active_id:
                            timer.stop()
                            print(f"[DEBUG][PLOT] delayed fallback canceled: id={active_id}")
                        state["succeeded"] = True
                        state["pending"] = False
                        self._plot_renderer_state = "Plotly"
                        self._update_plot_summary(state.get("single", {}), state.get("avg", {}), int(state.get("trace_count", 0)), self._plot_renderer_state)
                        print(f"[DEBUG][PLOT] final renderer state: {self._plot_renderer_state}")
                        return
                    self._schedule_plot_fallback(active_id)
                view.loadFinished.connect(_on_load_finished)
                self._plot_load_finished_hooked = True
        finally:
            self._plot_render_in_progress = False

    def calc_vancomycin(self, pk: dict, method: str) -> dict:
        print(f"[DEBUG][UI] calc_vancomycin input_method={method}")
        selected_model_key = (self.model_override_combo.currentData() if hasattr(self, "model_override_combo") else None) or None
        if method == "Klasszikus":
            selected_model_key = "trapezoid_classic"
        print(f"[DEBUG][UI] calc_vancomycin ui_selected_model_key={selected_model_key}")
        print(f"[DEBUG][UI] calc_vancomycin payload_selected_model_key={pk.get('selected_model_key')}")
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
                hsct=bool(pk.get("hsct")),
                patient_id=str(pk.get("patient_id", "")),
                patient_name=str(pk.get("patient_name", "")),
                method=method,
                height_cm=float(pk.get("height", 170.0)),
                dose_number=int(pk.get("dose_number", 1)),
                selected_model_key=selected_model_key,
                history_rows=self.history_data,
                episode_events=pk.get("episode_events", []),
            )
        )
        print("[DEBUG][UI] mapped result keys:", sorted(result.keys()))
        print(
            "[DEBUG][UI] mapped values:",
            {
                "cl_l_h": result.get("cl_l_h"),
                "vd_l": result.get("vd_l"),
                "crcl": result.get("crcl"),
                "auc24": result.get("auc24"),
                "has_plot": bool((result.get("plot") or {}).get("current_x") or (result.get("plot") or {}).get("obs_x")),
                "used_r_backend": result.get("used_r_backend"),
                "fallback_used": result.get("fallback_used"),
            },
        )
        is_classical_mode = method == "Klasszikus" or result.get("selected_model_key") == "trapezoid_classic"

        auto = result.get("auto_selection", {})
        fit_summary = result.get("fit_summary", [])
        fit_lines = [
            f"- {item['model_key']}: RMSE {item['rmse']:.2f}, MAE {item['mae']:.2f}, score {item['combined_score']:.3f}"
            for item in fit_summary[:5]
        ]
        history_summary = result.get("history_summary_by_antibiotic", {})
        history_text = ", ".join(f"{k}: {v}" for k, v in history_summary.items()) if history_summary else "nincs korábbi epizód"
        weight_metrics = result.get("weight_metrics", {})
        dist = result.get("distribution_assessment", {})
        trap = result.get("trapezoid_assessment", {})
        regimen_options = result.get("regimen_options", [])
        support = dist.get("supporting_metrics", {})
        target_assessment = result.get("target_assessment", {})
        toxicity_assessment = result.get("toxicity_assessment", {})
        mic_primary = target_assessment.get("target_basis") == "auc_mic_primary"

        report = [
            f"VANCOMYCIN – {method}",
            f"Számolási motor: {'R Bayesian backend' if result.get('engine_source') == 'R_BACKEND' else ('Python fallback' if result.get('engine_source') == 'PYTHON_FALLBACK' else 'Klasszikus Python')}",
            "",
            "PK/PD",
            f"- AUC24: {self._fmt_float(result.get('auc24'), 1)} mg·h/L",
            f"- AUC/MIC: {self._fmt_float(result.get('auc_mic'), 1, na='n.a.')}",
            f"- Peak: {self._fmt_float(result.get('peak'), 1)} mg/L | Trough: {self._fmt_float(result.get('trough'), 1)} mg/L",
            f"- CL: {self._fmt_float(result.get('cl_l_h'), 2)} L/h | Vd: {self._fmt_float(result.get('vd_l'), 2)} L | CrCl: {self._fmt_float(result.get('crcl'), 1)} mL/perc",
            (
                "- MIC rendelkezésre áll, ezért az elsődleges PK/PD cél az AUC/MIC >= 400; "
                "az AUC24 a túlzott expozíció megítélésére is figyelembe vett."
                if mic_primary
                else "- MIC nem áll rendelkezésre, ezért az értékelés AUC24 célablak (400–600 mg·h/L) alapján történik."
            ),
            "",
            "Súly és eloszlási mutatók",
            f"- ABW: {self._fmt_float(weight_metrics.get('abw_kg'), 1)} kg | IBW: {self._fmt_float(weight_metrics.get('ibw_kg'), 1)} kg | AdjBW: {self._fmt_float(weight_metrics.get('adjbw_kg'), 1)} kg",
            f"- Vd/ABW: {self._fmt_float(support.get('vd_l_per_kg_actual'), 2, na='n.a.')} L/kg | "
            f"Vd/IBW: {self._fmt_float(support.get('vd_l_per_kg_ideal'), 2, na='n.a.')} L/kg | "
            f"Vd/AdjBW: {self._fmt_float(support.get('vd_l_per_kg_adjusted'), 2, na='n.a.')} L/kg",
            "",
            "Az 1-kompartmentes közelítés értékelése",
            f"- 1-kompartmentes közelítés valószínűsége: {'igen' if dist.get('one_compartment_plausible') else 'csökkent'}",
            f"- Az 1-kompartmentes közelítés megbízhatósága: "
            f"{({'high': 'magas', 'moderate': 'közepes', 'low': 'alacsony'}.get(str(dist.get('confidence')), 'n.a.'))}",
            f"- Komplex kinetika gyanúja: {'igen' if dist.get('complex_kinetics_suspected') else 'nem'}",
            f"- Trapezoid alkalmazhatóság: {'igen' if trap.get('recommended') else 'óvatosan'}",
        ]
        for line in dist.get("reason_lines", []):
            report.append(f"- {line}")
        for line in dist.get("red_flags", []):
            report.append(f"- Figyelmeztetés: {line}")
        if toxicity_assessment.get("toxicity_flag"):
            report.extend(["", "Toxicitási értékelés (kiemelt)"])
            for line in toxicity_assessment.get("message_lines", []):
                report.append(f"- {line}")
        if dist.get("complex_kinetics_suspected") or dist.get("confidence") == "low":
            report.append("- Bayesian/populációs modell előnyösebb lehet.")
        if not is_classical_mode:
            active_keys = [m.key for m in active_models()]
            bayes_compare_lines = [
                f"- Aktív modellek: {', '.join(active_keys)}",
                f"- Választott modell: {result.get('selected_model_key', '-')}",
            ]
            if fit_summary:
                bayes_compare_lines.extend(
                    [
                        f"- {item.get('model_key', '-')}: AUC24={self._fmt_float(item.get('auc24'), 1)}, "
                        f"Trough={self._fmt_float(item.get('trough'), 1)}, "
                        f"RMSE={self._fmt_float(item.get('rmse'), 3)}, MAE={self._fmt_float(item.get('mae'), 3)}"
                        for item in fit_summary[:3]
                    ]
                )
            else:
                bayes_compare_lines.append(f"- Selector indoklás: {auto.get('rationale', '-')}")
            if result.get("uncertainty_note"):
                bayes_compare_lines.append(f"- Backend megjegyzés: {result.get('uncertainty_note')}")
            report.extend(
                [
                    "",
                    "Auto-select",
                    f"- Ajánlott modell: {auto.get('recommended_model_key', '-')}",
                    f"- Alternatívák: {', '.join(auto.get('alternative_model_keys', [])) if auto.get('alternative_model_keys') else 'nincs'}",
                    f"- Bayesian preferált: {'igen' if auto.get('bayesian_preferred') else 'nem'}",
                    f"- Trapezoid használható: {'igen' if auto.get('trapezoid_eligible') else 'nem'}",
                    f"- Indoklás: {auto.get('rationale', '-')}",
                    "",
                    "Final ranker",
                    f"- Kiválasztott modell: {result.get('selected_model_key', '-')}",
                    f"- Magyarázat: {result.get('final_explanation', '-')}",
                    "",
                    "Bayesian model összehasonlítás",
                    *bayes_compare_lines,
                    "",
                    "Model fit rangsor",
                    *(fit_lines or ["- nincs modellillesztési adat"]),
                    "",
                    "Előzmény panel (minden antibiotikum)",
                    f"- Korábbi epizódok: {history_text}",
                ]
            )
        else:
            report.extend(["", "Klasszikus trapezoid számítás.", f"- Magyarázat: {result.get('final_explanation', '-')}", ""])
        report.extend(["", "Regimen opciók"])
        if dist.get("confidence") == "low" or dist.get("complex_kinetics_suspected"):
            report.append("- Az alábbi klasszikus adagolási opciók tájékoztató jellegűek; komplex kinetika gyanúja esetén Bayesian megközelítés előnyösebb lehet.")
        if regimen_options:
            for idx, opt in enumerate(regimen_options[:5], start=1):
                line = (
                    f"{idx}. {opt.get('dose', 0):.0f} mg q{opt.get('tau', 0):.0f}h — "
                    f"prediktált AUC24: {self._fmt_float(opt.get('auc24'), 1)} (cél 400–600), "
                    f"trough: {self._fmt_float(opt.get('trough'), 1)}, "
                    f"peak: {self._fmt_float(opt.get('peak'), 1)}"
                )
                if mic_primary and opt.get("auc_mic") is not None:
                    line += (
                        f", AUC/MIC: {self._fmt_float(opt.get('auc_mic'), 1, na='n.a.')} (elsődleges cél ≥400)"
                    )
                if opt.get("efficacy_toxicity_mismatch"):
                    line += " — ⚠ hatásosság/toxicitás mismatch: magas expozíció mellett sem teljesül az elsődleges cél."
                elif opt.get("toxicity_flag"):
                    line += " — ⚠ fokozott toxicitási kockázat (AUC24 > 600)."
                report.append(line)
        else:
            report.append("- Nincs elérhető regimen opció.")

        plot = result.get("plot") or {
            "title": "Vancomycin koncentráció-idő profil",
            "current_x": [pk["t1"], pk["t2"]],
            "current_y": [result["peak"], result["trough"]],
            "best_x": [pk["t1"], pk["t2"]],
            "best_y": [result["peak"], result["trough"]],
            "obs_x": [pk["t1"], pk["t2"]],
            "obs_y": [pk["c1"], pk["c2"]],
        }
        if result.get("selected_model_key") == "trapezoid_classic":
            obs_x = [float(pk["t1"]), float(pk["t2"])]
            obs_y = [float(pk["c1"]), float(pk["c2"])]
            dose_events = []
            for event in pk.get("episode_events", []) or []:
                kind = str(event.get("event_type", "")).lower()
                if "dose" not in kind:
                    continue
                t_h = self._safe_optional_float(event.get("time_h"))
                if t_h is None:
                    continue
                dose_events.append({"event_type": kind, "time": t_h, "dose": self._safe_optional_float(event.get("dose_mg")) or 0.0})
            plot = {
                "title": "Vancomycin klasszikus trapezoid",
                "single_model": {
                    "label": "Klasszikus trapezoid (steady-state)",
                    "obs_x": obs_x,
                    "obs_y": obs_y,
                    "pred_x": obs_x,
                    "pred_y": obs_y,
                    "dose_events": dose_events,
                    "fit": {"rmse": 0.0, "mae": 0.0},
                },
                "model_averaging": {
                    "overlays": [
                        {
                            "label": "Klasszikus trapezoid",
                            "weight": 1.0,
                            "rmse": 0.0,
                            "mae": 0.0,
                            "x": obs_x,
                            "y": obs_y,
                            "auc24": round(float(result.get("auc24", 0.0)), 2),
                            "auc_mic": result.get("auc_mic"),
                        }
                    ]
                },
                "current_x": obs_x,
                "current_y": obs_y,
                "best_x": obs_x,
                "best_y": obs_y,
                "obs_x": obs_x,
                "obs_y": obs_y,
                "metadata": {"mode": "trapezoid_classic"},
                "warnings": result.get("warnings", []),
                "errors": result.get("errors", []),
            }
        plot.setdefault("metadata", {})
        if isinstance(plot["metadata"], dict):
            active_plot_mode = "model_averaging" if hasattr(self, "viz_mode_tabs") and self.viz_mode_tabs.currentIndex() == 1 else "single_model"
            plot["metadata"].update(
                {
                    "active_plot_mode": active_plot_mode,
                    "active_model_key": result.get("selected_model_key"),
                    "available_models": [m.key for m in active_models()],
                    "is_model_averaging": bool((plot.get("model_averaging") or {}).get("overlays")),
                    "layer_visibility": {
                        "fit": bool(not hasattr(self, "toggle_fit") or self.toggle_fit.isChecked()),
                        "obs": bool(not hasattr(self, "toggle_obs") or self.toggle_obs.isChecked()),
                        "dose_events": bool(not hasattr(self, "toggle_dose_events") or self.toggle_dose_events.isChecked()),
                        "overlay": bool(not hasattr(self, "toggle_overlay") or self.toggle_overlay.isChecked()),
                    },
                    "engine_source": result.get("engine_source"),
                    "used_r_backend": result.get("used_r_backend"),
                    "fallback_used": result.get("fallback_used"),
                    "fallback_reason": result.get("fallback_reason"),
                    "debug": result.get("debug", {}),
                }
            )

        ui_result = {
            "drug": "Vancomycin",
            "method": method,
            "status": result["status"],
            "primary": (
                f"AUC/MIC {self._fmt_float(result.get('auc_mic'), 1, na='n.a.')}"
                if target_assessment.get("target_basis") == "auc_mic_primary"
                else f"AUC24 {self._fmt_float(result.get('auc24'), 1)}"
            ),
            "secondary": f"CL {self._fmt_float(result.get('cl_l_h'), 2)} L/h",
            "regimen": f"{result['suggestion']['best']['dose']:.0f} mg q{result['suggestion']['best']['tau']:.0f}h",
            "status_sub": auto.get("rationale", result["status"]),
            "report": "\n".join(report),
            "pk": result,
            "suggestion": result["suggestion"],
            "plot": plot,
            "engine_source": result.get("engine_source"),
            "used_r_backend": result.get("used_r_backend"),
            "fallback_used": result.get("fallback_used"),
            "fallback_reason": result.get("fallback_reason"),
        }
        self._update_structured_result_views(result)
        return ui_result

    def _update_structured_result_views(self, pk_result: dict) -> None:
        if not pk_result:
            return
        is_classical = pk_result.get("selected_model_key") == "trapezoid_classic"
        if hasattr(self, "pkpd_table"):
            rows = [
                [
                    self._fmt_float(pk_result.get("auc24"), 1),
                    self._fmt_float(pk_result.get("auc_mic"), 1),
                    self._fmt_float(pk_result.get("peak"), 1),
                ],
                [
                    f"Trough {self._fmt_float(pk_result.get('trough'), 1)}",
                    f"CL {self._fmt_float(pk_result.get('cl_l_h'), 2)}",
                    f"Vd {self._fmt_float(pk_result.get('vd_l'), 2)}",
                ],
                [
                    f"ke {self._fmt_float(pk_result.get('ke'), 3)}",
                    f"Half-life {self._fmt_float(pk_result.get('half_life'), 2)}",
                    f"CrCl {self._fmt_float(pk_result.get('crcl'), 1)}",
                ],
            ]
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    self.pkpd_table.setItem(r, c, QTableWidgetItem(value))
        if hasattr(self, "final_decision_browser"):
            if is_classical:
                self.final_decision_browser.setHtml("<h3>Final decision</h3><p>Klasszikus módban nincs Bayesian final ranker.</p>")
            else:
                self.final_decision_browser.setHtml(
                    f"<h3>Final decision</h3><p><b>Kiválasztott modell:</b> {pk_result.get('selected_model_key', '-')}</p>"
                    f"<p>{pk_result.get('final_explanation', '-')}</p>"
                )
        if hasattr(self, "auto_select_browser"):
            auto = pk_result.get("auto_selection", {})
            if is_classical:
                self.auto_select_browser.setHtml("<h3>Automatikus modellválasztás</h3><p>Klasszikus módban rejtve.</p>")
            else:
                self.auto_select_browser.setHtml(
                    "<h3>Automatikus modellválasztás</h3>"
                    f"<p><b>Javasolt:</b> {auto.get('recommended_model_key', '-')}</p>"
                    f"<p><b>Alternatívák:</b> {', '.join(auto.get('alternative_model_keys', [])) or 'nincs'}</p>"
                    f"<p><b>Bayesian preferált:</b> {'igen' if auto.get('bayesian_preferred') else 'nem'}</p>"
                    f"<p><b>Trapezoid használható:</b> {'igen' if auto.get('trapezoid_eligible') else 'nem'}</p>"
                    f"<p><b>Indoklás:</b> {auto.get('rationale', '-')}</p>"
                )
        if hasattr(self, "model_meta_browser"):
            selected_key = pk_result.get("selected_model_key")
            if selected_key == "trapezoid_classic":
                self.model_meta_browser.setHtml(
                    "<h3>Modell meta</h3><p><b>Klasszikus trapezoid (steady-state)</b></p>"
                    "<p>Nem populációs/Bayesian modell, hanem kétpontos klasszikus becslés.</p>"
                )
                selected = None
            else:
                selected = next((m for m in MODELS if m.key == selected_key), None)
            if selected is None:
                if selected_key != "trapezoid_classic":
                    self.model_meta_browser.setHtml("<h3>Modell meta</h3><p>Nincs kiválasztott modell.</p>")
            else:
                self.model_meta_browser.setHtml(
                    "<h3>Modell meta</h3>"
                    f"<p><b>{selected.label}</b></p>"
                    f"<p>Populáció: {selected.population}</p>"
                    f"<p>Kötelező covariate-ek: {', '.join(selected.required_covariates)}</p>"
                )
        if hasattr(self, "fit_table"):
            self.fit_table.setRowCount(0)
            if is_classical:
                return
            for item in pk_result.get("fit_summary", []):
                row = self.fit_table.rowCount()
                self.fit_table.insertRow(row)
                values = [
                    item.get("model_key"),
                    f"{item.get('rmse', 0.0):.3f}",
                    f"{item.get('mae', 0.0):.3f}",
                    f"{item.get('combined_score', 0.0):.3f}",
                    f"{item.get('cl_l_h', '-')}",
                    f"{item.get('vd_l', '-')}",
                    f"{item.get('auc24', '-')}",
                    f"{item.get('auc_mic', '-')}",
                    "ok",
                ]
                for col, value in enumerate(values):
                    self.fit_table.setItem(row, col, QTableWidgetItem(str(value)))
        if hasattr(self, "recommendation_browser"):
            suggestion = pk_result.get("suggestion", {}).get("best", {})
            dist = pk_result.get("distribution_assessment", {})
            options = pk_result.get("regimen_options", [])
            target_assessment = pk_result.get("target_assessment", {})
            toxicity_assessment = pk_result.get("toxicity_assessment", {})
            mic_primary = target_assessment.get("target_basis") == "auc_mic_primary"
            warning = ""
            if dist.get("confidence") == "low" or dist.get("complex_kinetics_suspected"):
                warning = "<p><i>Az opciók tájékoztató jellegűek; komplex kinetika gyanúja esetén Bayesian megközelítés előnyösebb lehet.</i></p>"
            toxicity_html = ""
            if toxicity_assessment.get("toxicity_flag"):
                tox_lines = "".join(f"<li>{line}</li>" for line in toxicity_assessment.get("message_lines", []))
                toxicity_html = f"<p><b>Toxicitási figyelmeztetés:</b></p><ul>{tox_lines}</ul>"
            option_lines = "".join(
                [
                    f"<li>{opt.get('dose', 0):.0f} mg q{opt.get('tau', 0):.0f}h — "
                    f"AUC24 {self._fmt_float(opt.get('auc24'), 1)}"
                    + (" (cél 400–600)" if not mic_primary else " (biztonsági guardrail)")
                    + f", trough {self._fmt_float(opt.get('trough'), 1)}, peak {self._fmt_float(opt.get('peak'), 1)}"
                    + (
                        f", AUC/MIC {self._fmt_float(opt.get('auc_mic'), 1, na='n.a.')} (elsődleges cél ≥400)"
                        if mic_primary and opt.get("auc_mic") is not None
                        else ""
                    )
                    + "</li>"
                    for opt in options[:5]
                ]
            )
            target_note = (
                "<p><b>PK/PD cél:</b> MIC elérhető → elsődleges cél AUC/MIC ≥400; AUC24 túlzott expozíció guardrail.</p>"
                if mic_primary
                else "<p><b>PK/PD cél:</b> MIC hiányzik → AUC24 célablak 400–600.</p>"
            )
            self.recommendation_browser.setHtml(
                f"<h3>Recommendation</h3><p><b>Expozíció:</b> {pk_result.get('status', '-')}</p>"
                + target_note
                + (
                f"<p><b>Javaslat:</b> {suggestion.get('dose', 0):.0f} mg q{suggestion.get('tau', 0):.0f}h | "
                f"AUC24 {self._fmt_float(suggestion.get('auc24'), 1)}, "
                f"trough {self._fmt_float(suggestion.get('trough'), 1)}, "
                f"peak {self._fmt_float(suggestion.get('peak'), 1)}</p>"
                f"{toxicity_html}"
                f"{warning}"
                f"<p><b>Top opciók:</b></p><ol>{option_lines or '<li>nincs</li>'}</ol>"
                )
            )
        if hasattr(self, "history_summary_browser"):
            summary = pk_result.get("history_summary_by_antibiotic", {})
            dose_info = ""
            if self._last_pk_payload:
                dose_info = (
                    f"<br/>Aktuális dózisesemény: {self._last_pk_payload.get('dose_number', 0)} "
                    f"(ebből előzmény: {self._last_pk_payload.get('prior_dose_events', 0)})"
                )
            text = "<br/>".join([f"{k}: {v} epizód" for k, v in summary.items()]) if summary else "Nincs korábbi epizód."
            self.history_summary_browser.setHtml(f"<h3>History summary</h3><p>{text}{dose_info}</p>")

    def _export_plot_to_png(self) -> Optional[str]:
        if not self.results or not MATPLOTLIB_UI_OK:
            return None
        spec = (self.results or {}).get("plot") or {}
        try:
            import tempfile

            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp.close()
            fig = plt.figure(figsize=(10, 5.6), dpi=160)
            ax = fig.add_subplot(111)
            if spec.get("single_model"):
                single = spec["single_model"]
                ax.plot(single.get("pred_x", []), single.get("pred_y", []), label=f"Single: {single.get('label','model')}", linewidth=2.2, color="#2563eb")
                ax.scatter(single.get("obs_x", []), single.get("obs_y", []), label="Observed", s=42, color="#16a34a")
                for event in single.get("dose_events", []):
                    ax.axvline(float(event.get("time", 0.0)), linestyle="--", linewidth=1.0, color="#94a3b8")
            if spec.get("model_averaging"):
                for overlay in spec["model_averaging"].get("overlays", []):
                    ax.plot(overlay.get("x", []), overlay.get("y", []), linewidth=1.2, alpha=0.55, linestyle=":", label=f"{overlay.get('label','model')} (w={overlay.get('weight',0):.2f})")
            if not spec.get("single_model"):
                ax.text(0.5, 0.5, "Még nincs számítási eredmény", transform=ax.transAxes, ha="center", va="center")
            ax.set_title(spec.get("title", "Vancomycin vizualizáció"))
            ax.set_xlabel("Óra")
            ax.set_ylabel("Koncentráció (mg/L)")
            ax.grid(True, alpha=0.25)
            ax.legend(loc="best")
            fig.tight_layout()
            fig.savefig(tmp.name, format="png", bbox_inches="tight")
            plt.close(fig)
            return tmp.name
        except Exception:
            return None

    def _render_report_pdf_to_path(self, path: str):
        if not self.latest_report or not self.results:
            raise ValueError("Nincs menthető riport.")
        title = f"Klinikai TDM riport – {self.results.get('drug', '—')} / {self.results.get('method', '—')}"
        render_simple_report_pdf(path, title=title, report_text=self.latest_report)

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
                "hsct": pk.get("hsct"),
                "arc": pk.get("arc"),
                "loading_dose": pk.get("loading_dose"),
                "loading_time_h": pk.get("loading_time_h"),
                "dose_count": pk.get("dose_count"),
                "episode_events": pk.get("episode_events", []),
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
