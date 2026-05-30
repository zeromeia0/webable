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
    doc = SimpleDocTemplate(
        buf_rl,
        pagesize=A4,
        rightMargin=52,
        leftMargin=52,
        topMargin=52,
        bottomMargin=48,
        title="Webable spending report",
        author="Webable",
    )
    doc.build(story)
    try:
        chart_pdf = _reports_matplotlib_charts(report, display_currency=display_currency, fx_rates=fx_rates)
    except Exception as exc:
        import logging

        logging.getLogger("webable.reports_pdf").exception("Chart PDF generation failed: %s", exc)
        chart_pdf = _empty_chart_pdf_page("Charts could not be generated. Check server logs and matplotlib install.")
    if not chart_pdf or not chart_pdf.startswith(b"%PDF"):
        chart_pdf = _empty_chart_pdf_page("No chart data for this time range.")
    return _merge_pdf_bytes([buf_rl.getvalue(), chart_pdf])


def _empty_chart_pdf_page(message: str) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    buf = io.BytesIO()
    fig, ax = plt.subplots(figsize=(8.27, 3))
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=11, color="#475569", wrap=True)
    ax.axis("off")
    fig.savefig(buf, format="pdf", bbox_inches="tight", pad_inches=0.4)
    plt.close(fig)
    return buf.getvalue()


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
    cats = report.get("top_categories") or []
    chart_parts: list[bytes] = []

    if not monthly and not cats:
        buf = io.BytesIO()
        fig, ax = plt.subplots(figsize=(8.27, 3))
        ax.text(0.5, 0.5, "No data in selected range", ha="center", va="center", fontsize=11, color="#475569")
        ax.axis("off")
        fig.savefig(buf, format="pdf", bbox_inches="tight", pad_inches=0.4)
        plt.close(fig)
        return buf.getvalue()

    if monthly:
        labels = [m["month"] for m in monthly]
        x_idx = list(range(len(labels)))
        spend = [cv(float(m.get("oneoff_expenses", 0))) for m in monthly]
        tot_exp = [cv(float(m.get("total_expenses", 0))) for m in monthly]
        tot_inc = [cv(float(m.get("total_income", 0))) for m in monthly]
        step = max(1, len(labels) // 14)
        tick_pos = x_idx[::step]
        tick_lbl = [labels[i] for i in range(0, len(labels), step)]

        fig1, axes = plt.subplots(3, 1, figsize=(11.69, 11.69), constrained_layout=True)
        ax1, ax_line, ax2 = axes
        ax1.bar(x_idx, spend, color="#f87171", edgecolor="#7f1d1d", linewidth=0.2)
        ax1.set_title("One-off spending over time (monthly bars)", fontsize=12, pad=10)
        ax1.set_ylabel(y_label, fontsize=10)
        ax1.set_xticks(tick_pos)
        ax1.set_xticklabels(tick_lbl, rotation=35, ha="right", fontsize=7)
        ax1.grid(True, axis="y", alpha=0.35, linestyle=":")
        ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))

        ax_line.plot(
            x_idx,
            spend,
            color="#dc2626",
            linewidth=2.4,
            marker="o",
            markersize=5,
            markevery=1 if len(x_idx) <= 24 else max(1, len(x_idx) // 24),
        )
        ax_line.set_title("One-off spending over time (line)", fontsize=12, pad=10)
        ax_line.set_ylabel(y_label, fontsize=10)
        ax_line.set_xticks(tick_pos)
        ax_line.set_xticklabels(tick_lbl, rotation=35, ha="right", fontsize=7)
        ax_line.grid(True, alpha=0.35, linestyle=":")
        ax_line.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))

        ax2.plot(
            x_idx,
            tot_inc,
            color="#059669",
            label="Total income",
            linewidth=2.2,
            marker="o",
            markersize=4,
            markevery=max(1, len(x_idx) // 12),
        )
        ax2.plot(
            x_idx,
            tot_exp,
            color="#dc2626",
            label="Total expenses",
            linewidth=2.2,
            marker="o",
            markersize=4,
            markevery=max(1, len(x_idx) // 12),
        )
        ax2.set_title("Income vs expenses (incl. recurring)", fontsize=12, pad=10)
        ax2.legend(loc="upper left", fontsize=8, framealpha=0.92)
        ax2.set_ylabel(y_label, fontsize=10)
        ax2.set_xticks(tick_pos)
        ax2.set_xticklabels(tick_lbl, rotation=35, ha="right", fontsize=7)
        ax2.grid(True, alpha=0.35, linestyle=":")
        ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))

        buf1 = io.BytesIO()
        fig1.savefig(buf1, format="pdf", bbox_inches="tight", pad_inches=0.35)
        plt.close(fig1)
        chart_parts.append(buf1.getvalue())

    if cats:
        fig2, ax3 = plt.subplots(figsize=(8.27, max(4.5, min(10, 0.45 * len(cats) + 2))))
        names = [c["key"] for c in cats]
        vals = [cv(float(c["total"])) for c in cats]
        ax3.barh(names[::-1], vals[::-1], color="#6366f1", edgecolor="#312e81", linewidth=0.2)
        ax3.set_xlabel(y_label, fontsize=10)
        ax3.set_title("Top spending categories", fontsize=12, pad=10)
        ax3.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax3.grid(True, axis="x", alpha=0.3, linestyle=":")
        buf2 = io.BytesIO()
        fig2.tight_layout()
        fig2.savefig(buf2, format="pdf", bbox_inches="tight", pad_inches=0.35)
        plt.close(fig2)
        chart_parts.append(buf2.getvalue())

    if len(chart_parts) == 1:
        return chart_parts[0]
    return _merge_pdf_bytes(chart_parts)
