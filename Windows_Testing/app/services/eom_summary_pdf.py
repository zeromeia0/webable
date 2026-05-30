"""PDF export for end-of-month summaries."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape


def build_eom_summary_pdf(
    *,
    workspace_name: str,
    summary: dict,
    is_preview: bool = False,
    display_currency: str = "EUR",
    fx_rates: dict | None = None,
    fx_updated_at: str | None = None,
) -> bytes:
    from app.services import currency_service
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from app.services.pdf_common import pdf_styles, table_style_header

    title_style, h2_style, body_style, small_style = pdf_styles()
    cur = currency_service.normalize_currency(display_currency)
    rmap = dict(fx_rates or {})

    def m(vf: float) -> str:
        return currency_service.format_money(float(vf), cur, rmap)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=48, rightMargin=48, topMargin=48, bottomMargin=48)
    story: list = []

    label = "Preview — current month not finished" if is_preview else "Monthly summary"
    story.append(Paragraph(escape(f"EOM Summary — {summary.get('month_label', '')}"), title_style))
    story.append(
        Paragraph(
            f"<b>Workspace:</b> {escape(workspace_name)}<br/>"
            f"<b>Status:</b> {escape(label)}<br/>"
            f"<b>Generated:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            body_style,
        )
    )
    story.append(Paragraph(escape(currency_service.format_meta_line(cur, fx_updated_at)), small_style))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Overview", h2_style))
    overview = [
        ["Income", m(float(summary.get("total_income") or 0))],
        ["Expenses", m(float(summary.get("total_expenses") or 0))],
        ["Net balance", m(float(summary.get("net_balance") or 0))],
    ]
    if summary.get("safe_to_spend") is not None:
        overview.append(["Safe to spend (25%)", m(float(summary.get("safe_to_spend") or 0))])
    if summary.get("average_monthly_balance") is not None:
        overview.append(["Avg monthly balance (6 mo)", m(float(summary.get("average_monthly_balance") or 0))])
    if summary.get("fixed_expenses_percent_income"):
        overview.append(
            [
                "Fixed expenses",
                f"{m(float(summary.get('fixed_expenses_total') or 0))} ({summary.get('fixed_expenses_percent_income')}% of income)",
            ]
        )
    t = Table(overview, colWidths=[2.4 * inch, 3.6 * inch])
    t.setStyle(TableStyle(table_style_header("#1e3a5f")))
    story.append(t)
    story.append(Spacer(1, 0.15 * inch))

    comp = summary.get("comparison") or {}
    if comp:
        story.append(Paragraph("Compared with last month", h2_style))
        comp_lines = []
        if comp.get("income_change") is not None:
            comp_lines.append(f"Income change: {m(float(comp['income_change']))}")
        if comp.get("expenses_change") is not None:
            comp_lines.append(f"Expenses change: {m(float(comp['expenses_change']))}")
        if comp.get("savings_change") is not None:
            comp_lines.append(f"Savings change: {m(float(comp['savings_change']))}")
        if comp.get("plain_summary"):
            comp_lines.append(str(comp["plain_summary"]))
        story.append(Paragraph("<br/>".join(escape(x) for x in comp_lines), body_style))
        story.append(Spacer(1, 0.12 * inch))

    story.append(Paragraph("Summary", h2_style))
    for line in summary.get("summary_lines") or []:
        story.append(Paragraph(f"• {escape(str(line))}", body_style))

    top_exp = summary.get("top_expenses") or []
    if top_exp:
        story.append(Spacer(1, 0.12 * inch))
        story.append(Paragraph("Top expenses", h2_style))
        rows = [["Name", "Amount", "% of expenses", "% of income"]]
        for row in top_exp[:10]:
            rows.append(
                [
                    escape(str(row.get("name", ""))[:40]),
                    m(float(row.get("amount_eur") or 0)),
                    row.get("pct_expenses_label") or "—",
                    row.get("pct_income_label") or "—",
                ]
            )
        te = Table(rows, colWidths=[1.8 * inch, 1.1 * inch, 1.3 * inch, 1.3 * inch])
        te.setStyle(TableStyle(table_style_header("#7f1d1d")))
        story.append(te)

    doc.build(story)
    return buf.getvalue()
