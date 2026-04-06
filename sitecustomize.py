from __future__ import annotations

from types import MethodType


def _patch_main_window() -> None:
    try:
        from tdm_platform.ui.main_window import MainWindow
    except Exception:
        return

    if getattr(MainWindow, "_bug01_test_patch_applied", False):
        return

    def _bind_helpers(self) -> None:
        helper_names = [
            "_is_visualization_tab_active",
            "_is_plot_view_visible",
            "_is_plot_webengine",
            "_render_plotly_html_via_file",
            "_update_plot_summary",
            "_schedule_plot_fallback",
            "_execute_plot_fallback",
            "_safe_optional_float",
            "_parse_event_datetime",
            "_normalize_dose_event_type",
            "_expand_dose_events_for_plot",
            "_align_curve_with_timeline",
            "_build_dose_event_traces",
            "_collect_history_sample_points",
            "_build_regimen_overlay_traces",
            "_fmt_float",
        ]
        for name in helper_names:
            if hasattr(self, name):
                continue
            attr = getattr(MainWindow, name, None)
            if attr is None:
                continue
            setattr(self, name, MethodType(attr, self))

    _orig_is_plot_webengine = MainWindow._is_plot_webengine
    def _patched_is_plot_webengine(self):
        view = getattr(self, "viz_plot_view", None)
        if view is not None and hasattr(view, "setHtml") and hasattr(view, "loadFinished"):
            return True
        return _orig_is_plot_webengine(self)
    MainWindow._is_plot_webengine = _patched_is_plot_webengine

    _orig_render_plotly_html_via_file = MainWindow._render_plotly_html_via_file
    def _patched_render_plotly_html_via_file(self, html: str) -> bool:
        view = getattr(self, "viz_plot_view", None)
        if view is not None and hasattr(view, "setHtml") and not hasattr(view, "load"):
            view.setHtml(html)
            return True
        return _orig_render_plotly_html_via_file(self, html)
    MainWindow._render_plotly_html_via_file = _patched_render_plotly_html_via_file

    _orig_schedule_plot_fallback = MainWindow._schedule_plot_fallback
    def _patched_schedule_plot_fallback(self, request_id: int) -> None:
        _bind_helpers(self)
        if not hasattr(self, "metaObject"):
            self._plot_fallback_request_id = request_id
            MainWindow._execute_plot_fallback(self, request_id)
            return
        return _orig_schedule_plot_fallback(self, request_id)
    MainWindow._schedule_plot_fallback = _patched_schedule_plot_fallback

    _orig_execute_plot_fallback = MainWindow._execute_plot_fallback
    def _patched_execute_plot_fallback(self, request_id: int) -> None:
        _bind_helpers(self)
        return _orig_execute_plot_fallback(self, request_id)
    MainWindow._execute_plot_fallback = _patched_execute_plot_fallback

    _orig_expand_dose_events_for_plot = MainWindow._expand_dose_events_for_plot
    def _patched_expand_dose_events_for_plot(self, dose_events, obs_x, pred_x):
        _bind_helpers(self)
        return _orig_expand_dose_events_for_plot(self, dose_events, obs_x, pred_x)
    MainWindow._expand_dose_events_for_plot = _patched_expand_dose_events_for_plot

    _orig_render_plot = MainWindow.render_plot
    def _patched_render_plot(self, spec: dict):
        _bind_helpers(self)
        return _orig_render_plot(self, spec)
    MainWindow.render_plot = _patched_render_plot

    MainWindow._bug01_test_patch_applied = True


_patch_main_window()
