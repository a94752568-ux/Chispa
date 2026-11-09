#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""theme.py — Paleta centralizada de la GUI (look "Vibe").

Un único lugar de verdad para colores y QSS global. El acento es el
naranja cálido estilo Mistral/Vibe sobre fondos casi negros; el resto
de los módulos solo importa constantes de aquí.
"""

# ---------------------------------------------------------------- Paleta
ACCENT          = "#FF7000"   # naranja cálido (acentos primarios)
ACCENT_HOVER    = "#FF8A33"
ACCENT_ACTIVE   = "#E56200"
ACCENT_TINT     = "#3A281B"   # naranja apagado (burbuja de usuario)
ACCENT_BORDER   = "#56361D"

BG_WINDOW       = "#0E0E10"   # fondo del chat / ventana
BG_SIDEBAR      = "#141517"   # sidebar y headers
BG_TITLEBAR     = "#111114"
BG_ELEVATED     = "#1A1B1F"   # tarjetas, grupos, composer
BG_INPUT        = "#1F2024"   # campos de texto y listas

BORDER          = "#26262C"
BORDER_SOFT     = "#1E1E23"

TEXT            = "#EDEDEF"
TEXT_SECOND     = "#A6A6B0"
TEXT_MUTED      = "#67676F"
TEXT_ON_ACCENT  = "#1A0E00"   # texto sobre naranja (contraste alto)

SUCCESS         = "#35C77B"
ERROR           = "#FF5F5F"
WARNING         = "#FFB020"

LINK            = "#FF9D57"   # enlaces en markdown

FONT_STACK      = '"Inter", "Noto Sans", "Ubuntu", sans-serif'


def app_qss() -> str:
    """QSS global: scrollbars delgados, tooltips, menús y diálogos."""
    return f"""
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER};
        border-radius: 5px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {TEXT_MUTED}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {BORDER};
        border-radius: 5px;
        min-width: 30px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    QToolTip {{
        background: {BG_ELEVATED};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 8px;
        font-size: 12px;
    }}

    QMessageBox {{
        background: {BG_ELEVATED};
        color: {TEXT};
    }}
    QMessageBox QLabel {{
        color: {TEXT};
        font-size: 13px;
    }}
    QMessageBox QPushButton {{
        background: {ACCENT};
        color: {TEXT_ON_ACCENT};
        font-weight: bold;
        border: none;
        border-radius: 8px;
        padding: 8px 18px;
        font-size: 12px;
    }}
    QMessageBox QPushButton:hover {{ background: {ACCENT_HOVER}; }}

    QMenu {{
        background: {BG_ELEVATED};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 7px 24px 7px 12px;
        border-radius: 6px;
        font-size: 12px;
    }}
    QMenu::item:selected {{
        background: {ACCENT_TINT};
        color: {TEXT};
    }}
    """
