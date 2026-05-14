# -*- coding: utf-8 -*-
"""Customer activity report exports for daily, weekly and monthly archives."""

from __future__ import annotations

import os
from pathlib import Path

from services.pdf_fonts import get_pdf_fonts
from services.pdf_reports import money
from safe_io import atomic_copy_file


def write_customer_activity_pdf(file_path: str, title: str, period_label: str, rows: list[dict], summary: dict, base_dir: str) -> None:
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas

    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(file_path, pagesize=landscape(A4))
    regular_font, bold_font, _italic_font = get_pdf_fonts(base_dir)
    width, height = landscape(A4)
    margin = 1.5 * cm
    red = HexColor("#990000")
    light_bg = HexColor("#F5F5F5")
    border = HexColor("#222222")

    def new_page():
        pdf.showPage()
        pdf.setFont(regular_font, 9)
        return height - margin

    y = height - margin
    pdf.setFont(bold_font, 18)
    pdf.setFillColor(red)
    pdf.drawString(margin, y, title)
    y -= 0.8 * cm

    pdf.setFont(bold_font, 11)
    pdf.setFillColor(black)
    pdf.drawString(margin, y, period_label)
    y -= 0.7 * cm

    pdf.setFont(bold_font, 12)
    pdf.drawString(margin, y, "MÜŞTERİ İŞLEM ÖZETİ")
    y -= 0.5 * cm
    pdf.setFont(regular_font, 10)
    for line in (
        f"İşlem yapan müşteri: {summary.get('customer_count', 0)} kişi",
        f"Toplam işlem: {summary.get('row_count', 0)}",
        f"POS toplamı: {money(summary.get('pos_total', 0))}",
        f"Defter harcama: {money(summary.get('spend_total', 0))}",
        f"Bakiye yükleme/tahsilat: {money(summary.get('load_total', 0))}",
    ):
        pdf.drawString(margin + 0.5 * cm, y, line)
        y -= 0.38 * cm

    y -= 0.35 * cm
    pdf.setFont(bold_font, 11)
    pdf.setFillColor(red)
    pdf.rect(margin, y - 0.4 * cm, width - 2 * margin, 0.6 * cm, fill=1, stroke=0)
    pdf.setFillColor(white)
    pdf.drawString(margin + 0.3 * cm, y - 0.15 * cm, "İŞLEM YAPAN MÜŞTERİLER")
    y -= 0.75 * cm

    headers = ["Saat", "Müşteri", "İşlem", "Açıklama / Ürün", "Tutar", "Kasa"]
    col_widths = [2.2 * cm, 4.3 * cm, 3.0 * cm, 7.6 * cm, 2.8 * cm, 3.4 * cm]
    x_positions = [margin]
    for col_width in col_widths[:-1]:
        x_positions.append(x_positions[-1] + col_width)

    def draw_table_header(current_y):
        pdf.setFillColor(light_bg)
        pdf.rect(margin, current_y - 0.4 * cm, width - 2 * margin, 0.5 * cm, fill=1, stroke=1)
        pdf.setFillColor(black)
        pdf.setFont(bold_font, 8.5)
        for x, header in zip(x_positions, headers):
            pdf.drawString(x + 0.08 * cm, current_y - 0.22 * cm, header)
        return current_y - 0.55 * cm

    y = draw_table_header(y)
    pdf.setFont(regular_font, 8)

    if not rows:
        pdf.drawString(margin + 0.2 * cm, y - 0.2 * cm, "Seçilen dönemde müşteri işlemi bulunamadı.")
    else:
        for row in rows:
            if y < margin + 1 * cm:
                y = new_page()
                y = draw_table_header(y)
                pdf.setFont(regular_font, 8)
            values = [
                str(row.get("created_at", ""))[11:16],
                str(row.get("customer_name", ""))[:28],
                str(row.get("type", ""))[:18],
                str(row.get("detail", ""))[:54],
                money(float(row.get("amount", 0) or 0)),
                str(row.get("cashier_name", ""))[:22],
            ]
            pdf.setFillColor(black)
            for x, value in zip(x_positions, values):
                pdf.drawString(x + 0.08 * cm, y - 0.22 * cm, value)
            pdf.setStrokeColor(border)
            pdf.line(margin, y - 0.34 * cm, width - margin, y - 0.34 * cm)
            y -= 0.45 * cm

    pdf.save()



def copy_report_to_drive(local_path: str, reports_dir: str, drive_root: str | None) -> str:
    if not drive_root:
        return ""
    drive = Path(drive_root)
    if not drive.exists() or not drive.is_dir():
        return ""
    local = Path(local_path)
    try:
        relative = local.relative_to(Path(reports_dir))
    except ValueError:
        relative = Path(local.name)
    target = drive / "reports" / relative
    atomic_copy_file(local, target)
    return str(target)
