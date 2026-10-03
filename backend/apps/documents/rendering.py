"""PDF rendering with ReportLab (ADR 0016).

One layout for every official document, fed only by `content` (builders.py)
and the school's own identity (School / SchoolBranding):
- header band in the school's primary colour, logo if the school has one,
  name, legal name and contact details — nothing hard-coded;
- the document's fields, tables and summary;
- footer: school name, official / provisional mention, verification code,
  page number;
- PROVISIONAL documents carry a diagonal "PROVISOIRE" watermark, OFFICIAL
  ones an "OFFICIEL" stamp.
"""

import io
import logging

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import DocumentStatus

logger = logging.getLogger(__name__)
MARGIN = 15 * mm
HEADER_HEIGHT = 32 * mm


def _color(value, fallback):
    try:
        return colors.HexColor(value)
    except (ValueError, TypeError):
        return colors.HexColor(fallback)


def _logo(school):
    """The school's logo (default storage), or None when absent/unreadable."""
    if not school.logo:
        return None
    try:
        with school.logo.open("rb") as handle:
            return ImageReader(io.BytesIO(handle.read()))
    except Exception:  # a broken logo must not prevent an official document
        logger.warning("Unreadable logo for school %s", school.pk)
        return None


def render(content, *, school, status, verification_code, generated_label):
    info = content["school"]
    primary = _color(info["primary_color"], "#173B73")
    secondary = _color(info["secondary_color"], "#36A2EB")
    logo = _logo(school)
    official = status == DocumentStatus.OFFICIAL

    def decorate(canvas, doc):
        width, height = A4
        canvas.saveState()
        # Header band.
        canvas.setFillColor(primary)
        canvas.rect(0, height - HEADER_HEIGHT, width, HEADER_HEIGHT, stroke=0, fill=1)
        x = MARGIN
        if logo is not None:
            canvas.drawImage(
                logo,
                MARGIN,
                height - HEADER_HEIGHT + 4 * mm,
                width=24 * mm,
                height=24 * mm,
                preserveAspectRatio=True,
                mask="auto",
            )
            x += 28 * mm
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 14)
        canvas.drawString(x, height - 12 * mm, info["name"])
        canvas.setFont("Helvetica", 8)
        lines = [
            info["legal_name"],
            f"{info['address']} — {info['city']}, {info['country']}",
            " · ".join(v for v in (info["phone"], info["email"], info["website"]) if v),
        ]
        for i, text in enumerate(line for line in lines if line):
            canvas.drawString(x, height - 18 * mm - i * 4 * mm, text)
        # Watermark / stamp.
        if official:
            canvas.setStrokeColor(secondary)
            canvas.setFillColor(secondary)
            canvas.setFont("Helvetica-Bold", 10)
            canvas.roundRect(width - MARGIN - 32 * mm, height - HEADER_HEIGHT - 12 * mm, 32 * mm, 8 * mm, 2 * mm)
            canvas.drawCentredString(width - MARGIN - 16 * mm, height - HEADER_HEIGHT - 9.5 * mm, "OFFICIEL")
        else:
            canvas.setFillColor(colors.Color(0.85, 0.1, 0.1, alpha=0.15))
            canvas.setFont("Helvetica-Bold", 90)
            canvas.translate(width / 2, height / 2)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, "PROVISOIRE")
            canvas.rotate(-45)
            canvas.translate(-width / 2, -height / 2)
        # Footer.
        canvas.setFillColor(colors.grey)
        canvas.setFont("Helvetica", 7)
        mention = "Document officiel" if official else "Document provisoire — non valable comme pièce officielle"
        canvas.drawString(MARGIN, 10 * mm, f"{info['name']} — {mention} — {generated_label}")
        canvas.drawString(MARGIN, 6 * mm, f"Code de vérification : {verification_code}")
        canvas.drawRightString(width - MARGIN, 6 * mm, f"Page {doc.page}")
        canvas.restoreState()

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Title"], textColor=primary, spaceAfter=2)
    cell = ParagraphStyle("cell", parent=styles["BodyText"], fontSize=8, leading=10)
    head = ParagraphStyle("head", parent=cell, textColor=colors.white)
    story = [
        Spacer(1, 16 * mm),
        Paragraph(content["title"], title_style),
        Paragraph(content.get("subtitle", ""), styles["Heading4"]),
        Spacer(1, 3 * mm),
    ]
    if content.get("fields"):
        story.append(
            _grid(
                [[Paragraph(f"<b>{k}</b>", cell), Paragraph(_escape(v), cell)] for k, v in content["fields"]],
                primary,
                header=False,
                widths=[45 * mm, None],
            )
        )
        story.append(Spacer(1, 4 * mm))
    for table in content.get("tables", []):
        story.append(Paragraph(table["title"], styles["Heading5"]))
        rows = [[Paragraph(f"<b>{_escape(c)}</b>", head) for c in table["columns"]]]
        rows += [[Paragraph(_escape(v), cell) for v in row] for row in table["rows"]] or [
            [Paragraph("—", cell)] + [Paragraph("", cell)] * (len(table["columns"]) - 1)
        ]
        story.append(_grid(rows, primary, header=True))
        story.append(Spacer(1, 4 * mm))
    if content.get("summary"):
        story.append(
            _grid(
                [
                    [Paragraph(f"<b>{k}</b>", cell), Paragraph(f"<b>{_escape(v)}</b>", cell)]
                    for k, v in content["summary"]
                ],
                secondary,
                header=False,
                widths=[60 * mm, 60 * mm],
            )
        )
        story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(_escape(content.get("statement", "")), styles["Italic"]))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=HEADER_HEIGHT,
        bottomMargin=18 * mm,
        title=content["title"],
        author=info["name"],
        subject=content.get("subtitle", ""),
        creator="School platform",
    )
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def _escape(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _grid(rows, color, *, header, widths=None):
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), color), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    table.setStyle(TableStyle(style))
    return table
