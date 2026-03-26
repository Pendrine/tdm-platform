from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtWidgets import QComboBox, QTableWidget, QTableWidgetItem, QTextBrowser

from tdm_platform.core.history import HistoryStore


class HistoryTabController:
    """UI-only history tab helpers extracted from the monolith."""

    def __init__(self, store: HistoryStore | None = None) -> None:
        self.store = store or HistoryStore()

    def load_rows(self) -> list[dict]:
        return self.store.load()

    def save_rows(self, rows: list[dict]) -> None:
        self.store.save(rows)

    def refresh_filter(self, combo: QComboBox, history_rows: list[dict], current_user: Mapping[str, object] | None = None) -> None:
        current = combo.currentText() if combo.count() else "Összes"
        users = sorted({str(r.get("user", "")).strip() for r in history_rows if str(r.get("user", "")).strip()})
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Összes")
        if current_user:
            combo.addItem("Saját")
        combo.addItems(users)
        idx = combo.findText(current)
        combo.setCurrentIndex(max(0, idx))
        combo.blockSignals(False)

    def populate_table(
        self,
        table: QTableWidget,
        detail: QTextBrowser,
        history_rows: list[dict],
        selected_user: str = "Összes",
        current_user: Mapping[str, object] | None = None,
    ) -> list[dict]:
        rows = history_rows
        if selected_user == "Saját" and current_user:
            rows = [r for r in rows if str(r.get("user", "")).strip() == str(current_user.get("email", ""))]
        elif selected_user and selected_user != "Összes":
            rows = [r for r in rows if str(r.get("user", "")).strip() == selected_user]
        rows = sorted(rows, key=lambda x: str(x.get("timestamp", "")), reverse=True)
        table.setRowCount(len(rows))
        table.setProperty("history_rows", rows)
        for i, row in enumerate(rows):
            values = [
                row.get("timestamp", ""),
                row.get("user", ""),
                row.get("patient_id", ""),
                row.get("drug", ""),
                row.get("method", ""),
                row.get("status", ""),
                row.get("regimen", ""),
                row.get("decision", ""),
            ]
            for j, value in enumerate(values):
                table.setItem(i, j, QTableWidgetItem(str(value)))
        if rows:
            table.selectRow(0)
        else:
            detail.setHtml("<p>Még nincs naplózott számítás.</p>")
        return rows

    def render_detail(self, detail: QTextBrowser, record: Mapping[str, object]) -> None:
        report_html = "<br>".join(str(record.get("report", "")).splitlines())
        input_html = "<br>".join(
            f"<b>{key}</b>: {value}" for key, value in (record.get("inputs") or {}).items()
        )
        detail.setHtml(
            f"<h3>{record.get('drug','')} – {record.get('method','')}</h3>"
            f"<p><b>Időpont:</b> {record.get('timestamp','')}<br>"
            f"<b>Felhasználó:</b> {record.get('user','—')}<br>"
            f"<b>Beteg:</b> {record.get('patient_id','—')}<br>"
            f"<b>Döntés:</b> {record.get('decision','—')}</p>"
            f"<h4>Riport</h4><p>{report_html}</p>"
            f"<h4>Rögzített input</h4><p>{input_html}</p>"
        )
