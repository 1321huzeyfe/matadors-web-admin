# -*- coding: utf-8 -*-
"""ReportLab font helpers with Turkish character support."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path


def _candidate_paths(file_name: str, base_dir: str | None = None) -> list[Path]:
    roots: list[Path] = []
    if base_dir:
        roots.append(Path(base_dir))
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        roots.append(Path(sys._MEIPASS))
    roots.extend([Path.cwd(), Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"])

    candidates: list[Path] = []
    for root in roots:
        candidates.append(root / "assets" / "fonts" / file_name)
        candidates.append(root / file_name)
    return candidates


def _find_font(file_names: list[str], base_dir: str | None = None) -> str | None:
    for file_name in file_names:
        for path in _candidate_paths(file_name, base_dir):
            if path.exists():
                return str(path)
    return None


@lru_cache(maxsize=8)
def get_pdf_fonts(base_dir: str | None = None) -> tuple[str, str, str]:
    """Return registered regular, bold, and italic font names for ReportLab."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    regular_path = _find_font(["segoeui.ttf", "DejaVuSans.ttf", "arial.ttf"], base_dir)
    bold_path = _find_font(["segoeuib.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf"], base_dir)
    italic_path = _find_font(["segoeuii.ttf", "DejaVuSans-Oblique.ttf", "ariali.ttf"], base_dir)

    if not regular_path:
        return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"

    try:
        pdfmetrics.registerFont(TTFont("MatadorsRegular", regular_path))
        pdfmetrics.registerFont(TTFont("MatadorsBold", bold_path or regular_path))
        pdfmetrics.registerFont(TTFont("MatadorsItalic", italic_path or regular_path))
        return "MatadorsRegular", "MatadorsBold", "MatadorsItalic"
    except Exception:
        return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"
