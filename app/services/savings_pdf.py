"""PDF export for emergency fund / savings calculator."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

from xml.sax.saxutils import escape


def build_savings_calculator_pdf(
    *,
    workspace_name: str,
    inputs: dict,
    result: dict,
    display_currency: str = "EUR",
    fx_rates: dict | None = None,
    fx_updated_at: str | None = None,
) -> bytes:
    from app.services import currency_service
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        name="ST",
        parent=styles["Heading1"],
        fontSize=18,
        spaceAfter=10,
        textColor=colors.HexColor("#0f172a"),
        alignment=TA_LEFT,
    )
    h2 = ParagraphStyle(name="H2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#0f172a"))
    body = ParagraphStyle(name="B", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#334155"))

    cur = currency_service.normalize_currency(display_currency)
    rmap = dict(fx_rates or {})

    def m(vf: float) -> str:
        return currency_service.format_money(float(vf), cur, rmap)

    story: list = []
    story.append(Paragraph("Emergency fund calculator", title))
    story.append(
        Paragraph(
            f"<b>Workspace:</b> {escape(workspace_name)}<br/>"
            f"<b>Generated:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}<br/>"
            f"Values are based on <b>essential monthly expenses</b> (not salary).",
            body,
        )
    )
    story.append(Paragraph(escape(currency_service.format_meta_line(cur, fx_updated_at)), body))
    story.append(Spacer(1, 0.15 * inch))

    bd = result.get("breakdown") or {}
    story.append(Paragraph("Monthly inputs (EUR base)", h2))
    rows = [["Category", "Amount"]]
    labels = [
        ("Housing", bd.get("housing")),
        ("Food / groceries", bd.get("food")),
        ("Transport", bd.get("transport")),
        ("Utilities / bills", bd.get("utilities")),
        ("Subscriptions", bd.get("subscriptions")),
        ("Insurance / health", bd.get("insurance")),
        ("Debt payments", bd.get("debt")),
        ("Other essentials", bd.get("other")),
    ]
    for lab, val in labels:
        rows.append([lab, m(float(val or 0))])
    rows.append(["Buffer %", f"{float(result.get('buffer_pct') or 0):.1f}%"])
    rows.append(["Monthly total (with buffer)", m(float(result.get("monthly_with_buffer") or 0))])
    tb = Table(rows, colWidths=[2.8 * inch, 3.2 * inch])
    tb.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14532d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f0fdf4"), colors.white]),
            ]
        )
    )
    story.append(tb)
    story.append(Spacer(1, 0.12 * inch))

    story.append(Paragraph("Targets & progress", h2))
    pr = result.get("progress") or {}
    trows = [["Horizon", "Target", "Progress", "Still needed"]]
    for mkey in ("3", "6", "9"):
        p = pr.get(mkey) or {}
        trows.append(
            [
                f"{mkey} months",
                m(float(p.get("target") or 0)),
                f"{float(p.get('progress_pct') or 0):.1f}%",
                m(float(p.get("still_needed") or 0)),
            ]
        )
    trows.append(["Current savings", m(float(result.get("current_savings") or 0)), "", ""])
    tb2 = Table(trows, colWidths=[1.1 * inch, 1.5 * inch, 1.2 * inch, 1.7 * inch])
    tb2.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ]
        )
    )
    story.append(tb2)
    story.append(Spacer(1, 0.1 * inch))
    story.append(
        Paragraph(
            "<i>Educational only — not financial advice. Targets are estimates; adjust inputs as your situation changes.</i>",
            body,
        )
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50)
    doc.build(story)
    return buf.getvalue()
