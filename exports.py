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

    _blocks = [_block(t, n, d) for t, n, d in sigs]
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


# ------------------------------------------------------------------ Invoice PDF (v4 layout)
def invoice_pdf(title, subtitle, meta, bill_to, kind, colour, cols, rows, totals, words, terms, sigs, code, company="",
                company_address="", show_address=True,
                logo_left=None, logo_right=None, watermark_on=False, watermark_text="", qr_url="", is_approved=False, is_pending=False):
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
        # The seal and the stamp come ONLY from the invoice's status.
        # A newly created invoice shows no watermark at all; the seal
        # appears when the owner marks it Approved and the stamp when
        # the owner marks it Pending. The template's watermark text
        # never makes one appear on its own.
        if is_pending:
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
            # owner set the invoice's status to Approved.
            try:
                _seal = os.path.join(current_app.static_folder, "approved-seal-grey.png")
                _sw = 5.5 * cm
                canvas.drawImage(ImageReader(_seal), A4[0] - 1.4 * cm - _sw, 6.2 * cm, width=_sw, height=_sw, mask="auto")
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
                company_address="", show_address=True, logo_left=None, logo_right=None, qr_url=""):
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
