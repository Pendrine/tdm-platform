from __future__ import annotations

import sys
import traceback
import base64
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QDate, QDateTime, QTime
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
from tdm_platform.pk.vancomycin.model_library import MODELS
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
        self._remove_method_controls_from_action_bar()
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
        for edit in [
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
        ]:
            if edit is None:
                continue
            if hasattr(edit, "editingFinished"):
                edit.editingFinished.connect(self._sync_input_panel_to_episode_events)
            if hasattr(edit, "textChanged"):
                edit.textChanged.connect(lambda *_: self._sync_input_panel_to_episode_events())

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
            ("maintenance dose", "maintenance dose"),
            ("loading dose", "loading dose"),
            ("extra dose", "extra dose"),
            ("sample", "sample"),
            ("MIC result", "mic result"),
            ("creatinine result", "creatinine result"),
        ]

    def _set_event_type_widget(self, row: int, event_type: str) -> None:
        if not hasattr(self, "episode_events_table"):
            return
        combo = QComboBox()
        for label, value in self._event_type_options():
            combo.addItem(label, value)
        normalized = str(event_type or "").strip().lower().replace("_", " ")
        idx = combo.findData(normalized)
        if idx < 0:
            for i in range(combo.count()):
                if combo.itemText(i).strip().lower() == normalized:
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
        values = {
            "loading_dose": ["0.0", "loading dose", self.dose_edit.text().strip() or "1000", self.tinf_edit.text().strip() or "1.0", "", "", "", ""],
            "maintenance_dose": ["0.0", "maintenance dose", self.dose_edit.text().strip() or "1000", self.tinf_edit.text().strip() or "1.0", "", "", "", ""],
            "extra_dose": ["0.0", "extra dose", self.dose_edit.text().strip() or "500", self.tinf_edit.text().strip() or "1.0", "", "", "", ""],
            "sample": [self.t1_edit.text().strip() or "2.0", "sample", "", "", self.level1_rel_edit.text().strip() or "20", "", "", ""],
            "mic_result": ["0.0", "MIC result", "", "", "", self.mic_edit.text().strip() or "1.0", "", ""],
            "creatinine_result": ["0.0", "creatinine result", "", "", "", "", self.scr_edit.text().strip() or "90", ""],
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
            elif "creatinine" in kind:
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
        self.model_override_combo.addItem("Automatikus javaslat", "")
        self.model_override_combo.addItem("Klasszikus trapezoid (steady-state)", "trapezoid_classic")
        for model in MODELS:
            self.model_override_combo.addItem(model.label, model.key)
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
        top.addWidget(self.view_combo)
        for chk in [self.toggle_obs, self.toggle_fit, self.toggle_projection, self.toggle_dose_events, self.toggle_overlay]:
            top.addWidget(chk)
        top.addStretch(1)
        layout.addLayout(top)
        self.viz_mode_tabs = QTabWidget()
        self.viz_single = QTextBrowser()
        self.viz_averaging = QTextBrowser()
        self.viz_mode_tabs.addTab(self.viz_single, "Single model")
        self.viz_mode_tabs.addTab(self.viz_averaging, "Model averaging")
        self.viz_mode_tabs.currentChanged.connect(lambda *_: self.render_plot(self._last_plot_spec or {}))
        layout.addWidget(self.viz_mode_tabs)
        if hasattr(self, "plot_view") and self.plot_view is not None:
            self.viz_plot_view = self.plot_view
            self.viz_plot_view.setVisible(True)
        else:
            self.viz_plot_view = QTextBrowser()
        self.viz_plot_view.setMinimumHeight(460)
        self.viz_plot_view.setHtml("<p>Még nincs számítási eredmény.</p>")
        layout.addWidget(self.viz_plot_view, 1)
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
            res = self.calc_vancomycin(pk, "Auto")
            self.results = res
            self.latest_report = res["report"]
            self.result_text.setPlainText(res["report"])
            self.card_primary.update_card(res["primary"], f"{abx} – Auto")
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

    def methods_for_antibiotic(self, abx: str) -> list[str]:
        if abx == "Vancomycin":
            return ["Klasszikus", "Bayesian"]
        return ["Nincs implementálva"]

    def on_antibiotic_change(self):
        super().on_antibiotic_change()
        is_vanco = self.antibiotic_combo.currentText() == "Vancomycin"
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
        if hasattr(self, "method_combo") and self.method_combo.findText("Klasszikus") >= 0:
            self.method_combo.setCurrentText("Klasszikus")
        if hasattr(self, "episode_events_table"):
            self.episode_events_table.setRowCount(0)
            self._append_episode_event("maintenance_dose")
            self._append_episode_event("sample")
            self._append_episode_event("sample")
            self._sync_input_panel_to_episode_events()
        self._reset_non_vancomycin_views() if self.antibiotic_combo.currentText() != "Vancomycin" else None

    def collect_pk_inputs(self) -> dict:
        return self.collect_common()

    def _collect_episode_events(self) -> list[dict]:
        events: list[dict] = []
        if not hasattr(self, "episode_events_table"):
            return events
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
            self._set_event_type_widget(0, "maintenance dose")
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
            self.episode_events_table.setItem(sample_rows[0], 0, QTableWidgetItem(self.t1_edit.text().strip()))
            self.episode_events_table.setItem(sample_rows[0], 4, QTableWidgetItem(self.level1_rel_edit.text().strip()))
            self.episode_events_table.setItem(sample_rows[1], 0, QTableWidgetItem(self.t2_edit.text().strip()))
            self.episode_events_table.setItem(sample_rows[1], 4, QTableWidgetItem(self.level2_rel_edit.text().strip()))
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
                    self._set_event_type_widget(r, "loading dose")
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
                _upsert_row("mic result", 5, self.mic_edit.text().strip())
            if self.scr_edit.text().strip():
                _upsert_row("creatinine result", 6, self.scr_edit.text().strip())
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
        if len(sample_events) >= 2:
            payload["t1"], payload["c1"] = sample_events[0]
            payload["t2"], payload["c2"] = sample_events[1]
            if len(sample_events) >= 3:
                payload["t3"], payload["c3"] = sample_events[2]
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
            res = self.calc_vancomycin(pk, "Auto")
            self.results = res
            self.latest_report = res["report"]
            self.result_text.setPlainText(res["report"])
            self.card_primary.update_card(res["primary"], f"{abx} – Auto")
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
        if hasattr(self, "guide_browser"):
            self.guide_browser.setHtml(self.build_guide_html(abx, method))
        if hasattr(self, "evidence_browser"):
            self.evidence_browser.setHtml(self.build_evidence_html(abx, method))

    def build_guide_html(self, abx: str, method: str) -> str:
        if abx != "Vancomycin":
            return "<h2>Info</h2><p>Ehhez az antibiotikumhoz még nincs modell implementálva.</p>"
        items = []
        for model in MODELS:
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
        for model in MODELS:
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


    def render_plot(self, spec: dict):
        self._last_plot_spec = spec or {}
        single = spec.get("single_model") or {}
        avg = spec.get("model_averaging") or {}
        if single:
            fig = go.Figure()
            show_averaging = hasattr(self, "viz_mode_tabs") and self.viz_mode_tabs.currentIndex() == 1
            if show_averaging and avg and (not hasattr(self, "toggle_overlay") or self.toggle_overlay.isChecked()):
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
            if (not show_averaging) and (not hasattr(self, "toggle_fit") or self.toggle_fit.isChecked()):
                fig.add_trace(go.Scatter(x=single["pred_x"], y=single["pred_y"], mode="lines", name=f"Single: {single['label']}"))
            if not hasattr(self, "toggle_obs") or self.toggle_obs.isChecked():
                fig.add_trace(go.Scatter(x=single["obs_x"], y=single["obs_y"], mode="markers", name="Observed", marker=dict(size=10, color="green")))
            if (not hasattr(self, "toggle_dose_events") or self.toggle_dose_events.isChecked()) and single.get("dose_events"):
                for event in single.get("dose_events", []):
                    fig.add_vline(x=float(event.get("time", 0.0)), line_dash="dash", line_color="gray")
            fig.update_layout(
                title=f"{spec.get('title', 'Vancomycin')} — Single model + Model averaging",
                xaxis_title="Óra",
                yaxis_title="Koncentráció (mg/L)",
                template="plotly_white",
                margin=dict(l=30, r=30, t=50, b=30),
            )
            html = pio.to_html(fig, include_plotlyjs=True, full_html=False)
            if isinstance(getattr(self, "viz_plot_view", None), QTextBrowser) and MATPLOTLIB_UI_OK:
                try:
                    mfig = plt.figure(figsize=(8, 4), dpi=120)
                    ax = mfig.add_subplot(111)
                    if single.get("pred_x") and single.get("pred_y"):
                        ax.plot(single["pred_x"], single["pred_y"], label=single.get("label", "Model"), linewidth=2.0, color="#2563eb")
                    if single.get("obs_x") and single.get("obs_y"):
                        ax.scatter(single["obs_x"], single["obs_y"], label="Observed", color="#16a34a")
                    ax.set_xlabel("Óra")
                    ax.set_ylabel("Koncentráció (mg/L)")
                    ax.set_title(spec.get("title", "Vancomycin"))
                    ax.grid(True, alpha=0.3)
                    ax.legend(loc="best")
                    buffer = BytesIO()
                    mfig.tight_layout()
                    mfig.savefig(buffer, format="png")
                    plt.close(mfig)
                    png_b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
                    html = (
                        f"<h3>{spec.get('title', 'Vancomycin')}</h3>"
                        f"<img src='data:image/png;base64,{png_b64}' style='max-width:100%; height:auto;'/>"
                    )
                except Exception:
                    pass
            if hasattr(self, "viz_plot_view"):
                self.viz_plot_view.setHtml(html)
            if hasattr(self, "viz_single"):
                fit = single.get("fit", {})
                rmse = fit.get("rmse")
                mae = fit.get("mae")
                self.viz_single.setHtml(
                    f"<h3>{single.get('label','Single model')}</h3><p>RMSE: {rmse if rmse is not None else '-'} | MAE: {mae if mae is not None else '-'}</p>"
                )
            if hasattr(self, "viz_averaging"):
                self.viz_averaging.setHtml(
                    "<br/>".join(
                        [f"{overlay['label']}: w={overlay['weight']:.3f}, RMSE={overlay['rmse']:.3f}, MAE={overlay['mae']:.3f}" for overlay in avg.get("overlays", [])]
                    )
                    or "Nincs model averaging adat."
                )
            if hasattr(self, "model_avg_table"):
                self.model_avg_table.setRowCount(0)
                for overlay in avg.get("overlays", []):
                    row = self.model_avg_table.rowCount()
                    self.model_avg_table.insertRow(row)
                    values = [
                        overlay["label"],
                        f"{overlay['weight']:.3f}",
                        f"{overlay['rmse']:.3f}",
                        f"{overlay['mae']:.3f}",
                        f"{overlay.get('auc24', '-')}",
                        f"{overlay.get('auc_mic', '-')}",
                    ]
                    for col, value in enumerate(values):
                        self.model_avg_table.setItem(row, col, QTableWidgetItem(str(value)))
            return
        if hasattr(self, "viz_plot_view"):
            self.viz_plot_view.setHtml("<p>Még nincs számítási eredmény.</p>")
        return

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
                hsct=bool(pk.get("hsct")),
                patient_id=str(pk.get("patient_id", "")),
                patient_name=str(pk.get("patient_name", "")),
                method=method,
                height_cm=float(pk.get("height", 170.0)),
                dose_number=int(pk.get("dose_number", 1)),
                selected_model_key=(self.model_override_combo.currentData() if hasattr(self, "model_override_combo") else None) or None,
                history_rows=self.history_data,
                episode_events=pk.get("episode_events", []),
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
            }

        ui_result = {
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
        self._update_structured_result_views(result)
        return ui_result

    def _update_structured_result_views(self, pk_result: dict) -> None:
        if not pk_result:
            return
        if hasattr(self, "pkpd_table"):
            rows = [
                [f"{pk_result.get('auc24', 0.0):.1f}", f"{pk_result.get('auc_mic', 'n.a.')}", f"{pk_result.get('peak', 0.0):.1f}"],
                [f"Trough {pk_result.get('trough', 0.0):.1f}", f"CL {pk_result.get('cl_l_h', 0.0):.2f}", f"Vd {pk_result.get('vd_l', 0.0):.2f}"],
                [f"ke {pk_result.get('ke', 0.0):.3f}", f"Half-life {pk_result.get('half_life', 0.0):.2f}", f"CrCl {pk_result.get('crcl', 0.0):.1f}"],
            ]
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    self.pkpd_table.setItem(r, c, QTableWidgetItem(value))
        if hasattr(self, "final_decision_browser"):
            self.final_decision_browser.setHtml(
                f"<h3>Final decision</h3><p><b>Kiválasztott modell:</b> {pk_result.get('selected_model_key', '-')}</p>"
                f"<p>{pk_result.get('final_explanation', '-')}</p>"
            )
        if hasattr(self, "auto_select_browser"):
            auto = pk_result.get("auto_selection", {})
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
            self.recommendation_browser.setHtml(
                f"<h3>Recommendation</h3><p><b>Expozíció:</b> {pk_result.get('status', '-')}</p>"
                f"<p><b>Javaslat:</b> {suggestion.get('dose', 0):.0f} mg q{suggestion.get('tau', 0):.0f}h</p>"
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
