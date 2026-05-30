"""PDF export for standalone investment calculator + optional projection-linked scenario."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from app.services.projection_pdf import _merge_pdf_bytes


def build_investment_calculator_pdf(
    *,
    workspace_name: str,
    calculator_inputs: dict[str, Any],
    calculator_result: dict[str, Any],
    projection_result: dict[str, Any] | None,
    projection_label: str | None,
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
    title = ParagraphStyle("t", parent=styles["Heading1"], fontSize=18, textColor=colors.HexColor("#0f172a"), alignment=TA_LEFT)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#0f172a"))
    body = ParagraphStyle("b", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#334155"))

    cur = currency_service.normalize_currency(display_currency)
    rmap = dict(fx_rates or {})

    def m(vf: float) -> str:
        return currency_service.format_money(float(vf), cur, rmap)

    story: list = []
    story.append(Paragraph("Investment calculator report", title))
    story.append(
        Paragraph(
            f"<b>Workspace:</b> {escape(workspace_name)}<br/>"
            f"<b>Generated:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            body,
        )
    )
    story.append(Paragraph(escape(currency_service.format_meta_line(cur, fx_updated_at)), body))
    story.append(Spacer(1, 0.12 * inch))

    story.append(Paragraph("Calculator inputs", h2))
    ci = calculator_inputs
    inp = [
        ["Field", "Value"],
        ["Initial balance", m(float(ci.get("initial_balance", 0)))],
        ["Monthly contribution", m(float(ci.get("monthly_contribution", 0)))],
        ["Annual return (%)", f"{float(ci.get('annual_rate_pct', 0)):g}%"],
        ["Duration (years)", f"{float(ci.get('years', 0)):g}"],
        ["Compounding periods / year", str(ci.get("compounding_per_year", 12))],
        ["Contribution timing", str(ci.get("contribution_timing", "beginning"))],
    ]
    t1 = Table(inp, colWidths=[2.5 * inch, 3.5 * inch])
    tbl_style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]
    )
    t1.setStyle(tbl_style)
    story.append(t1)
    story.append(Spacer(1, 0.1 * inch))

    summ = calculator_result.get("summary") or {}
    meta = calculator_result.get("meta") or {}
    story.append(Paragraph("Calculator results", h2))
    res_tbl = [
        ["Metric", "Value"],
        ["Final balance", m(float(summ.get("final_balance", 0)))],
        ["Total contributions", m(float(summ.get("total_contributions", 0)))],
        ["Interest / profit", m(float(summ.get("total_interest_profit", 0)))],
        ["Effective monthly rate", f"{float(meta.get('effective_monthly_rate', 0)):.6f}"],
    ]
    t2 = Table(res_tbl, colWidths=[2.5 * inch, 3.5 * inch])
    t2.setStyle(tbl_style)
    story.append(t2)

    if projection_result and projection_label:
        story.append(Spacer(1, 0.12 * inch))
        story.append(Paragraph("Projection-linked scenario", h2))
        story.append(Paragraph(escape(projection_label), body))
        ps = projection_result.get("summary") or {}
        pm = projection_result.get("meta") or {}
        t3 = Table(
            [
                ["Metric", "Value"],
                ["Invest % of projected savings", f"{float(pm.get('invest_pct', 0)):g}%"],
                ["Horizon (years)", f"{float(pm.get('horizon_years', 0)):g}"],
                ["Final investment balance", m(float(ps.get("final_investment_balance", 0)))],
                ["Total contributed", m(float(ps.get("final_cumulative_contributed", 0)))],
                ["Compounded profit", m(float(ps.get("final_compounded_profit", 0)))],
            ],
            colWidths=[2.5 * inch, 3.5 * inch],
        )
        t3.setStyle(tbl_style)
        story.append(t3)

    buf_rl = io.BytesIO()
    doc = SimpleDocTemplate(buf_rl, pagesize=A4, rightMargin=48, leftMargin=48, topMargin=48, bottomMargin=48)
    doc.build(story)

    charts = _investment_matplotlib_pages(
        calculator_result,
        projection_result,
        display_currency=display_currency,
        fx_rates=fx_rates,
    )
    return _merge_pdf_bytes([buf_rl.getvalue(), charts])


def _investment_matplotlib_pages(
    calc: dict,
    proj: dict | None,
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

    parts: list[bytes] = []
    series = calc.get("series") or {}
    labels = series.get("labels") or []
    bal = [cv(float(x)) for x in (series.get("balance") or [])]
    cum = [cv(float(x)) for x in (series.get("cumulative_contributed") or [])]
    intr = [cv(float(x)) for x in (series.get("interest_earned") or [])]

    fig, ax = plt.subplots(figsize=(11.69, 5.5))
    x = list(range(len(bal)))
    ax.plot(x, bal, label="Balance", color="#a78bfa", linewidth=2)
    ax.plot(x, cum, label="Total contributed", color="#94a3b8", linestyle="--", linewidth=1.5)
    ax.plot(x, intr, label="Interest earned", color="#34d399", linewidth=1.5)
    ax.set_title("Investment growth (calculator)", fontsize=12)
    ax.set_ylabel(y_label)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.3)
    step = max(1, len(labels) // 20)
    ax.set_xticks(x[::step])
    ax.set_xticklabels([labels[i] for i in x[::step]], rotation=35, ha="right", fontsize=7)
    b1 = io.BytesIO()
    fig.tight_layout()
    fig.savefig(b1, format="pdf", bbox_inches="tight")
    plt.close(fig)
    parts.append(b1.getvalue())

    if proj and (proj.get("rows") or []):
        rows = proj["rows"]
        months = [r["month"] for r in rows]
        wealth = [
            cv(float(r["accumulated_wealth"])) if r.get("accumulated_wealth") is not None else float("nan") for r in rows
        ]
        invb = [cv(float(r["investment_balance"])) for r in rows]
        fig2, ax2 = plt.subplots(figsize=(11.69, 5.5))
        xi = range(len(months))
        ax2.plot(xi, wealth, color="#60a5fa", label="Projected wealth", linewidth=2)
        ax2.plot(xi, invb, color="#fbbf24", label="Investment balance", linewidth=2)
        ax2.set_title("Projection-linked investment", fontsize=12)
        ax2.set_ylabel(y_label)
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=0.3)
        st = max(1, len(months) // 18)
        ax2.set_xticks(xi[::st])
        ax2.set_xticklabels([months[i] for i in xi[::st]], rotation=35, ha="right", fontsize=7)
        b2 = io.BytesIO()
        fig2.tight_layout()
        fig2.savefig(b2, format="pdf", bbox_inches="tight")
        plt.close(fig2)
        parts.append(b2.getvalue())

    return _merge_pdf_bytes(parts)
