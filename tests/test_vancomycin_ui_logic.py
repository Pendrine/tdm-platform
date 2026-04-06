from types import SimpleNamespace

import pytest

main_window_module = pytest.importorskip("tdm_platform.ui.main_window", exc_type=ImportError)
MainWindow = main_window_module.MainWindow


class _DummyHtmlWidget:
    def __init__(self):
        self.html = ""
        self._cb = None
        self.loadFinished = SimpleNamespace(connect=self._connect)

    def setHtml(self, html, *_args):
        self.html = html

    def _connect(self, cb):
        self._cb = cb

    def emit_load_finished(self, ok: bool):
        if self._cb:
            self._cb(ok)

    def isVisible(self):
        return True

    def size(self):
        return SimpleNamespace(width=lambda: 800, height=lambda: 600)

    def setMinimumHeight(self, _h):
        return None


class _DummyFitTable:
    def __init__(self):
        self.rows = 0

    def setRowCount(self, n):
        self.rows = n

    def rowCount(self):
        return self.rows

    def insertRow(self, _row):
        self.rows += 1

    def setItem(self, *_args):
        return None


class _DummyLineEdit:
    def __init__(self, value: str, visible: bool = True):
        self._value = value
        self._visible = visible

    def text(self):
        return self._value

    def isVisible(self):
        return self._visible


def test_collect_pk_inputs_uses_fresh_event_samples_and_selected_model():
    dummy = SimpleNamespace()
    dummy._collect_common_with_events = lambda: {
        "episode_events": [
            {"event_type": "sample", "level_mg_l": 22},
            {"event_type": "sample", "level_mg_l": 11},
        ]
    }
    dummy.method_combo = SimpleNamespace(currentText=lambda: "Bayesian")
    dummy.model_override_combo = SimpleNamespace(currentData=lambda: "okada_2018")
    payload = MainWindow.collect_pk_inputs(dummy)
    assert payload["method"] == "Bayesian"
    assert payload["selected_model_key"] == "okada_2018"
    assert len([e for e in payload["episode_events"] if e["event_type"] == "sample"]) == 2


def test_render_plot_plotly_branch_generates_html_for_webview_like_widget():
    dummy = SimpleNamespace()
    dummy.viz_plot_view = _DummyHtmlWidget()
    spec = {
        "title": "Vancomycin",
        "single_model": {
            "label": "Hospitalized — Goti (2018)",
            "pred_x": [0, 1, 2],
            "pred_y": [20, 15, 10],
            "obs_x": [1, 2],
            "obs_y": [16, 11],
            "dose_events": [],
            "fit": {},
        },
        "model_averaging": {"overlays": []},
        "errors": [],
        "warnings": [],
    }
    MainWindow.render_plot(dummy, spec)
    assert "Plotly.newPlot" in dummy.viz_plot_view.html
    assert "vanco_plot_chart" in dummy.viz_plot_view.html


def test_render_plot_webview_fallback_renders_image_when_load_failed():
    if not getattr(main_window_module, "MATPLOTLIB_UI_OK", False):
        pytest.skip("Matplotlib UI fallback unavailable in this environment.")
    dummy = SimpleNamespace()
    dummy.viz_plot_view = _DummyHtmlWidget()
    spec = {
        "title": "Vancomycin",
        "single_model": {
            "label": "Hospitalized — Goti (2018)",
            "pred_x": [0, 1, 2],
            "pred_y": [20, 15, 10],
            "obs_x": [1, 2],
            "obs_y": [16, 11],
            "dose_events": [],
            "fit": {},
        },
        "model_averaging": {"overlays": []},
        "errors": [],
        "warnings": [],
    }
    MainWindow.render_plot(dummy, spec)
    dummy.viz_plot_view.emit_load_finished(False)
    assert "data:image/png;base64" in dummy.viz_plot_view.html


def test_classical_mode_hides_bayesian_sections_in_structured_views():
    dummy = SimpleNamespace()
    dummy._fmt_float = MainWindow._fmt_float
    dummy.pkpd_table = _DummyFitTable()
    dummy.final_decision_browser = _DummyHtmlWidget()
    dummy.auto_select_browser = _DummyHtmlWidget()
    dummy.model_meta_browser = _DummyHtmlWidget()
    dummy.fit_table = _DummyFitTable()
    MainWindow._update_structured_result_views(
        dummy,
        {
            "selected_model_key": "trapezoid_classic",
            "final_explanation": "klasszikus",
            "fit_summary": [{"model_key": "goti_2018"}],
            "auto_selection": {},
        },
    )
    assert "nincs Bayesian final ranker" in dummy.final_decision_browser.html
    assert "Klasszikus módban rejtve" in dummy.auto_select_browser.html
    assert dummy.fit_table.rowCount() == 0


def test_get_active_sample_times_and_levels_prefers_clinical_fields_when_visible():
    dummy = SimpleNamespace(
        t1_edit=_DummyLineEdit("2.0"),
        t2_edit=_DummyLineEdit("11.0"),
        level1_rel_edit=_DummyLineEdit("23.5"),
        level2_rel_edit=_DummyLineEdit("8.0"),
        level1_clin_edit=_DummyLineEdit("30.0", visible=True),
        level2_clin_edit=_DummyLineEdit("10.0", visible=True),
    )
    t1, c1, t2, c2, source = MainWindow._get_active_sample_times_and_levels(dummy)
    assert source == "clinical"
    assert (t1, c1, t2, c2) == ("2.0", "30.0", "11.0", "10.0")


def test_get_active_sample_times_and_levels_falls_back_to_relative_fields():
    dummy = SimpleNamespace(
        t1_edit=_DummyLineEdit("2.0"),
        t2_edit=_DummyLineEdit("11.0"),
        level1_rel_edit=_DummyLineEdit("23.5"),
        level2_rel_edit=_DummyLineEdit("8.0"),
    )
    t1, c1, t2, c2, source = MainWindow._get_active_sample_times_and_levels(dummy)
    assert source == "relative"
    assert (t1, c1, t2, c2) == ("2.0", "23.5", "11.0", "8.0")


def test_get_active_sample_times_and_levels_ignores_hidden_clinical_values():
    dummy = SimpleNamespace(
        t1_edit=_DummyLineEdit("2.0"),
        t2_edit=_DummyLineEdit("11.0"),
        level1_rel_edit=_DummyLineEdit("23.5"),
        level2_rel_edit=_DummyLineEdit("8.0"),
        level1_clin_edit=_DummyLineEdit("30.0", visible=False),
        level2_clin_edit=_DummyLineEdit("10.0", visible=False),
    )
    t1, c1, t2, c2, source = MainWindow._get_active_sample_times_and_levels(dummy)
    assert source == "relative"
    assert (t1, c1, t2, c2) == ("2.0", "23.5", "11.0", "8.0")


def test_show_history_detail_appends_user_timestamp_method_patient_audit_block():
    class _DummyHistoryDetail:
        def __init__(self):
            self.html = ""

        def append(self, txt):
            self.html += txt

    rendered_rows = []
    history_row = {
        "user": "nurse@example.com",
        "timestamp": "2026-03-31T10:00:00",
        "method": "Bayesian",
        "patient_id": "P-001",
    }
    dummy = SimpleNamespace(
        history_table=SimpleNamespace(property=lambda _k: [history_row], currentRow=lambda: 0),
        history_detail=_DummyHistoryDetail(),
        _history_tab=SimpleNamespace(render_detail=lambda *_args, **_kwargs: rendered_rows.append(history_row)),
        _username_for_email=lambda _email: "nurse.user",
    )
    MainWindow.show_history_detail(dummy)
    assert rendered_rows
    assert "Felhasználó:" in dummy.history_detail.html
    assert "Timestamp:" in dummy.history_detail.html
    assert "Method:" in dummy.history_detail.html
    assert "Patient ID:" in dummy.history_detail.html


def test_collect_history_sample_points_uses_event_datetime_window_and_reference_projection():
    ref_dt = main_window_module.datetime(2026, 4, 1, 8, 0, 0)
    dummy = SimpleNamespace(
        _last_pk_payload={
            "patient_id": "P-001",
            "episode_events": [
                {"event_datetime": "2026-04-01T10:00:00"},
                {"event_datetime": "2026-04-01T12:00:00"},
            ],
        },
        relative_reference_dt=SimpleNamespace(dateTime=lambda: SimpleNamespace(toPython=lambda: ref_dt)),
        history_data=[
            {
                "drug": "vancomycin",
                "patient_id": "P-001",
                "timestamp": "2026-04-01T00:00:00",
                "method": "Bayesian",
                "inputs": {
                    "episode_events": [
                        {"event_type": "sample", "level_mg_l": "20", "event_datetime": "2026-04-01T11:00:00"},
                        {"event_type": "sample", "level_mg_l": "19", "event_datetime": "2026-04-05T11:00:00"},
                    ]
                },
            }
        ],
        _safe_optional_float=MainWindow._safe_optional_float,
        _parse_event_datetime=MainWindow._parse_event_datetime,
    )
    points = MainWindow._collect_history_sample_points(dummy)
    assert len(points) == 1
    # 11:00 relative to 08:00 -> 3h (datetime fallback when explicit time_h is missing)
    assert abs(points[0]["time_h"] - 3.0) < 1e-6


def test_collect_history_sample_points_prefers_time_h_over_datetime_when_available():
    ref_dt = main_window_module.datetime(2026, 4, 1, 8, 0, 0)
    dummy = SimpleNamespace(
        _last_pk_payload={
            "patient_id": "P-001",
            "episode_events": [
                {"time_h": "2"},
                {"time_h": "12"},
            ],
        },
        relative_reference_dt=SimpleNamespace(dateTime=lambda: SimpleNamespace(toPython=lambda: ref_dt)),
        history_data=[
            {
                "drug": "vancomycin",
                "patient_id": "P-001",
                "timestamp": "2026-04-01T00:00:00",
                "method": "Bayesian",
                "inputs": {
                    "episode_events": [
                        {"event_type": "sample", "level_mg_l": "20", "time_h": "5", "event_datetime": "2026-04-03T11:00:00"},
                    ]
                },
            }
        ],
        _safe_optional_float=MainWindow._safe_optional_float,
        _parse_event_datetime=MainWindow._parse_event_datetime,
    )
    points = MainWindow._collect_history_sample_points(dummy)
    assert len(points) == 1
    assert abs(points[0]["time_h"] - 5.0) < 1e-6


def test_extract_history_patient_ids_returns_unique_case_insensitive_sorted_values():
    rows = [
        {"patient_id": "P-002"},
        {"patient_id": "p-001"},
        {"patient_id": "P-001"},
        {"patient_id": "  "},
        {},
    ]
    assert MainWindow._extract_history_patient_ids(rows) == ["p-001", "P-002"]


def test_expand_dose_events_for_plot_generates_intermediate_cycles_beyond_latest_sample():
    ref_dt = main_window_module.datetime(2026, 4, 1, 0, 0, 0)
    dummy = SimpleNamespace(
        _last_pk_payload={
            "dose": 1000,
            "tau": 8,
            "tinf": 1,
            "episode_events": [{"event_type": "maintenance_dose", "event_datetime": "2026-04-01T00:00:00"}],
        },
        relative_reference_dt=SimpleNamespace(dateTime=lambda: SimpleNamespace(toPython=lambda: ref_dt)),
        _safe_optional_float=MainWindow._safe_optional_float,
        _parse_event_datetime=MainWindow._parse_event_datetime,
    )
    expanded = MainWindow._expand_dose_events_for_plot(dummy, [], [2.0, 10.0], [0.0, 24.0])
    times = sorted([round(e["time"], 2) for e in expanded if e.get("event_type") == "maintenance_dose"])
    # at least 0,8,16,24 and one extra interval-end point at 32h due +tau extension
    assert times[:4] == [0.0, 8.0, 16.0, 24.0]
    assert 32.0 in times
