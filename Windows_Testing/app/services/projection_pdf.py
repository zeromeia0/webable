"""Structured PDF reports for long-range projections (ReportLab + matplotlib, merged with pypdf)."""

from __future__ import annotations

import io
from datetime import datetime
from xml.sax.saxutils import escape


def _merge_pdf_bytes(parts: list[bytes]) -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for raw in parts:
        reader = PdfReader(io.BytesIO(raw))
        for page in reader.pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _money(v: float) -> str:
    return f"EUR {float(v):,.2f}"


def _build_reportlab_story(
    *,
    workspace_name: str,
    job_id: int,
    job_started: datetime | None,
    projection_rows: list[dict],
    output_details: dict,
    sim: dict,
    display_currency: str = "EUR",
    fx_rates: dict[str, float] | None = None,
    fx_updated_at: str | None = None,
) -> list:
    from app.services import currency_service
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        name="DocTitle",
        parent=styles["Heading1"],
        fontSize=20,
        spaceAfter=14,
        textColor=colors.HexColor("#1e293b"),
        alignment=TA_LEFT,
    )
    h2 = ParagraphStyle(
        name="H2",
        parent=styles["Heading2"],
        fontSize=13,
        spaceBefore=16,
        spaceAfter=8,
        textColor=colors.HexColor("#0f172a"),
    )
    body = ParagraphStyle(
        name="Body",
        parent=styles["Normal"],
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#334155"),
    )
    small = ParagraphStyle(
        name="Small",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#64748b"),
    )

    cur = currency_service.normalize_currency(display_currency)
    rmap = dict(fx_rates or {})

    def m(vf: float) -> str:
        return currency_service.format_money(float(vf), cur, rmap)

    story: list = []
    story.append(Paragraph("Financial projection report", title))
    job_when = job_started.strftime("%Y-%m-%d %H:%M UTC") if job_started else "—"
    story.append(
        Paragraph(
            f"<b>Workspace:</b> {escape(workspace_name)}<br/>"
            f"<b>Projection completed:</b> {escape(job_when)}<br/>"
            f"<b>Report generated:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            body,
        )
    )
    story.append(Paragraph(escape(currency_service.format_meta_line(cur, fx_updated_at)), small))
    story.append(Spacer(1, 0.12 * inch))

    story.append(Paragraph("Executive summary", h2))
    cards = output_details.get("cards") or []
    card_data = [["Metric", "Value"]]
    for c in cards:
        card_data.append([str(c.get("label", "")), str(c.get("value", ""))])
    t_cards = Table(card_data, colWidths=[2.6 * inch, 3.4 * inch])
    t_cards.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(t_cards)
    story.append(Spacer(1, 0.15 * inch))

    meta = sim.get("meta") or {}
    summ = sim.get("summary") or {}
    story.append(Paragraph("Investment simulation (inputs)", h2))
    story.append(
        Paragraph(
            f"<b>Percent of monthly projected savings invested:</b> {meta.get('invest_pct', 0):g}%<br/>"
            f"<b>Annual return (stated %, effective annual):</b> {meta.get('annual_rate_pct', 0):g}%<br/>"
            f"<b>Horizon:</b> {meta.get('horizon_years', 0):g} years ({meta.get('horizon_months', 0)} months)<br/>"
            f"<b>Monthly rate:</b> (1 + APR)^(1/12) - 1 = {meta.get('effective_monthly_rate', 0):.6f}<br/>"
            f"<b>Extended savings base (after projection ends):</b> {escape(m(float(meta.get('extended_monthly_savings_base', 0) or 0)))} "
            f"(last projected month’s savings, or the latest earlier month with positive savings)<br/>"
            "<b>Contribution rule:</b> each month, contribution = invest% × monthly savings base "
            "(that month within the projection, else the extended base). "
            "<b>Timing:</b> beginning of month — add contribution, then multiply balance by (1 + monthly rate).",
            body,
        )
    )
    story.append(Spacer(1, 0.1 * inch))

    story.append(Paragraph("Investment results (final period)", h2))
    inv_data = [
        ["Measure", "Amount"],
        ["Final investment balance (compounded)", m(float(summ.get("final_investment_balance", 0)))],
        ["Total amount invested (contributions)", m(float(summ.get("final_cumulative_contributed", 0)))],
        ["Compounded growth / profit", m(float(summ.get("final_compounded_profit", 0)))],
        ["Final projected accumulated wealth (end of projection)", m(float(summ.get("final_accumulated_wealth", 0)))],
    ]
    t_inv = Table(inv_data, colWidths=[3.2 * inch, 2.8 * inch])
    t_inv.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14532d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#ecfdf5"), colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#86efac")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(t_inv)
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Monthly projection detail", h2))
    proj_head = ["Month", "Est. monthly savings", "Accumulated wealth"]
    proj_data = [proj_head]
    for r in projection_rows:
        proj_data.append(
            [
                str(r.get("month", "")),
                m(float(r.get("estimated_savings", 0))),
                m(float(r.get("accumulated", 0))),
            ]
        )
    t_proj = Table(proj_data, repeatRows=1, colWidths=[1.1 * inch, 1.6 * inch, 1.6 * inch])
    t_proj.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#312e81")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f1f5f9"), colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_proj)
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Monthly investment simulation", h2))
    sim_rows = sim.get("rows") or []
    inv_head = ["Month", "Contribution", "Cumulative invested", "Balance", "Compounded profit"]
    inv_table = [inv_head]
    for row in sim_rows:
        inv_table.append(
            [
                str(row.get("month", "")),
                m(float(row.get("contribution", 0))),
                m(float(row.get("cumulative_contributed", 0))),
                m(float(row.get("investment_balance", 0))),
                m(float(row.get("compounded_profit", 0))),
            ]
        )
    t_sim = Table(inv_table, repeatRows=1, colWidths=[0.95 * inch, 1.15 * inch, 1.2 * inch, 1.15 * inch, 1.15 * inch])
    t_sim.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#92400e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#fffbeb"), colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#fcd34d")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(t_sim)
    story.append(Spacer(1, 0.15 * inch))

    rec = output_details.get("recommendation") or ""
    story.append(Paragraph("Recommendation", h2))
    story.append(Paragraph(escape(rec), body))

    sections = output_details.get("sections") or []
    if sections:
        story.append(Paragraph("Additional highlights", h2))
        for sec in sections:
            title_txt = str(sec.get("title", ""))
            items = sec.get("items") or []
            story.append(Paragraph(f"<b>{title_txt}</b>", body))
            for it in items:
                story.append(Paragraph(f"• {escape(str(it))}", small))
            story.append(Spacer(1, 0.08 * inch))

    return story


def _matplotlib_chart_pages(
    sim: dict,
    projection_rows: list[dict],
    display_currency: str = "EUR",
    fx_rates: dict[str, float] | None = None,
) -> bytes:
    """Vector PDF page(s) with matplotlib — not raster screenshots."""
    from app.services import currency_service

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cur = currency_service.normalize_currency(display_currency)
    rmap = dict(fx_rates or {})

    def cv(v: float) -> float:
        return currency_service.convert_from_eur(float(v), cur, rmap)

    y_label = cur if cur != "EUR" else "EUR"
    rows = sim.get("rows") or []
    if not rows:
        buf = io.BytesIO()
        fig, ax = plt.subplots(figsize=(8, 2))
        ax.text(0.5, 0.5, "No simulation data", ha="center", va="center")
        ax.axis("off")
        fig.savefig(buf, format="pdf", bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()

    x_idx = list(range(len(rows)))
    labels = [r["month"] for r in rows]
    step = max(1, len(labels) // 18)
    tick_pos = x_idx[::step]
    tick_lbl = [labels[i] for i in tick_pos]

    wealth = [
        cv(float(r["accumulated_wealth"])) if r.get("accumulated_wealth") is not None else float("nan")
        for r in rows
    ]
    balance = [cv(float(r["investment_balance"])) for r in rows]
    cum = [cv(float(r["cumulative_contributed"])) for r in rows]
    profit = [cv(float(r["compounded_profit"])) for r in rows]

    # --- Page 1: main wealth & investment curves (landscape A4) ---
    fig1, ax1 = plt.subplots(figsize=(11.69, 8.27))
    ax1.plot(x_idx, wealth, color="#2563eb", linewidth=2.2, label="Total projected wealth (accumulated savings)", alpha=0.95)
    ax1.plot(x_idx, balance, color="#d97706", linewidth=2.2, label="Investment balance (compounded)", alpha=0.95)
    ax1.plot(x_idx, cum, color="#7c3aed", linewidth=1.6, linestyle="--", label="Cumulative amount invested", alpha=0.9)
    ax1.plot(x_idx, profit, color="#059669", linewidth=1.8, label="Compounded profit (balance − invested)", alpha=0.9)
    ax1.set_xticks(tick_pos)
    ax1.set_xticklabels(tick_lbl, rotation=35, ha="right", fontsize=8)
    ax1.set_ylabel(y_label, fontsize=10)
    ax1.set_title("Projection & investment simulation", fontsize=13, pad=12)
    ax1.grid(True, alpha=0.35, linestyle=":")
    ax1.legend(loc="upper left", fontsize=8, framealpha=0.92)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    buf1 = io.BytesIO()
    fig1.savefig(buf1, format="pdf", bbox_inches="tight")
    plt.close(fig1)

    # --- Page 2: monthly savings bars from projection (portrait) ---
    n = len(projection_rows)
    months_p = [str(r.get("month", "")) for r in projection_rows]
    savings_p = [cv(float(r.get("estimated_savings", 0))) for r in projection_rows]
    fig2, ax2 = plt.subplots(figsize=(8.27, 11.69))
    colors_b = ["#34d399" if s >= 0 else "#f87171" for s in savings_p]
    ax2.bar(range(n), savings_p, color=colors_b, edgecolor="#1e293b", linewidth=0.3)
    step2 = max(1, n // 20)
    ax2.set_xticks(range(0, n, step2))
    ax2.set_xticklabels([months_p[i] for i in range(0, n, step2)], rotation=55, ha="right", fontsize=7)
    ax2.axhline(0, color="#334155", linewidth=0.8)
    ax2.set_ylabel(y_label, fontsize=10)
    ax2.set_title("Projected monthly savings by month", fontsize=12, pad=10)
    ax2.grid(True, axis="y", alpha=0.35, linestyle=":")
    buf2 = io.BytesIO()
    fig2.savefig(buf2, format="pdf", bbox_inches="tight")
    plt.close(fig2)

    return _merge_pdf_bytes([buf1.getvalue(), buf2.getvalue()])


def build_projection_report_pdf(
    *,
    workspace_name: str,
    job_id: int,
    job_started: datetime | None,
    projection_rows: list[dict],
    output_details: dict,
    sim: dict,
    display_currency: str = "EUR",
    fx_rates: dict[str, float] | None = None,
    fx_updated_at: str | None = None,
) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    buf_rl = io.BytesIO()
    doc = SimpleDocTemplate(
        buf_rl,
        pagesize=A4,
        rightMargin=48,
        leftMargin=48,
        topMargin=52,
        bottomMargin=48,
        title="Webable projection report",
        author="Webable",
    )
    story = _build_reportlab_story(
        workspace_name=workspace_name,
        job_id=job_id,
        job_started=job_started,
        projection_rows=projection_rows,
        output_details=output_details,
        sim=sim,
        display_currency=display_currency,
        fx_rates=fx_rates,
        fx_updated_at=fx_updated_at,
    )
    doc.build(story)
    chart_pdf = _matplotlib_chart_pages(
        sim,
        projection_rows,
        display_currency=display_currency,
        fx_rates=fx_rates,
    )
    return _merge_pdf_bytes([buf_rl.getvalue(), chart_pdf])


def build_results_summary_pdf(
    *,
    workspace_name: str,
    result_title: str,
    result_subtitle: str,
    output_details: dict,
    display_currency: str = "EUR",
    fx_rates: dict[str, float] | None = None,
    fx_updated_at: str | None = None,
) -> bytes:
    """Lightweight Results-only PDF (no investment charts or simulation tables)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from app.services import currency_service
    from app.services.pdf_common import pdf_styles, table_style_header

    title, h2, body, small = pdf_styles()
    cur = currency_service.normalize_currency(display_currency)
    rmap = dict(fx_rates or {})

    def m(vf: float) -> str:
        return currency_service.format_money(float(vf), cur, rmap)

    story: list = []
    story.append(Paragraph("Database calculation — results summary", title))
    story.append(
        Paragraph(
            f"<b>Workspace:</b> {escape(workspace_name)}<br/>"
            f"<b>Result:</b> {escape(result_title)}<br/>"
            f"<b>Detail:</b> {escape(result_subtitle)}<br/>"
            f"<b>Generated:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            body,
        )
    )
    story.append(Paragraph(escape(currency_service.format_meta_line(cur, fx_updated_at)), small))
    story.append(Spacer(1, 0.14 * inch))

    cards = output_details.get("cards") or []
    if cards:
        story.append(Paragraph("Key metrics", h2))
        card_data = [["Metric", "Value"]]
        for c in cards:
            card_data.append([str(c.get("label", "")), str(c.get("value", ""))])
        t_cards = Table(card_data, colWidths=[2.6 * inch, 3.4 * inch])
        t_cards.setStyle(TableStyle(table_style_header()))
        story.append(t_cards)
        story.append(Spacer(1, 0.12 * inch))

    sections = output_details.get("sections") or []
    for sec in sections:
        sec_title = str(sec.get("title", "Details"))
        items = sec.get("items") or []
        if not items:
            continue
        story.append(Paragraph(escape(sec_title), h2))
        for it in items:
            story.append(Paragraph(f"• {escape(str(it))}", body))
        story.append(Spacer(1, 0.08 * inch))

    bars = output_details.get("bars") or []
    if bars:
        story.append(Paragraph("Projection trend (monthly savings)", h2))
        bar_rows = [["Month", "Estimated savings"]]
        for b in bars:
            label = str(b.get("label", ""))
            if b.get("value_eur") is not None:
                val = m(float(b["value_eur"]))
            else:
                val = str(b.get("value", ""))
            bar_rows.append([label, val])
        t_bars = Table(bar_rows, repeatRows=1, colWidths=[1.8 * inch, 2.2 * inch])
        t_bars.setStyle(TableStyle(table_style_header("#312e81")))
        story.append(t_bars)
        story.append(Spacer(1, 0.1 * inch))

    rec = output_details.get("recommendation") or ""
    if rec:
        story.append(Paragraph("Summary insight", h2))
        story.append(Paragraph(escape(rec), body))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=52,
        leftMargin=52,
        topMargin=52,
        bottomMargin=48,
        title="Webable results summary",
        author="Webable",
    )
    doc.build(story)
    return buf.getvalue()
