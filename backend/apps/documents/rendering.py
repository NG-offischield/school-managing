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

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas
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


def _image(field_file):
    """An image of the storage (school logo, pupil photo, card background),
    or None when absent / unreadable: a broken image must never prevent an
    official document."""
    if not field_file:
        return None
    try:
        with field_file.open("rb") as handle:
            return ImageReader(io.BytesIO(handle.read()))
    except Exception:
        logger.warning("Unreadable image %s", getattr(field_file, "name", ""))
        return None


def _logo(school):
    return _image(school.logo)


def render(content, *, school, status, verification_code, generated_label):
    info = content["school"]
    primary = _color(info["primary_color"], "#173B73")
    secondary = _color(info["secondary_color"], "#36A2EB")
    logo = _logo(school)
    official = status == DocumentStatus.OFFICIAL

    pagesize = landscape(A4) if content.get("landscape") else A4

    def decorate(canvas, doc):
        width, height = pagesize
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
        pagesize=pagesize,
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
    text = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace(chr(10), "<br/>")  # multi-line cells (timetable)


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


# =============================================================================
# Student card (ID-1 format, recto / verso)
# =============================================================================

CARD = (85.6 * mm, 53.98 * mm)


def render_card(content, *, school, verification_code, qr_token, photo=None, background=None):
    """Recto: school identity, photo, pupil identity, annual QR (the
    EXISTING opaque token, encoded as is). Verso: emergency contacts, school
    contacts, verification code. Branding from School / SchoolBranding."""
    info = content["school"]
    primary = _color(info["primary_color"], "#173B73")
    fields = dict(content["fields"])
    width, height = CARD
    buffer = io.BytesIO()
    page = pdf_canvas.Canvas(buffer, pagesize=CARD)
    page.setTitle(content["title"])
    page.setAuthor(info["name"])
    background_image, logo, picture = _image(background), _logo(school), _image(photo)

    # --- recto ---
    if background_image is not None:
        page.drawImage(background_image, 0, 0, width=width, height=height, mask="auto")
    page.setFillColor(primary)
    page.rect(0, height - 11 * mm, width, 11 * mm, stroke=0, fill=1)
    x = 3 * mm
    if logo is not None:
        page.drawImage(
            logo, 2 * mm, height - 10 * mm, width=9 * mm, height=9 * mm, preserveAspectRatio=True, mask="auto"
        )
        x = 12 * mm
    page.setFillColor(colors.white)
    page.setFont("Helvetica-Bold", 7.5)
    page.drawString(x, height - 5 * mm, info["name"][:48])
    page.setFont("Helvetica", 5.5)
    page.drawString(x, height - 8.5 * mm, f"Carte d'élève — {fields['Année scolaire']}")
    if picture is not None:
        page.drawImage(picture, 3 * mm, 8 * mm, width=20 * mm, height=25 * mm, preserveAspectRatio=True, mask="auto")
    else:
        page.setStrokeColor(colors.lightgrey)
        page.rect(3 * mm, 8 * mm, 20 * mm, 25 * mm)
    page.setFillColor(colors.black)
    y = height - 15 * mm
    for label in ("Nom", "Prénom", "Sexe", "Né(e) le", "Classe", "Matricule"):
        page.setFont("Helvetica", 5)
        page.drawString(25 * mm, y, label)
        page.setFont("Helvetica-Bold", 6.5)
        page.drawString(37 * mm, y, str(fields.get(label, ""))[:28])
        y -= 4.2 * mm
    widget = QrCodeWidget(qr_token)
    x0, y0, x1, y1 = widget.getBounds()
    side = 22 * mm
    drawing = Drawing(side, side, transform=[side / (x1 - x0), 0, 0, side / (y1 - y0), 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, page, width - side - 2 * mm, 3 * mm)
    page.setFont("Helvetica", 4.5)
    page.drawString(3 * mm, 3 * mm, f"Carte n° {fields['Carte n°']}")
    page.showPage()

    # --- verso ---
    page.setFillColor(primary)
    page.rect(0, height - 7 * mm, width, 7 * mm, stroke=0, fill=1)
    page.setFillColor(colors.white)
    page.setFont("Helvetica-Bold", 6.5)
    page.drawString(3 * mm, height - 4.8 * mm, "En cas d'urgence")
    page.setFillColor(colors.black)
    y = height - 12 * mm
    for name, phone in content.get("emergency") or [["—", ""]]:
        page.setFont("Helvetica-Bold", 6)
        page.drawString(3 * mm, y, str(name)[:40])
        page.setFont("Helvetica", 6)
        page.drawRightString(width - 3 * mm, y, str(phone))
        y -= 4.5 * mm
    page.setFont("Helvetica", 5)
    contact = " · ".join(v for v in (info["phone"], info["email"]) if v)
    page.drawString(3 * mm, 14 * mm, f"{info['name']} — {info['address']}, {info['city']}"[:90])
    if contact:
        page.drawString(3 * mm, 10.5 * mm, contact[:90])
    page.drawString(3 * mm, 7 * mm, content.get("statement", "")[:95])
    page.setFillColor(colors.grey)
    page.drawString(3 * mm, 3 * mm, f"Code de vérification : {verification_code}")
    page.showPage()
    page.save()
    return buffer.getvalue()
