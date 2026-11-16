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
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Rect, String

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


def _signatures_table(sigs, usable, font):
    """Signature blocks, aligned by count (approved in sig-alignment-demo.jpg).
    Each block is one quarter of the page wide; inside a block the title,
    the name and the designation stay CENTRED in respect to the name.
    Only where the blocks sit on the page changes with the count:
    1 signature sits at the left (never in the middle), 2 sit at the
    left and the right, 3 sit at the left, the centre and the right,
    4 spread evenly across the page. More than four wrap in groups of four.
    Returns None when there are no signatures."""
    if not sigs:
        return None
    small = ParagraphStyle("cell", fontName=font["regular"], fontSize=9, leading=12)
    _sig_title = ParagraphStyle("sigt", fontName=font["bold"], fontSize=9, leading=12, alignment=1)
    _sig_line = ParagraphStyle("sigl", fontName=font["regular"], fontSize=9, leading=12, alignment=1)
    _sig_name = ParagraphStyle("sign", fontName=font["bold"], fontSize=9, leading=12, alignment=1)
    _sig_role = ParagraphStyle("sigr", fontName=font["regular"], fontSize=9, leading=12, textColor=colors.HexColor("#506A7B"), alignment=1)

    def _block(t, n, d):
        return Table([
            [Paragraph(f"<b>{_pdf_text(t)}</b>", _sig_title)],
            [Spacer(1, 48)],
            [Paragraph("_________________________", _sig_line)],
            [Paragraph(f"<b>{_pdf_text(n)}</b>", _sig_name)],
            [Paragraph(_pdf_text(d), _sig_role)],
        ], colWidths=[usable / 4], style=[
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("VALIGN", (0, 0), (-1, -1), "TOP")])

    def _block_img(t, n, d, dept, image):
        # A chain step: the saved signature image on top at a fixed height
        # (a blank space of the same height when the step has not signed
        # yet, so the lines align), then the role label, the name, the
        # designation and the department, all centred — the same block as
        # the application letter's FOR OFFICE USE.
        _rows = [[_sig_image_fixed_height(image, 1.4 * cm)],
                 [Paragraph(f"<b>{_pdf_text(t)}</b>", _sig_title)],
                 [Paragraph(f"<b>{_pdf_text(n)}</b>", _sig_name)],
                 [Paragraph(_pdf_text(d), _sig_role)]]
        if dept:
            _rows.append([Paragraph(_pdf_text(dept), _sig_role)])
        return Table(_rows, colWidths=[usable / 4], style=[
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "TOP")])

    _blocks = [_block_img(*s) if len(s) == 5 else _block(s[0], s[1], s[2]) for s in sigs]
    _w = usable / 4
    _n = len(_blocks)
    if _n == 1:
        _data, _cw = [[_blocks[0]]], [_w]
    elif _n == 2:
        _data, _cw = [[_blocks[0], "", _blocks[1]]], [_w, usable / 2, _w]
    elif _n == 3:
        _data, _cw = [[_blocks[0], "", _blocks[1], "", _blocks[2]]], [_w, usable / 8, _w, usable / 8, _w]
    else:
        _data, _cw = [], [_w] * 4
        for _i in range(0, _n, 4):
            _chunk = _blocks[_i:_i + 4]
            _chunk += [""] * (4 - len(_chunk))
            _data.append(_chunk)
    return Table(_data, colWidths=_cw, hAlign="LEFT", style=[
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP")])


def _sig_image_fixed_height(path, height):
    """A signature image drawn at exactly `height` tall, width proportional.
    Every signature image in a row is the same height, so the line under
    each signature (which sits at the same place inside its image) lines up
    across the blocks. Drawing by width (or fitting a box) makes wider
    signatures shorter, and their lines sit higher — the misalignment the
    user reported. Returns a Spacer when the file is missing."""
    try:
        if not path or not os.path.exists(path):
            return Spacer(1, height)
        ir = ImageReader(path)
        iw, ih = ir.getSize()
        if not iw or not ih:
            return Spacer(1, height)
        return Image(path, width=height * iw / ih, height=height)
    except Exception:
        return Spacer(1, height)


def _application_sig_table(blocks, usable):
    """Signature blocks for an application letter, laid out by count the
    same way as the invoice/request signatures (approved in
    sig-alignment-demo.jpg): each block is one quarter of the page wide and
    everything inside it is CENTRED. 1 block sits at the left, 2 sit at
    the left and the right, 3 sit at the left, the centre and the right,
    4 spread evenly across the page. More than four wrap in groups of
    four. A block is (image_path, title, name, designation, department): the
    signature image on top (fixed height, so the lines align), then the
    title, then the name, then the designation, then the department —
    with tight spacing, no extra gap. An older four-element block (no
    department) still works. Returns None when there are no blocks."""
    if not blocks:
        return None
    _t = ParagraphStyle("appt", fontName="Times-Bold", fontSize=12, leading=16, alignment=1)
    _n = ParagraphStyle("appn", fontName="Times-Bold", fontSize=12, leading=16, alignment=1)
    _d = ParagraphStyle("appd", fontName="Times-Roman", fontSize=12, leading=16, alignment=1,
                        textColor=colors.HexColor("#444444"))

    def _block(image_path, title, name, designation, department=""):
        _rows = [[_sig_image_fixed_height(image_path, 1.4 * cm)],
                 [Paragraph(_times_text(title), _t)],
                 [Paragraph(_times_text(name), _n)]]
        if designation:
            _rows.append([Paragraph(_times_text(designation), _d)])
        if department:
            _rows.append([Paragraph(_times_text(department), _d)])
        return Table(_rows, colWidths=[usable / 4], style=[
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "TOP")])

    _blocks = [_block(*b) for b in blocks]
    _w = usable / 4
    _n = len(_blocks)
    if _n == 1:
        _data, _cw = [[_blocks[0]]], [_w]
    elif _n == 2:
        _data, _cw = [[_blocks[0], "", _blocks[1]]], [_w, usable / 2, _w]
    elif _n == 3:
        _data, _cw = [[_blocks[0], "", _blocks[1], "", _blocks[2]]], [_w, usable / 8, _w, usable / 8, _w]
    else:
        _data, _cw = [], [_w] * 4
        for _i in range(0, _n, 4):
            _chunk = _blocks[_i:_i + 4]
            _chunk += [""] * (4 - len(_chunk))
            _data.append(_chunk)
    return Table(_data, colWidths=_cw, hAlign="LEFT", style=[
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP")])


def _number(value):
    try:
        text = str(value).replace(",", "")
        number = float(text)
        return int(number) if number.is_integer() and "." not in text else number
    except (TypeError, ValueError):
        return value


def safe_name(text, default="export"):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text or "").strip("_") or default


def _safe_excel_cell(cell):
    """Stop Excel formula injection: a text cell starting with =, +, -, @,
    tab or carriage return must stay text, never a formula.

    openpyxl turns a value starting with '=' into a formula cell (<f>).
    Forcing data_type to 's' after setting the value writes it as plain
    inline text instead, with the exact characters preserved (unlike a
    leading-apostrophe prefix, which would change the visible value).
    CSV exports already prefix such values; this is the Excel equivalent."""
    try:
        v = cell.value
    except Exception:
        return
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        cell.data_type = "s"


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
            _safe_excel_cell(cell)
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
                _safe_excel_cell(cell)
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


# ------------------------------------------------------------------ Sales Pipeline report (build 66)
def _fmt_money(x):
    """1,035,000 — a whole-number amount with commas."""
    return f"{x:,.0f}"


def _fmt_m(x):
    """1.03 M — a large amount in millions, two decimals."""
    return f"{x / 1000000:.2f} M"


def _fmt_k(x):
    """355K — an amount in thousands, whole."""
    return f"{x / 1000:.0f}K"


def _kpi_row(items, font, col_width):
    """A row of stat blocks: big coloured number, bold label, small grey
    note, each with a coloured bar on the left. items = [(number, label,
    sub, colour_hex), ...]."""
    num = ParagraphStyle("kpin", fontName=font["bold"], fontSize=16, leading=18)
    lab = ParagraphStyle("kpil", fontName=font["bold"], fontSize=9, leading=11,
                         textColor=colors.HexColor("#10283A"))
    sub = ParagraphStyle("kpis", fontName=font["regular"], fontSize=8, leading=10,
                         textColor=colors.HexColor("#506A7B"))
    row = []
    style = []
    for i, (number, label, note, colour) in enumerate(items):
        st_num = ParagraphStyle("kpin" + str(i), parent=num, textColor=colors.HexColor("#" + colour))
        row.append([Paragraph(_pdf_text(number), st_num),
                    Paragraph(_pdf_text(label), lab),
                    Paragraph(_pdf_text(note), sub)])
        style += [("BACKGROUND", (i, 0), (i, 0), colors.HexColor("#F2F6FA")),
                  ("LINEBEFORE", (i, 0), (i, 0), 4, colors.HexColor("#" + colour))]
    t = Table([row], colWidths=[col_width] * len(items))
    t.setStyle(TableStyle(style + [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _band(text, colour, font, size=11):
    """A full-width coloured section header with white bold text."""
    st = ParagraphStyle("band", fontName=font["bold"], fontSize=size, leading=size + 3,
                        textColor=colors.white)
    t = Table([[Paragraph(_pdf_text(text), st)]], colWidths=[None])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#" + colour)),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROUNDEDCORNERS", [4, 4, 4, 4])]))
    return t


def _hbar(segments, max_total, width, height, font, total_label):
    """A horizontal stacked bar: segments = [(value, colour_hex, label)].
    The bar length is proportional to the total relative to max_total;
    the total is printed at the right end. Returns a Drawing."""
    d = Drawing(width + 42, height)
    x = 0.0
    for value, colour, label in segments:
        w = width * value / max_total if max_total else 0
        if w > 0:
            d.add(Rect(x, 0, w, height, fillColor=colors.HexColor("#" + colour), strokeColor=None))
            if label:
                d.add(String(x + w / 2, height / 2 - 2.5, str(label), fontName=font["bold"],
                             fontSize=8, fillColor=colors.white, textAnchor="middle"))
        x += w
    d.add(String(width + 6, height / 2 - 2.5, str(total_label), fontName=font["bold"],
                 fontSize=9, fillColor=colors.HexColor("#10283A")))
    return d


def _bar_table(rows, font, bar_width=250, height=13):
    """rows = [(label, drawing)] — a KAM name and its bar, one per row."""
    lab = ParagraphStyle("barlab", fontName=font["regular"], fontSize=9, leading=11,
                         textColor=colors.HexColor("#10283A"))
    if not rows:
        # An empty Table is refused by ReportLab ("must have at least a
        # row and column"), so never build one from an empty list.
        return Paragraph(_pdf_text("No data"), lab)
    data = [[Paragraph(_pdf_text(label), lab), drawing] for label, drawing in rows]
    t = Table(data, colWidths=[92, bar_width + 42])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    return t


def sales_pipeline_report_pdf(dept_name, tab_name, data, company="", prepared_for="Managing Director"):
    """The Client Follow-up & Sales Pipeline report, in the style of the
    user's own report: title band, follow-up on the left, pipeline on
    the right, key message at the bottom. data is the dict from
    routes_deptdb._sales_pipeline_data, computed from the selected rows
    only. Returns the PDF as bytes (landscape A4, one page)."""
    font = _fonts()
    page = landscape(A4)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=1.2 * cm, rightMargin=1.2 * cm,
                            topMargin=0.4 * cm, bottomMargin=0.8 * cm,
                            title="Client Follow-up & Sales Pipeline Report")
    h3 = ParagraphStyle("h3", fontName=font["bold"], fontSize=10, leading=13,
                        textColor=colors.HexColor("#10283A"), spaceBefore=6, spaceAfter=2)
    body = ParagraphStyle("body", fontName=font["regular"], fontSize=9, leading=12,
                          textColor=colors.HexColor("#10283A"))
    small = ParagraphStyle("small", fontName=font["regular"], fontSize=8, leading=10,
                           textColor=colors.HexColor("#506A7B"))
    title_st = ParagraphStyle("title", fontName=font["bold"], fontSize=15, leading=18,
                              textColor=colors.white)
    sub_st = ParagraphStyle("subtitle", fontName=font["regular"], fontSize=9, leading=12,
                            textColor=colors.HexColor("#CFE0F5"))

    today = datetime.now().strftime("%d %B %Y")
    total = data["total"]
    visit, phone = data["visit"], data["phone"]
    story = []
    # Title band.
    head = Table([[Paragraph(_pdf_text("CLIENT FOLLOW-UP & SALES PIPELINE REPORT"), title_st)],
                  [Paragraph(_pdf_text(
                      f"Prepared for: {prepared_for}  |  Date: {today}  |  Amounts in BDT  |  "
                      f"From the {tab_name} tab ({dept_name}) — {total} of {total} rows selected"), sub_st)]],
                 colWidths=[page[0] - 2.4 * cm])
    head.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1E5AA8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, 0), 7), ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
        ("TOPPADDING", (0, 1), (-1, 1), 2)]))
    story += [head, Spacer(1, 6)]

    # ---- left column: existing client follow-up ----
    left = []
    left.append(_band(f"1.  EXISTING CLIENT FOLLOW-UP  (Live clients: {total})", "1F77C8", font))
    left.append(Spacer(1, 4))
    left.append(_kpi_row([
        (str(visit), "Physical visit done", f"{100 * visit // total}% of clients" if total else "—", "1F77C8"),
        (str(phone), "Reached by phone", f"{100 * phone // total}% of clients" if total else "—", "F58220"),
    ], font, 185))
    left.append(Paragraph(_pdf_text("Follow-up status by Account Manager (no. of live clients)"), h3))
    if data["kam_follow"]:
        max_follow = max((t for _, _, _, t in data["kam_follow"]), default=0)
        left.append(_bar_table([
            (kam, _hbar([(v, "1F77C8", str(v) if v else ""), (p, "F58220", str(p) if p else "")],
                        max_follow, 250, 10, font, str(t)))
            for kam, v, p, t in data["kam_follow"]], font))
    else:
        # No rows at all were selected with a follow-up to show; a bar
        # table with no rows would crash the PDF (an empty Table is
        # refused), so say so instead.
        left.append(Paragraph(_pdf_text("No follow-ups recorded for the selected rows."), small))
    left.append(Paragraph(_pdf_text(
        "Physical visit (blue)  |  Phone call (orange)  |  Clients reached (visit + phone): "
        f"{data['reached_pct']}%"), small))
    reasons = data["phone_reasons"]
    if phone and (reasons["outside"] or reasons["busy"] or reasons["other"]):
        why = ParagraphStyle("why", parent=body, fontSize=9, leading=12)
        why_t = ParagraphStyle("why_t", fontName=font["bold"], fontSize=9, leading=12,
                               textColor=colors.HexColor("#B45309"))
        lines = [Paragraph(_pdf_text("Why some clients were contacted by phone"), why_t),
                 Paragraph(_pdf_text(
                     f"{phone} clients were reached by phone:"), why)]
        if reasons["outside"]:
            lines.append(Paragraph(_pdf_text(f"  - {reasons['outside']} are outside Dhaka city"), why))
        if reasons["busy"]:
            lines.append(Paragraph(_pdf_text(f"  - {reasons['busy']} are busy — physical visit to be scheduled"), why))
        if reasons["other"]:
            lines.append(Paragraph(_pdf_text(f"  - {reasons['other']} for another reason"), why))
        box = Table([[lines]], colWidths=[370])
        box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FDF6EE")),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#F0D48A")),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        left += [Spacer(1, 6), box]

    # ---- right column: sales pipeline ----
    right = []
    right.append(_band(f"2.  SALES PIPELINE  ({data['prospects']} prospects)", "6B3FA0", font))
    right.append(Spacer(1, 4))
    right.append(_kpi_row([
        (str(data["prospects"]), "Prospects", "in pipeline", "1F77C8"),
        (_fmt_m(data["mrc_total"]), "Potential MRC", _fmt_money(data["mrc_total"]), "1F77C8"),
    ], font, 185))
    right.append(Spacer(1, 4))
    right.append(_kpi_row([
        (str(data["done_n"]), "Done (closed)", "MRC " + _fmt_money(data["done_mrc"]), "1F77C8"),
        (str(data["open_n"]), "Open / In progress", "MRC " + _fmt_money(data["open_mrc"]), "F58220"),
    ], font, 185))
    if data["terminated_n"]:
        right.append(Paragraph(_pdf_text(
            f"{data['terminated_n']} terminated — not in the pipeline."), small))
    ref = data["referred"]
    if ref:
        ref_head = ParagraphStyle("refh", fontName=font["bold"], fontSize=10, leading=13,
                                  textColor=colors.white)
        ref_num = ParagraphStyle("refn", fontName=font["bold"], fontSize=18, leading=20,
                                 textColor=colors.HexColor("#D35400"))
        ref_lab = ParagraphStyle("refl", fontName=font["regular"], fontSize=8, leading=10,
                                 textColor=colors.HexColor("#506A7B"))
        ref_body = ParagraphStyle("refb", fontName=font["regular"], fontSize=9, leading=12,
                                  textColor=colors.HexColor("#10283A"))
        by_kam = "  ".join(f"{kam} {n}" for kam, n in ref["by_kam"])
        nums = Table([[
            [Paragraph(_pdf_text(str(ref["prospects"])), ref_num), Paragraph(_pdf_text("prospects"), ref_lab)],
            [Paragraph(_pdf_text(_fmt_money(ref["mrc"])), ref_num), Paragraph(_pdf_text("MRC (BDT)"), ref_lab)],
            [Paragraph(_pdf_text(f"{ref['pct']}%"), ref_num), Paragraph(_pdf_text("of pipeline MRC"), ref_lab)],
        ]], colWidths=[123, 123, 123])
        nums.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                  ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        refbox = Table([
            [Paragraph(_pdf_text("*  REFERRED BY " + ref["name"].upper()), ref_head)],
            [nums],
            [Paragraph(_pdf_text(f"By KAM: {by_kam}  |  Done {ref['done']}, Open {ref['open']}"), ref_body)],
        ], colWidths=[370])
        refbox.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D35400")),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#FDF6EE")),
            ("BOX", (0, 0), (-1, -1), 1.2, colors.HexColor("#E67E22")),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        right += [Spacer(1, 6), refbox]
    right.append(Paragraph(_pdf_text("Pipeline MRC by KAM (BDT thousand)"), h3))
    if data["kam_mrc"]:
        max_mrc = max((t for _, _, _, t in data["kam_mrc"]), default=0)
        right.append(_bar_table([
            (kam, _hbar([(o, "6B3FA0", ""), (d, "1F77C8", "")], max_mrc, 250, 10, font, _fmt_k(t)))
            for kam, o, d, t in data["kam_mrc"]], font))
        right.append(Paragraph(_pdf_text("Open (purple)  |  Done (blue)"), small))
    else:
        # No selected row is Open or Done (blank deal stage, or every
        # row Terminated): there is no pipeline MRC to chart. A bar
        # table with no rows would crash the PDF (an empty Table is
        # refused), so say so instead of building one.
        right.append(Paragraph(_pdf_text("No open or done prospects in the selected rows."), small))
    if data["top5"]:
        right.append(Paragraph(_pdf_text("Top 5 open prospects by MRC"), h3))
        th = ParagraphStyle("th", fontName=font["bold"], fontSize=9, leading=11, textColor=colors.white)
        td = ParagraphStyle("td", fontName=font["regular"], fontSize=9, leading=11,
                            textColor=colors.HexColor("#10283A"))
        tdr = ParagraphStyle("tdr", parent=td, alignment=2)
        top = [[Paragraph(_pdf_text("Prospect"), th), Paragraph(_pdf_text("KAM"), th),
                Paragraph(_pdf_text("MRC"), th)]]
        top += [[Paragraph(_pdf_text(name), td), Paragraph(_pdf_text(kam), td),
                 Paragraph(_pdf_text(_fmt_money(mrc)), tdr)] for name, kam, mrc in data["top5"]]
        top_t = Table(top, colWidths=[200, 90, 80])
        top_t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6B3FA0")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6FA")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D3DBE0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
        right.append(top_t)

    # The two columns side by side, with a gap between them.
    cols = Table([[left, "", right]], colWidths=[370, 14, 370])
    cols.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                              ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story.append(cols)

    # Key message band.
    key_st = ParagraphStyle("key", fontName=font["regular"], fontSize=9, leading=12,
                            textColor=colors.white)
    key_b = ParagraphStyle("keyb", fontName=font["bold"], fontSize=9, leading=12,
                           textColor=colors.HexColor("#FFD166"))
    visit_pct = 100 * visit // total if total else 0
    msg1 = (f"Visits: most existing clients are covered — {visit} of {total} live clients ({visit_pct}%) "
            f"were visited physically; {phone} were reached by phone because they are busy or outside Dhaka. "
            f"More time is needed to cover all remaining {phone} clients with physical visits.")
    msg2 = (f"Pipeline: {data['prospects']} prospects worth BDT {_fmt_money(data['mrc_total'])} MRC; "
            f"{data['done_n']} are marked Done and {data['open_n']} are open.")
    if ref:
        msg2 += (f" {ref['prospects']} prospects (BDT {_fmt_money(ref['mrc'])}) were referred by "
                 f"{ref['name']}.")
    key = Table([[Paragraph(_pdf_text("KEY MESSAGE"), key_b)],
                 [[Paragraph(_pdf_text(msg1), key_st), Paragraph(_pdf_text(msg2), key_st)]]],
                colWidths=[page[0] - 2.4 * cm])
    key.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1E5AA8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
        ("TOPPADDING", (0, 1), (-1, 1), 2)]))
    story += [Spacer(1, 6), key]

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont(font["regular"], 8)
        canvas.setFillColor(colors.HexColor("#506A7B"))
        canvas.drawRightString(page[0] - 1.2 * cm, 0.8 * cm, f"Page {canvas.getPageNumber()}")
        canvas.drawString(1.2 * cm, 0.8 * cm, datetime.now().strftime("%d %b %Y %H:%M"))
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# ------------------------------------------------------------------ Invoice PDF (v4 layout)
def invoice_pdf(title, subtitle, meta, bill_to, kind, colour, cols, rows, totals, words, terms, sigs, code, company="",
                company_address="", show_address=True,
                logo_left=None, logo_right=None, watermark_on=False, watermark_text="", qr_url="", is_approved=False, is_pending=False, is_rejected=False, hide_watermark=False):
    """Invoice PDF, layout v5 (approved in invoice-format-v5.jpg):
    Top row: left logo + company name and address CENTRED in the middle,
    right second logo in the top right corner. Then meta, one field per
    line: "Invoice No. - JOY-0001", then Reference (only when set) under
    it, then Bill to under that; Date on the right, also one line
    ("Date - 2026-11-09"). Then the invoice type centred ON TOP OF THE
    TABLE, then the table (moved lower). Currency is beside every amount
    (the caller formats amounts as '18,500.00 BDT'). Signatures are
    aligned by count (see _signatures_table): 1 at the left, 2 at the
    left and right, 3 at left, centre and right, 4 spread evenly; the
    title, name and designation stay centred in respect to the name
    inside each block. No footer text between the QR and the page number.
    The QR encodes qr_url (the portal's real address); the old
    https://portal host is never used. Watermark: OFF by default; the
    grey APPROVED seal is drawn at the bottom right when the invoice's
    status is Approved (is_approved); the grey PENDING stamp is drawn
    at the bottom right when the status is Pending (is_pending). A newly created invoice shows
    no watermark at all; the seal and the stamp come ONLY from the
    invoice's status, never from the template's watermark text."""
    import segno as _segno
    font = _fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.4 * cm, rightMargin=1.4 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.4 * cm, title=title)
    accent = colors.HexColor("#" + colour.lstrip("#"))
    small = ParagraphStyle("cell", fontName=font["regular"], fontSize=9, leading=12)
    head = ParagraphStyle("head", fontName=font["bold"], fontSize=9, leading=12, textColor=colors.white)
    h1 = ParagraphStyle("h1", fontName=font["bold"], fontSize=22, textColor=accent, leading=26, alignment=1)
    sub = ParagraphStyle("sub", fontName=font["regular"], fontSize=9, textColor=colors.HexColor("#506A7B"), leading=12, alignment=1)
    meta_s = ParagraphStyle("meta", fontName=font["regular"], fontSize=8.5, textColor=colors.HexColor("#506A7B"), leading=11)
    meta_b = ParagraphStyle("metab", fontName=font["bold"], fontSize=10, textColor=colors.HexColor("#10283A"), leading=13)
    meta_r = ParagraphStyle("metar", fontName=font["regular"], fontSize=8.5, textColor=colors.HexColor("#506A7B"), leading=11, alignment=2)
    right_s = ParagraphStyle("right", fontName=font["regular"], fontSize=9, leading=12, alignment=2)
    right_b = ParagraphStyle("rightb", fontName=font["bold"], fontSize=10, leading=13, alignment=2)
    story = []
    # top row
    def _img(path, w=2.6 * cm, h=1.6 * cm):
        try:
            return Image(path, width=w, height=h, kind="proportional")
        except Exception:
            return ""
    left_logo = _img(logo_left) if logo_left else _img(custom_logo_path() or os.path.join(current_app.static_folder, "logo.png"))
    right_logo = _img(logo_right, w=2.2 * cm, h=1.4 * cm) if logo_right else ""
    # Top row: the company name and address come from the template that made
    # this invoice (chosen by the dept admin); no email is ever shown here.
    # The name and address sit CENTRED in the middle of the top row.
    if show_address and company_address:
        company_para = Paragraph(f"<b>{_pdf_text(company)}</b><br/><font color='#506A7B'>{_pdf_text(company_address)}</font>",
                                 ParagraphStyle("comp", fontName=font["bold"], fontSize=11, leading=14, alignment=1))
    else:
        company_para = Paragraph(f"<b>{_pdf_text(company)}</b>",
                                 ParagraphStyle("comp", fontName=font["bold"], fontSize=11, leading=14, alignment=1))
    banner = Table([[left_logo, company_para, right_logo]], colWidths=[3 * cm, None, 3 * cm],
                   style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, 0), 1.5, accent)])
    story += [banner, Spacer(1, 10)]
    # meta: one field per line — "Invoice No. - JOY-0001", then
    # Reference (only when the user put one in) under it, then Bill to
    # under that; Date on the right, also one line.
    _lab_map = {"INVOICE NO.": "Invoice No.", "REFERENCE": "Reference", "DATE": "Date"}
    meta_d = {lab: val for lab, val in meta}
    left_rows = []
    for _lab in ("INVOICE NO.", "REFERENCE"):
        if _lab in meta_d:
            left_rows.append([Paragraph(f"<font color='#506A7B'>{_pdf_text(_lab_map.get(_lab, _lab))} -</font> <font size='10'><b>{_pdf_text(meta_d[_lab])}</b></font>", meta_s)])
    # "Bill to" only appears when there is a customer to bill: a
    # Conveyance, Admin Expense or Purchase Request invoice has no
    # customer (its form has no customer field), so the line used to
    # print empty. A Billing invoice still shows it, and a customer
    # that exists but is hidden from strangers still shows the "—".
    if bill_to and ((bill_to[0] or "").strip() or (bill_to[1] or "").strip()):
        _bill = f"<font color='#506A7B'>Bill to -</font> <font size='10'><b>{_pdf_text(bill_to[0])}</b></font>"
        if bill_to[1]:
            _bill += f"<br/>{_pdf_text(bill_to[1])}"
        left_rows.append([Paragraph(_bill, meta_s)])
    _left = Table(left_rows, colWidths=[9 * cm],
                  style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                         ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)])
    _date = Paragraph(f"<font color='#506A7B'>Date -</font> <font size='10'><b>{_pdf_text(meta_d.get('DATE', ''))}</b></font>", meta_r)
    story.append(Table([[_left, _date]], colWidths=[None, 5 * cm], style=[("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(Spacer(1, 12))
    # invoice type on top of the table
    story += [Paragraph(_pdf_text(title), h1), Paragraph(_pdf_text(subtitle), sub), Spacer(1, 10)]
    # table (lower than the old top-right title layout)
    usable = A4[0] - 2.8 * cm
    data = [[Paragraph(_pdf_text(h), head) for h in cols]]
    data += [[Paragraph(_pdf_text(v), small) for v in row] for row in rows] or [[Paragraph("No lines.", small)]]
    table = Table(data, colWidths=[usable / len(cols)] * len(cols), repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), accent), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F7FA")]),
                               ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D3DBE0")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    story += [table, Spacer(1, 10)]
    # totals, right aligned
    tot_data = [[Paragraph(_pdf_text(lab), small), Paragraph(_pdf_text(val), ParagraphStyle("tot", fontName=font["bold"], fontSize=10, leading=13, alignment=2))] for lab, val in totals]
    story.append(Table(tot_data, colWidths=[usable - 5 * cm, 5 * cm], style=[("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EFF4F8")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(Spacer(1, 10))
    if words:
        story.append(Table([[Paragraph(_pdf_text("In words: " + words), small)]], colWidths=[usable], style=[("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F6F9")), ("LINEBEFORE", (0, 0), (0, 0), 3, accent)]))
        story.append(Spacer(1, 8))
    if terms:
        story.append(Paragraph(_pdf_text("Terms: " + terms), small))
    # Signatures, aligned by count (see _signatures_table): 1 at the
    # left, 2 at the left and right, 3 at left, centre and right, 4 spread
    # evenly. The title, name and designation stay centred in respect to
    # the name inside each block.
    story.append(Spacer(1, 12))
    _sig_table = _signatures_table(sigs, usable, font)
    if _sig_table is not None:
        story.append(_sig_table)
        story.append(Spacer(1, 24))
    # No footer text: the QR and share code are drawn in the page footer
    # at the bottom left (see _on_page) and the page number at the bottom
    # right, with nothing in between.
    def _on_page(canvas, _doc):
        _wm = (watermark_text or "").strip().lower() if watermark_text else ""
        # The seal and the stamps come ONLY from the invoice's status:
        # the APPROVED seal when the last step in the chain approved, the
        # grey PENDING stamp while the chain is still running, and the
        # grey REJECTED stamp as soon as any step rejects. A newly created
        # invoice shows no watermark at all. The template's watermark text
        # never makes one appear on its own. hide_watermark (the PDF
        # download without a watermark) draws nothing at all.
        if hide_watermark:
            pass
        elif is_pending:
            # The PENDING stamp (the grey rectangular stamp the user
            # supplied), at the bottom right of the page, in the empty
            # space below the signatures. It appears when the owner set
            # the invoice's status to Pending. The stamp is a wide
            # rectangle (about 3:1), drawn 7.5 cm wide.
            try:
                _seal = os.path.join(current_app.static_folder, "pending-stamp.png")
                _sw = 7.5 * cm
                _sh = _sw * 146 / 436
                canvas.drawImage(ImageReader(_seal), A4[0] - 1.4 * cm - _sw, 6.2 * cm, width=_sw, height=_sh, mask="auto")
            except Exception:
                pass
        elif is_approved:
            # The APPROVED seal (grey), at the bottom right of the page,
            # in the empty space below the signatures. It appears when the
            # last step in the chain has approved.
            try:
                _seal = os.path.join(current_app.static_folder, "approved-seal-grey.png")
                _sw = 5.5 * cm
                canvas.drawImage(ImageReader(_seal), A4[0] - 1.4 * cm - _sw, 6.2 * cm, width=_sw, height=_sw, mask="auto")
            except Exception:
                pass
        elif is_rejected:
            # The REJECTED stamp (grey), at the bottom right of the page,
            # in the empty space below the signatures. It appears as soon
            # as any step in the chain rejects. The stamp is a wide
            # rectangle (612x369), drawn 7.5 cm wide like the PENDING stamp.
            try:
                _seal = os.path.join(current_app.static_folder, "rejected-stamp-grey.png")
                _sw = 7.5 * cm
                _sh = _sw * 369 / 612
                canvas.drawImage(ImageReader(_seal), A4[0] - 1.4 * cm - _sw, 6.2 * cm, width=_sw, height=_sh, mask="auto")
            except Exception:
                pass
        elif watermark_on and watermark_text and _wm not in ("approved", "pending"):
            # Any other watermark text keeps the old diagonal rendering.
            canvas.saveState()
            try:
                canvas.setFillAlpha(0.08)
            except Exception:
                pass
            canvas.setFillColor(colors.HexColor("#1E8A5A"))
            canvas.setFont(font["bold"], 90)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(30)
            canvas.drawCentredString(0, 0, watermark_text)
            canvas.restoreState()
        canvas.saveState(); canvas.setFont(font["regular"], 8); canvas.setFillColor(colors.HexColor("#506A7B"))
        canvas.drawRightString(A4[0] - 1.4 * cm, 0.8 * cm, f"Page {canvas.getPageNumber()}")
        if code:
            canvas.setFont(font["bold"], 9); canvas.setFillColor(colors.HexColor("#10283A"))
            canvas.drawString(1.4 * cm, 0.8 * cm, f"Share code: {code}")
            # Smaller QR (1.9 cm, was 2.8 cm), directly on top of the
            # share code, at the bottom left corner of the page.
            if qr_url:
                try:
                    _q = io.BytesIO()
                    _segno.make(qr_url, error="m").save(_q, kind="png", scale=4, border=1)
                    _q.seek(0)
                    canvas.drawImage(ImageReader(_q), 1.4 * cm, 1.25 * cm, width=1.9 * cm, height=1.9 * cm, mask="auto")
                except Exception:
                    pass
        canvas.restoreState()
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()


def request_pdf(meta_left, meta_right, cols, rows, totals, words, terms, sigs, code, company="",
                company_address="", show_address=True, logo_left=None, logo_right=None, qr_url="",
                is_approved=False, is_rejected=False, hide_watermark=False):
    """Item Request PDF, layout v5 (same header as the invoice, approved in
    invoice-format-v5.jpg): top row: left logo + company name and address
    CENTRED in the middle, right second logo in the top right corner (the
    portal logo when the kind has no right logo, so there are always two
    logos on the two top corners). Then meta, one field per line:
    "Request No. - REQ-0003", then Requested by, Department and Requested
    to under it; Date and Status on the right, also one line each. Then
    the CENTRED "Item Request" title, then the table.
    The kind name is NOT shown on the document at all — the document is
    just "Item Request". Currency is beside every amount (the caller
    formats amounts as '3,500.00 BDT'). Signatures are aligned by count
    (see _signatures_table): 1 at the left, 2 at the left and right, 3 at
    left, centre and right, 4 spread evenly; the title, name and
    designation stay centred in respect to the name inside each block.
    There are as many as the dept admin set on the kind.
    No footer text between the QR and the page number. The QR (1.9 cm)
    and share code stay at the bottom left of every page, with the page
    number at the bottom right. The QR encodes qr_url (the portal's real
    address); the old https://portal host is never used."""
    import segno as _segno
    font = _fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.4 * cm, rightMargin=1.4 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.4 * cm, title="Item Request")
    accent = colors.HexColor("#0B6E99")
    small = ParagraphStyle("cell", fontName=font["regular"], fontSize=9, leading=12)
    head = ParagraphStyle("head", fontName=font["bold"], fontSize=9, leading=12, textColor=colors.white)
    h1 = ParagraphStyle("h1", fontName=font["bold"], fontSize=22, textColor=accent, leading=26, alignment=1)
    meta_s = ParagraphStyle("meta", fontName=font["regular"], fontSize=8.5, textColor=colors.HexColor("#506A7B"), leading=11)
    meta_b = ParagraphStyle("metab", fontName=font["bold"], fontSize=10, textColor=colors.HexColor("#10283A"), leading=13)
    meta_r = ParagraphStyle("metar", fontName=font["regular"], fontSize=8.5, textColor=colors.HexColor("#506A7B"), leading=11, alignment=2)
    story = []
    # top row: left logo + company, centred title, right logo
    def _img(path, w=2.6 * cm, h=1.6 * cm):
        try:
            return Image(path, width=w, height=h, kind="proportional")
        except Exception:
            return ""
    default_logo = custom_logo_path() or os.path.join(current_app.static_folder, "logo.png")
    left_logo = _img(logo_left) if logo_left else _img(default_logo)
    # Two logos on the two top corners: when the kind has no right logo, the
    # portal logo fills the right corner too (as in the approved JPG).
    right_logo = _img(logo_right, w=2.2 * cm, h=1.4 * cm) if logo_right else _img(default_logo, w=2.2 * cm, h=1.4 * cm)
    # Top row: left logo + company name and address CENTRED in the middle,
    # right second logo in the top right corner.
    if show_address and company_address:
        company_para = Paragraph(f"<b>{_pdf_text(company)}</b><br/><font color='#506A7B'>{_pdf_text(company_address)}</font>",
                                 ParagraphStyle("comp", fontName=font["bold"], fontSize=11, leading=14, alignment=1))
    else:
        company_para = Paragraph(f"<b>{_pdf_text(company)}</b>",
                                 ParagraphStyle("comp", fontName=font["bold"], fontSize=11, leading=14, alignment=1))
    banner = Table([[left_logo, company_para, right_logo]], colWidths=[3 * cm, None, 3 * cm],
                   style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, 0), 1.5, accent)])
    story += [banner, Spacer(1, 10)]
    # meta: one field per line — "Request No. - REQ-0003", then
    # Requested by, Department and Requested to under it; Date and Status
    # on the right, also one line each.
    def _meta_table(pairs, style, width=9 * cm):
        _lab_map = {"REQUEST NO.": "Request No.", "DATE": "Date", "STATUS": "Status"}
        _rows = [[Paragraph(f"<font color='#506A7B'>{_pdf_text(_lab_map.get(lab, lab))} -</font> <font size='10'><b>{_pdf_text(val)}</b></font>", style)] for lab, val in pairs]
        return Table(_rows, colWidths=[width],
                     style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)])
    story.append(Table([[_meta_table(meta_left, meta_s), _meta_table(meta_right, meta_r, 5 * cm)]],
                       colWidths=[None, 5 * cm], style=[("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(Spacer(1, 12))
    story += [Paragraph("Item Request", h1), Spacer(1, 10)]
    # table — Item name and Description get the most room; # and Qty the least.
    usable = A4[0] - 2.8 * cm
    data = [[Paragraph(_pdf_text(h), head) for h in cols]]
    data += [[Paragraph(_pdf_text(v), small) for v in row] for row in rows] or [[Paragraph("No items.", small)]]
    _w = {"#": 0.6, "Item name": 2.6, "Description": 3.2, "Qty": 0.9, "Quantity": 0.9, "Rate": 2.0, "Amount": 2.2}
    _weights = [_w.get(h, 1.0) for h in cols]
    _tot = sum(_weights) or 1.0
    table = Table(data, colWidths=[usable * w / _tot for w in _weights], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), accent), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F7FA")]),
                               ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D3DBE0")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    story += [table, Spacer(1, 10)]
    # totals, right aligned
    tot_data = [[Paragraph(_pdf_text(lab), small), Paragraph(_pdf_text(val), ParagraphStyle("tot", fontName=font["bold"], fontSize=10, leading=13, alignment=2))] for lab, val in totals]
    story.append(Table(tot_data, colWidths=[usable - 5 * cm, 5 * cm], style=[("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EFF4F8")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(Spacer(1, 10))
    if words:
        story.append(Table([[Paragraph(_pdf_text("In words: " + words), small)]], colWidths=[usable], style=[("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F6F9")), ("LINEBEFORE", (0, 0), (0, 0), 3, accent)]))
        story.append(Spacer(1, 8))
    if terms:
        story.append(Paragraph(_pdf_text("Terms: " + terms), small))
    # Signatures, aligned by count (see _signatures_table): 1 at the
    # left, 2 at the left and right, 3 at left, centre and right, 4 spread
    # evenly. The title, name and designation stay centred in respect to
    # the name inside each block. There are as many as the dept admin set
    # on the kind.
    story.append(Spacer(1, 12))
    _sig_table = _signatures_table(sigs, usable, font)
    if _sig_table is not None:
        story.append(_sig_table)
        story.append(Spacer(1, 24))
    # No footer text: the QR and share code are drawn in the page footer
    # at the bottom left (see _on_page) and the page number at the bottom
    # right, with nothing in between.
    def _on_page(canvas, _doc):
        # The watermark comes ONLY from the request's status: the grey
        # APPROVED seal when the last step in the chain approved, and the
        # grey REJECTED stamp as soon as any step rejects. Requests never
        # had a watermark before this build. hide_watermark (the PDF
        # download without a watermark) draws nothing at all.
        if not hide_watermark:
            if is_approved:
                try:
                    _seal = os.path.join(current_app.static_folder, "approved-seal-grey.png")
                    _sw = 5.5 * cm
                    canvas.drawImage(ImageReader(_seal), A4[0] - 1.4 * cm - _sw, 6.2 * cm, width=_sw, height=_sw, mask="auto")
                except Exception:
                    pass
            elif is_rejected:
                try:
                    _seal = os.path.join(current_app.static_folder, "rejected-stamp-grey.png")
                    _sw = 7.5 * cm
                    _sh = _sw * 369 / 612
                    canvas.drawImage(ImageReader(_seal), A4[0] - 1.4 * cm - _sw, 6.2 * cm, width=_sw, height=_sh, mask="auto")
                except Exception:
                    pass
        canvas.saveState(); canvas.setFont(font["regular"], 8); canvas.setFillColor(colors.HexColor("#506A7B"))
        canvas.drawRightString(A4[0] - 1.4 * cm, 0.8 * cm, f"Page {canvas.getPageNumber()}")
        if code:
            canvas.setFont(font["bold"], 9); canvas.setFillColor(colors.HexColor("#10283A"))
            canvas.drawString(1.4 * cm, 0.8 * cm, f"Share code: {code}")
            # Smaller QR (1.9 cm), directly on top of the share code, at
            # the bottom left corner of the page.
            if qr_url:
                try:
                    _q = io.BytesIO()
                    _segno.make(qr_url, error="m").save(_q, kind="png", scale=4, border=1)
                    _q.seek(0)
                    canvas.drawImage(ImageReader(_q), 1.4 * cm, 1.25 * cm, width=1.9 * cm, height=1.9 * cm, mask="auto")
                except Exception:
                    pass
        canvas.restoreState()
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()


_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"]

def _long_date(iso):
    """YYYY-MM-DD -> '16 November 2026' for the formal letter."""
    try:
        y, m, d = [int(p) for p in (iso or "").split("-")]
        return f"{d} {_MONTHS[m - 1]} {y}"
    except Exception:
        return iso or ""

def _times_text(value):
    """Escape for a Times (WinAnsi) paragraph: keep only characters the
    font can print, escape HTML, and turn newlines into line breaks."""
    text = "" if value is None else str(value)
    out = []
    for ch in text:
        try:
            ch.encode("cp1252")
            out.append(ch)
        except Exception:
            out.append("?")
    text = "".join(out)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def application_pdf(number="", app_date="", kind_name="", status="", status_label="", owner_name="",
                    owner_designation="", dept_name="", checker_name="", checker_designation="",
                    checker_signature_path=None, recipient_name="", from_date="", to_date="",
                    days=0, reason="", letter_body="", hr_note="", signer_name="", signer_designation="",
                    signature_path=None, signature_date="", code="", company="", company_address="",
                    qr_url="", logo_left=None, logo_right=None, to_lines="", sig_blocks=None, subject=""):
    """Application Letter PDF — a FORMAL application letter, not an invoice
    (approved in leave-application-pdf-formal.jpg). A plain centred
    letterhead (company name and address, one thin rule, no logos, no teal),
    Ref on the left and the date on the right, then To (only the lines the
    user wrote in the To box — nothing is filled in automatically, so by
    default nothing appears under "To,"), Subject, the body, and the
    applicant's signature (name, designation, department, company). The
    body ends with the "Thanking you. Yours faithfully," closing — the
    user wrote it, or the leave form filled it in — so the letter adds no
    closing of its own and the user can change it. A Custom Application
    is different: the user writes the subject and the whole body
    themself, so the letter adds no "Respected Sir," opening either.
    Then a FOR OFFICE USE section with the HR note
    and one signature block per step in the approval chain — the step's
    saved signature image above their name and designation — laid out by
    count the same way as the invoice and item request signatures (1 at
    the left, 2 left and right, 3 left/centre/right, 4 across). There is
    no separate Status or Date line at the bottom: the status is shown by
    the watermark — the grey APPROVED seal when the last step approved,
    the grey REJECTED stamp as soon as any step rejects, and no watermark
    when the application is still waiting or only an earlier step has
    approved. The body is set in Times (serif), like a typed formal
    letter. The QR (1.9 cm) and share code stay at the bottom left of
    every page, with the page number at the bottom right, the same as the
    other portal documents."""
    import segno as _segno
    font = _fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.4 * cm, title="Application Letter")
    serif = "Times-Roman"
    serif_b = "Times-Bold"
    head_name = ParagraphStyle("ahead", fontName=serif_b, fontSize=17, leading=20, alignment=1)
    head_addr = ParagraphStyle("aaddr", fontName=serif, fontSize=10.5, leading=13, alignment=1,
                               textColor=colors.HexColor("#444444"))
    ref = ParagraphStyle("aref", fontName=serif, fontSize=11.5, leading=15)
    ref_r = ParagraphStyle("arefr", fontName=serif, fontSize=11.5, leading=15, alignment=2)
    body_s = ParagraphStyle("abody", fontName=serif, fontSize=12, leading=20, alignment=4)
    plain = ParagraphStyle("aplain", fontName=serif, fontSize=12, leading=20)
    sig_name = ParagraphStyle("asign", fontName=serif_b, fontSize=12, leading=16)
    sig_line = ParagraphStyle("asigl", fontName=serif, fontSize=12, leading=16)
    office_h = ParagraphStyle("aoffh", fontName=serif_b, fontSize=11, leading=14,
                              textColor=colors.HexColor("#444444"))
    note_s = ParagraphStyle("anote", fontName=serif, fontSize=11, leading=17)
    story = []
    # Letterhead: company name and address, centred, one thin rule. The
    # kind may carry a logo for the top left corner and one for the top
    # right corner (2026-11-14); a corner with no logo stays blank, and
    # the company name stays centred in the middle.
    def _logo_img(path):
        if not path:
            return ""
        try:
            return Image(path, width=2.6 * cm, height=1.6 * cm, kind="proportional")
        except Exception:
            return ""
    _mid_w = A4[0] - 3.6 * cm - 6 * cm
    text_head = Table([[Paragraph(_times_text(company), head_name)],
                       [Paragraph(_times_text(company_address), head_addr)]],
                      colWidths=[_mid_w],
                      style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                             ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)])
    head = Table([[_logo_img(logo_left), text_head, _logo_img(logo_right)]],
                 colWidths=[3 * cm, _mid_w, 3 * cm],
                 style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LINEBELOW", (0, -1), (-1, -1), 1.2, colors.HexColor("#1A1A1A"))])
    story += [head, Spacer(1, 14)]
    # Ref on the left, date on the right.
    story.append(Table([[Paragraph(_times_text("Ref: " + number) if number else "", ref),
                         Paragraph(_times_text(_long_date(app_date)), ref_r)]],
                       colWidths=[(A4[0] - 3.6 * cm) / 2, (A4[0] - 3.6 * cm) / 2],
                       style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                              ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                              ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(Spacer(1, 16))
    # To: ONLY the lines the user wrote in the To box (2026-11-14). By
    # default there is nothing under "To," — the checker, the department
    # and the company are no longer filled in automatically.
    _to = ["To,"] + [_times_text(l) for l in (to_lines or "").split("\n") if l.strip()]
    story.append(Paragraph("<br/>".join(_to), plain))
    story.append(Spacer(1, 12))
    # Subject: kind, days and dates. The kind name stands on its own
    # ("Leave Application for 2 days ...") — no "Application for" in
    # front of it, or a kind called "Leave Application" reads twice.
    # A Custom Application shows the subject the user wrote instead.
    day_word = "day" if days == 1 else "days"
    _subj = (subject or "").strip()
    if _subj:
        if _subj[-1] not in ".!?":
            _subj += "."
        story.append(Paragraph(f"<b>Subject:</b> {_times_text(_subj)}", plain))
    else:
        _subj = (f"{kind_name} for {days} {day_word} "
                 f"({_long_date(from_date)} \u2013 {_long_date(to_date)}).")
        story.append(Paragraph(f"<b>Subject:</b> {_times_text(_subj)}", plain))
    story.append(Spacer(1, 12))
    # Salutation, then the body paragraphs (blank line = new paragraph).
    # A Custom Application is written entirely by the user, so the
    # letter does not add its own "Respected Sir," — the user writes
    # the opening themself if they want one.
    if not (subject or "").strip():
        story.append(Paragraph("Respected Sir,", plain))
        story.append(Spacer(1, 10))
    for para in (letter_body or "").split("\n"):
        para = para.strip()
        if para:
            story.append(Paragraph(_times_text(para), body_s))
            story.append(Spacer(1, 8))
    # The applicant's signature: name, designation, department, company.
    # The letter adds no closing of its own — "Thanking you. Yours
    # faithfully," is part of the body the user wrote (or the leave form
    # filled in), so the user can change it (2026-11-14).
    story.append(Spacer(1, 28))
    sig_rows = []
    if owner_name:
        sig_rows.append([Paragraph(_times_text(owner_name), sig_name)])
    if owner_designation:
        sig_rows.append([Paragraph(_times_text(owner_designation), sig_line)])
    if dept_name:
        sig_rows.append([Paragraph(_times_text(dept_name), sig_line)])
    if company:
        sig_rows.append([Paragraph(_times_text(company), sig_line)])
    if sig_rows:
        story.append(Table(sig_rows, colWidths=[A4[0] - 3.6 * cm],
                           style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                  ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    # FOR OFFICE USE: the HR note, then the signature blocks side by
    # side — Checked By (the checker's signature image above their name
    # and designation) and Approved By (the HR approver's signature image
    # above their name and designation). The blocks are laid out by count
    # the same way as the invoice and item request signatures. There is
    # no separate Status or Date line: the status is shown by the
    # watermark (the APPROVED seal or the REJECTED stamp).
    story.append(Spacer(1, 30))
    office = []
    office.append([Paragraph("FOR OFFICE USE", office_h)])
    if hr_note:
        who = signer_name or recipient_name
        office.append([Paragraph(f"<b>HR note \u2014 {_times_text(who)}:</b> {_times_text(hr_note)}", note_s)])
    # One block per step in the chain (sig_blocks, when given); without
    # them, the old two blocks — Checked By and Approved By.
    if sig_blocks is not None:
        _sig_blocks = list(sig_blocks)
    else:
        _sig_blocks = []
        _sig_blocks.append((checker_signature_path, "Checked By",
                            checker_name or "", checker_designation or "", ""))
        _sig_blocks.append((signature_path, "Approved By",
                            signer_name or "", signer_designation or "", ""))
    _sig_table = _application_sig_table(_sig_blocks, A4[0] - 3.6 * cm)
    if _sig_table is not None:
        office.append([_sig_table])
    office_table = Table(office, colWidths=[A4[0] - 3.6 * cm],
                         style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                                ("LINEABOVE", (0, 0), (-1, 0), 1.2, colors.HexColor("#1A1A1A"))])
    story.append(office_table)
    # Footer: QR + share code bottom left, Page N bottom right (same as the
    # other portal documents). The watermark comes from the status the
    # caller passes: the grey APPROVED seal when the last step approved,
    # the grey REJECTED stamp when the last step rejected. A pending,
    # checked or earlier-rejected application shows no watermark.
    # The seal and the stamp are drawn at the same size (5.5 cm) and the
    # same place (right side, 10 cm up from the bottom), in the blank
    # space beside the applicant's signature and above FOR OFFICE USE,
    # so the stamp never reaches as far left as the approver's
    # signature block. onPage is drawn before the letter content, so
    # the watermark sits behind the signature blocks instead of on
    # top of them.
    def _on_page(canvas, _doc):
        canvas.saveState(); canvas.setFont(font["regular"], 8); canvas.setFillColor(colors.HexColor("#506A7B"))
        canvas.drawRightString(A4[0] - 1.4 * cm, 0.8 * cm, f"Page {canvas.getPageNumber()}")
        if status == "approved":
            try:
                _seal = os.path.join(current_app.static_folder, "approved-seal-grey.png")
                _sw = 5.5 * cm
                canvas.drawImage(ImageReader(_seal), A4[0] - 1.4 * cm - _sw, 10 * cm, width=_sw, height=_sw, mask="auto")
            except Exception:
                pass
        elif status == "rejected":
            try:
                _stamp = os.path.join(current_app.static_folder, "rejected-stamp-grey.png")
                _sw = 5.5 * cm
                _sh = _sw * 369 / 612
                canvas.drawImage(ImageReader(_stamp), A4[0] - 1.4 * cm - _sw, 10 * cm, width=_sw, height=_sh, mask="auto")
            except Exception:
                pass
        if code:
            canvas.setFont(font["bold"], 9); canvas.setFillColor(colors.HexColor("#10283A"))
            canvas.drawString(1.4 * cm, 0.8 * cm, f"Share code: {code}")
            if qr_url:
                try:
                    _q = io.BytesIO()
                    _segno.make(qr_url, error="m").save(_q, kind="png", scale=4, border=1)
                    _q.seek(0)
                    canvas.drawImage(ImageReader(_q), 1.4 * cm, 1.25 * cm, width=1.9 * cm, height=1.9 * cm, mask="auto")
                except Exception:
                    pass
        canvas.restoreState()
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()
