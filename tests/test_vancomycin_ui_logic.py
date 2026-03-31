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
