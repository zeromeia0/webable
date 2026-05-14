"""Structured PDF for spending reports (ReportLab + matplotlib vector charts)."""

from __future__ import annotations

import io
from datetime import datetime
from xml.sax.saxutils import escape

from app.services.projection_pdf import _merge_pdf_bytes


def build_reports_pdf(
    *,
    workspace_name: str,
    range_label: str,
    report: dict,
    display_currency: str = "EUR",
    fx_rates: dict[str, float] | None = None,
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
        name="RT",
        parent=styles["Heading1"],
        fontSize=18,
        spaceAfter=10,
        textColor=colors.HexColor("#0f172a"),
        alignment=TA_LEFT,
    )
    h2 = ParagraphStyle(name="H2", parent=styles["Heading2"], fontSize=12, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#0f172a"))
    body = ParagraphStyle(name="B", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#334155"))

    cur = currency_service.normalize_currency(display_currency)
    rmap = dict(fx_rates or {})

    def m(vf: float) -> str:
        return currency_service.format_money(float(vf), cur, rmap)

    story: list = []
    story.append(Paragraph("Spending report", title))
    story.append(
        Paragraph(
            f"<b>Workspace:</b> {escape(workspace_name)}<br/>"
            f"<b>Time range:</b> {escape(range_label)}<br/>"
            f"<b>Generated:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            body,
        )
    )
    story.append(Paragraph(escape(currency_service.format_meta_line(cur, fx_updated_at)), body))
    story.append(Spacer(1, 0.1 * inch))

    t = report.get("totals") or {}
    story.append(Paragraph("Summary", h2))
    summ = [
        ["Metric", "Value"],
        ["One-off expenses", m(float(t.get("oneoff_expenses", 0)))],
        ["One-off income", m(float(t.get("oneoff_income", 0)))],
        ["Recurring income (monthly)", m(float(t.get("recurring_income_monthly", 0)))],
        ["Recurring expenses (monthly)", m(float(t.get("recurring_expense_monthly", 0)))],
        ["Expense transactions", str(t.get("transaction_count_expenses", 0))],
        ["Income transactions", str(t.get("transaction_count_income", 0))],
    ]
    tb = Table(summ, colWidths=[2.8 * inch, 3.2 * inch])
    tb.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(tb)
    story.append(Spacer(1, 0.12 * inch))

    def top_table(title_txt: str, rows: list[dict]):
        story.append(Paragraph(escape(title_txt), h2))
        head = ["Item", "Total", "% of spend", "Count", "Average"]
        data = [head]
        for r in rows or []:
            data.append(
                [
                    escape(str(r.get("key", ""))),
                    m(float(r.get("total", 0))),
                    f"{float(r.get('pct_of_total', 0)):.1f}%",
                    str(r.get("count", 0)),
                    m(float(r.get("average", 0))),
                ]
            )
        tbl = Table(data, repeatRows=1, colWidths=[1.8 * inch, 1.1 * inch, 0.9 * inch, 0.55 * inch, 1.1 * inch])
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#312e81")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#cbd5e1")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(tbl)
        story.append(Spacer(1, 0.1 * inch))

    top_table("Top spending categories", report.get("top_categories"))
    top_table("Top descriptions / merchants", report.get("top_merchants"))

    buf_rl = io.BytesIO()
    doc = SimpleDocTemplate(buf_rl, pagesize=A4, rightMargin=48, leftMargin=48, topMargin=48, bottomMargin=48)
    doc.build(story)
    chart_pdf = _reports_matplotlib_charts(report, display_currency=display_currency, fx_rates=fx_rates)
    return _merge_pdf_bytes([buf_rl.getvalue(), chart_pdf])


def _reports_matplotlib_charts(
    report: dict,
    display_currency: str = "EUR",
    fx_rates: dict[str, float] | None = None,
) -> bytes:
    from app.services import currency_service

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cur = currency_service.normalize_currency(display_currency)
    rmap = dict(fx_rates or {})

    def cv(v: float) -> float:
        return currency_service.convert_from_eur(float(v), cur, rmap)

    y_label = cur if cur != "EUR" else "EUR"
    monthly = report.get("monthly") or []
    if not monthly:
        buf = io.BytesIO()
        fig, ax = plt.subplots(figsize=(8, 2))
        ax.text(0.5, 0.5, "No data in selected range", ha="center", va="center")
        ax.axis("off")
        fig.savefig(buf, format="pdf", bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()

    labels = [m["month"] for m in monthly]
    spend = [cv(float(m.get("oneoff_expenses", 0))) for m in monthly]
    tot_exp = [cv(float(m.get("total_expenses", 0))) for m in monthly]
    tot_inc = [cv(float(m.get("total_income", 0))) for m in monthly]

    fig1, (ax1, ax2) = plt.subplots(2, 1, figsize=(11.69, 8.27))
    ax1.bar(range(len(labels)), spend, color="#f87171", label="One-off expenses")
    ax1.set_title("One-off spending over time", fontsize=12)
    ax1.set_ylabel(y_label)
    step = max(1, len(labels) // 16)
    ax1.set_xticks(range(0, len(labels), step))
    ax1.set_xticklabels([labels[i] for i in range(0, len(labels), step)], rotation=40, ha="right", fontsize=7)
    ax1.grid(True, axis="y", alpha=0.3)

    ax2.plot(range(len(labels)), tot_inc, color="#34d399", label="Total income", linewidth=2)
    ax2.plot(range(len(labels)), tot_exp, color="#f87171", label="Total expenses", linewidth=2)
    ax2.set_title("Income vs expenses (incl. recurring)", fontsize=12)
    ax2.legend(loc="upper left", fontsize=8)
    ax2.set_ylabel(y_label)
    ax2.set_xticks(range(0, len(labels), step))
    ax2.set_xticklabels([labels[i] for i in range(0, len(labels), step)], rotation=40, ha="right", fontsize=7)
    ax2.grid(True, alpha=0.3)

    buf1 = io.BytesIO()
    fig1.tight_layout()
    fig1.savefig(buf1, format="pdf", bbox_inches="tight")
    plt.close(fig1)

    cats = report.get("top_categories") or []
    if cats:
        fig2, ax3 = plt.subplots(figsize=(8.27, 6))
        names = [c["key"] for c in cats]
        vals = [cv(float(c["total"])) for c in cats]
        ax3.barh(names[::-1], vals[::-1], color="#6366f1")
        ax3.set_xlabel(y_label)
        ax3.set_title("Top spending categories", fontsize=12)
        buf2 = io.BytesIO()
        fig2.tight_layout()
        fig2.savefig(buf2, format="pdf", bbox_inches="tight")
        plt.close(fig2)
        return _merge_pdf_bytes([buf1.getvalue(), buf2.getvalue()])
    return buf1.getvalue()
