"""Shared ReportLab styling helpers for Webable PDF exports."""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet


def pdf_styles():
    """Return common paragraph styles and a factory for data tables."""
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        name="WbTitle",
        parent=styles["Heading1"],
        fontSize=20,
        spaceAfter=12,
        textColor=colors.HexColor("#0f172a"),
        alignment=TA_LEFT,
    )
    h2 = ParagraphStyle(
        name="WbH2",
        parent=styles["Heading2"],
        fontSize=13,
        spaceBefore=14,
        spaceAfter=8,
        textColor=colors.HexColor("#0f172a"),
    )
    body = ParagraphStyle(
        name="WbBody",
        parent=styles["Normal"],
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#334155"),
    )
    small = ParagraphStyle(
        name="WbSmall",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#64748b"),
    )
    return title, h2, body, small


def table_style_header(hex_bg: str = "#1e3a5f") -> list:
    return [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(hex_bg)),
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
