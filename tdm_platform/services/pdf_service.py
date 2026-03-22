from pathlib import Path

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdf_canvas
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False

def render_simple_report_pdf(path: str | Path, title: str, report_text: str) -> None:
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab nincs telepítve.")
    path = str(path)
    c = pdf_canvas.Canvas(path, pagesize=A4)
    page_w, page_h = A4
    margin = 15 * mm
    y = page_h - margin
    c.setTitle(title)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, title[:120])
    y -= 10 * mm
    c.setFont("Helvetica", 10)
    for line in report_text.splitlines():
        if y < margin:
            c.showPage()
            y = page_h - margin
            c.setFont("Helvetica", 10)
        c.drawString(margin, y, (line or " ")[:140])
        y -= 4.8 * mm
    c.save()
