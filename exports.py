"""
exports.py - formatted Excel (.xlsx) and PDF files for records and reports.

Used by: routes_bulk.py (exports, reports) and routes_records.py (one-record PDF).
Uses:    openpyxl (Excel), reportlab (PDF), branding.py (logo), static/fonts (PDF font)

Excel: styled header row, frozen header, filter buttons, sensible column widths, numbers
stored as real numbers. PDF: logo and company on top, wrapped table, page numbers.
The PDF font (Noto Sans) covers English and most European letters. Characters it does not
contain print as '?' in PDF; Excel keeps every character.
"""
import io
import os
import re
from datetime import datetime

from flask import Response, current_app
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from branding import custom_logo_path

BLUE = "0B6E99"
_FONT = {}


def _fonts():
    """Register the bundled Noto Sans once. Falls back to Helvetica if the files are missing."""
    if not _FONT:
        folder = os.path.join(current_app.static_folder, "fonts")
        try:
            pdfmetrics.registerFont(TTFont("NotoSans", os.path.join(folder, "NotoSans-Regular.ttf")))
            pdfmetrics.registerFont(TTFont("NotoSans-Bold", os.path.join(folder, "NotoSans-Bold.ttf")))
            _FONT.update(regular="NotoSans", bold="NotoSans-Bold",
                         glyphs=pdfmetrics.getFont("NotoSans").face.charToGlyph)
        except Exception:
            _FONT.update(regular="Helvetica", bold="Helvetica-Bold", glyphs=None)
    return _FONT


def _pdf_text(value):
    """Escape for the PDF paragraph and replace letters the font does not have."""
    text = "" if value is None else str(value)
    glyphs = _fonts()["glyphs"]
    if glyphs is not None:
        text = "".join(ch if (ord(ch) in glyphs or ch in "\n\t") else "?" for ch in text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _number(value):
    try:
        text = str(value).replace(",", "")
        number = float(text)
        return int(number) if number.is_integer() and "." not in text else number
    except (TypeError, ValueError):
        return value


def safe_name(text, default="export"):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text or "").strip("_") or default


# ------------------------------------------------------------------ Excel
def workbook_xlsx(sheets, company=""):
    """sheets = [{'title','header','rows','kinds','subtitle'}]. Returns the file as bytes."""
    wb = Workbook()
    thin = Side(style="thin", color="D3DBE0")
    for index, sheet in enumerate(sheets):
        ws = wb.active if index == 0 else wb.create_sheet()
        ws.title = re.sub(r"[\[\]\*\?/\\:]", " ", sheet["title"])[:31] or "Sheet"
        header, rows = sheet["header"], sheet["rows"]
        kinds = sheet.get("kinds") or ["text"] * len(header)
        ws["A1"] = (company + " - " if company else "") + sheet["title"]
        ws["A1"].font = Font(size=14, bold=True, color=BLUE)
        ws["A2"] = sheet.get("subtitle") or datetime.now().strftime("Created %d %b %Y %H:%M")
        ws["A2"].font = Font(size=9, color="506A7B")
        for col, name in enumerate(header, start=1):
            cell = ws.cell(row=4, column=col, value=name)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor=BLUE)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        widths = [min(max(len(str(h)) + 2, 10), 40) for h in header]
        for r, row in enumerate(rows, start=5):
            for c, value in enumerate(row, start=1):
                if value is not None and kinds[c - 1] == "number":
                    value = _number(value)
                cell = ws.cell(row=r, column=c, value=value)
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
                if r % 2 == 0:
                    cell.fill = PatternFill("solid", fgColor="F3F7FA")
                if isinstance(value, float):
                    cell.number_format = "#,##0.00"
                elif isinstance(value, int) and kinds[c - 1] == "number":
                    cell.number_format = "#,##0"
                widths[c - 1] = min(max(widths[c - 1], len(str(value or "")) + 2), 50)
        for c, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(c)].width = w
        ws.freeze_panes = "A5"
        if rows:
            ws.auto_filter.ref = f"A4:{get_column_letter(len(header))}{4 + len(rows)}"
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ PDF
def document_pdf(title, subtitle, sections, company=""):
    """sections = [(heading, header, rows)]. Returns the PDF as bytes."""
    font = _fonts()
    widest = max([len(s[1]) for s in sections] + [1])
    page = landscape(A4) if widest > 5 else A4
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=1.2 * cm, rightMargin=1.2 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.5 * cm, title=title)
    small = 9 if widest <= 6 else 7.5 if widest <= 10 else 6.5
    cell = ParagraphStyle("cell", fontName=font["regular"], fontSize=small, leading=small + 2.5)
    head = ParagraphStyle("head", fontName=font["bold"], fontSize=small, leading=small + 2.5, textColor=colors.white)
    h1 = ParagraphStyle("h1", fontName=font["bold"], fontSize=15, textColor=colors.HexColor("#" + BLUE), leading=19)
    h2 = ParagraphStyle("h2", fontName=font["bold"], fontSize=11, textColor=colors.HexColor("#10283A"), leading=14, spaceBefore=10)
    meta = ParagraphStyle("meta", fontName=font["regular"], fontSize=8.5, textColor=colors.HexColor("#506A7B"), leading=11)

    story = []
    banner = [[Paragraph(_pdf_text(company), h2), Paragraph(_pdf_text(subtitle), meta)]]
    logo = custom_logo_path() or os.path.join(current_app.static_folder, "logo.png")
    try:
        banner[0].insert(0, Image(logo, width=2.6 * cm, height=1.6 * cm, kind="proportional"))
    except Exception:                                  # unsupported logo type: skip the picture
        banner[0].insert(0, "")
    story.append(Table(banner, colWidths=[3 * cm, None, 8 * cm],
                       style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.HexColor("#49C7F5"))]))
    story += [Spacer(1, 6), Paragraph(_pdf_text(title), h1), Spacer(1, 4)]
    usable = page[0] - 2.4 * cm
    for heading, header, rows in sections:
        if heading:
            story.append(Paragraph(_pdf_text(heading), h2))
        data = [[Paragraph(_pdf_text(h), head) for h in header]]
        data += [[Paragraph(_pdf_text(v), cell) for v in row] for row in rows] or \
                [[Paragraph(_pdf_text("No data."), cell)] + [""] * (len(header) - 1)]
        table = Table(data, colWidths=[usable / len(header)] * len(header), repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + BLUE)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F7FA")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D3DBE0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
        story += [table, Spacer(1, 8)]

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont(font["regular"], 8)
        canvas.setFillColor(colors.HexColor("#506A7B"))
        canvas.drawRightString(page[0] - 1.2 * cm, 0.8 * cm, f"Page {canvas.getPageNumber()}")
        canvas.drawString(1.2 * cm, 0.8 * cm, datetime.now().strftime("%d %b %Y %H:%M"))
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# ------------------------------------------------------------------ one call for the routes
def table_file(fmt, title, header, rows, kinds=None, subtitle="", company="", filename="export"):
    """Build an xlsx or pdf download of one table."""
    stamp = datetime.now().strftime("%Y-%m-%d")
    if fmt == "pdf":
        data = document_pdf(title, subtitle, [("", header, rows)], company)
        mime, ext = "application/pdf", "pdf"
    else:
        data = workbook_xlsx([{"title": title, "header": header, "rows": rows, "kinds": kinds,
                               "subtitle": subtitle}], company)
        mime, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    resp = Response(data, mimetype=mime)
    resp.headers["Content-Disposition"] = f'attachment; filename="{safe_name(filename)}_{stamp}.{ext}"'
    return resp


def sheets_file(fmt, title, sheets, company="", filename="report", subtitle=""):
    """Several tables in one download. sheets = [{'title','header','rows','kinds'}]."""
    stamp = datetime.now().strftime("%Y-%m-%d")
    if fmt == "pdf":
        data = document_pdf(title, subtitle, [(s["title"], s["header"], s["rows"]) for s in sheets], company)
        mime, ext = "application/pdf", "pdf"
    else:
        data = workbook_xlsx([dict(s, subtitle=subtitle) for s in sheets], company)
        mime, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    resp = Response(data, mimetype=mime)
    resp.headers["Content-Disposition"] = f'attachment; filename="{safe_name(filename)}_{stamp}.{ext}"'
    return resp
