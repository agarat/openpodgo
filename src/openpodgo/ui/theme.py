"""Tema oscuro calcado de POD Go Edit (fondo #18191b + Roboto oficial)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from . import assets
from .palette import BACKGROUND

import os

def make_qss(scale: float = 1.0) -> str:
    base = max(10, round(13 * scale))
    title = max(12, round(17 * scale))
    hint = max(9, round(11 * scale))
    return f"""
QWidget {{ background: {BACKGROUND}; color: #e6e6e6; font-size: {base}px; }}
QLabel#title {{ font-size: {title}px; font-weight: 600; color: #ffffff; }}
QLabel#hint {{ color: #8a8f98; font-size: {hint}px; }}
QSplitter::handle {{ background: #232529; width: 2px; }}
QListWidget#presetList {{
    background: #1d1f23; border: 1px solid #2a2d31; border-radius: 6px;
    padding: 2px; font-size: {base}px;
}}
QListWidget#presetList::item {{ padding: 4px 8px; border-radius: 3px; }}
QListWidget#presetList::item:selected {{ background: #3a3f47; color: #ffffff; }}
QListWidget#presetList::item:hover {{ background: #26292e; }}
QListWidget {{ background: #1d1f23; border: none; }}
QPushButton {{
    background: #2a2d31; border: 1px solid #383c42; border-radius: 5px;
    padding: 5px 12px;
}}
QPushButton:hover {{ background: #383c42; }}
QPushButton:disabled {{ color: #6b7078; }}
QToolButton {{ border: none; padding: 2px; }}
QToolButton:hover {{ background: #2a2d31; border-radius: 4px; }}
QToolButton:disabled {{ color: #5a5f66; }}
QDoubleSpinBox {{
    background: #232529; border: 1px solid #383c42; border-radius: 4px;
    padding: 1px 2px; color: #ffffff;
}}
QLineEdit {{
    background: #232529; border: 1px solid #383c42; border-radius: 4px;
    padding: 3px 6px;
}}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{
    background: {BACKGROUND}; width: 10px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #383c42; border-radius: 5px; min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QMenu {{ background: #232529; border: 1px solid #383c42; }}
QMenu::item:selected {{ background: #3a3f47; }}
QStatusBar {{ background: #131416; color: #9aa0a8; }}
QMenuBar {{ background: #131416; }}
QMenuBar::item:selected {{ background: #2a2d31; }}
"""


def apply_dark_theme(app: QApplication, font_scale: float | None = None) -> None:
    if font_scale is None:
        try:
            font_scale = float(os.environ.get("PODGO_FONT_SCALE", "1.0"))
        except ValueError:
            font_scale = 1.0

    app.setStyle("Fusion")
    families = assets.load_fonts()
    roboto = next((f for f in families if f == "Roboto"), None)
    pt_size = max(8, round(10 * font_scale))
    if roboto:
        app.setFont(QFont(roboto, pt_size))
    else:
        f = app.font()
        f.setPointSize(pt_size)
        app.setFont(f)

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BACKGROUND))
    pal.setColor(QPalette.Base, QColor("#1d1f23"))
    pal.setColor(QPalette.Text, QColor("#e6e6e6"))
    pal.setColor(QPalette.WindowText, QColor("#e6e6e6"))
    pal.setColor(QPalette.Button, QColor("#2a2d31"))
    pal.setColor(QPalette.ButtonText, QColor("#e6e6e6"))
    pal.setColor(QPalette.Highlight, QColor("#3a3f47"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(pal)
    app.setStyleSheet(make_qss(font_scale))
