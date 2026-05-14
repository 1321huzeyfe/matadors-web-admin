# -*- coding: utf-8 -*-

def money(value: float) -> str:
    return f"{value:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def write_report_pdf(file_path: str, lines: list[str]):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from services.pdf_fonts import get_pdf_fonts

    pdf = canvas.Canvas(file_path, pagesize=A4)
    regular_font, bold_font, _italic_font = get_pdf_fonts()
    _, height = A4
    y = height - 40
    pdf.setFont(bold_font, 14)
    pdf.drawString(40, y, lines[0][:120])
    y -= 24
    pdf.setFont(regular_font, 10)
    for line in lines[1:]:
        pdf.drawString(40, y, line[:130])
        y -= 14
        if y < 40:
            pdf.showPage()
            pdf.setFont(regular_font, 10)
            y = height - 40
    pdf.save()
