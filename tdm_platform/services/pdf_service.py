from __future__ import annotations

from pathlib import Path

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdf_canvas

    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False


MAX_LINE_LENGTH = 140


def _wrap_text(text: str, width: int = MAX_LINE_LENGTH) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines() or [""]:
        remaining = raw_line or " "
        while len(remaining) > width:
            split_at = remaining.rfind(" ", 0, width)
            if split_at <= 0:
                split_at = width
            lines.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip() or " "
        lines.append(remaining)
    return lines


def render_simple_report_pdf(path: str | Path, title: str, report_text: str) -> None:
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab nincs telepítve.")
    output_path = str(path)
    canvas = pdf_canvas.Canvas(output_path, pagesize=A4)
    page_width, page_height = A4
    margin = 15 * mm
    y = page_height - margin
    canvas.setTitle(title)
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(margin, y, title[:120])
    y -= 10 * mm
    canvas.setFont("Helvetica", 10)
    for line in _wrap_text(report_text):
        if y < margin:
            canvas.showPage()
            y = page_height - margin
            canvas.setFont("Helvetica", 10)
        canvas.drawString(margin, y, line)
        y -= 4.8 * mm
    canvas.save()
