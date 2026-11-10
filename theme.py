#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""theme.py — Paleta centralizada de la GUI (look "Vibe" premium).

Un único lugar de verdad para colores y QSS global. El acento es el
naranja cálido estilo Mistral/Vibe sobre fondos casi negros; el resto
de los módulos solo importa constantes de aquí.

Acabado premium: tokens extra (hover, bordes fuertes, glow RGBA),
scrollbars finos redondeados con hover naranja, menús con barra de
acento, tooltips pulidos y selección de texto con tinte.
"""

# ---------------------------------------------------------------- Paleta
ACCENT          = "#FF7000"   # naranja cálido (acentos primarios)
ACCENT_HOVER    = "#FF8A33"
ACCENT_ACTIVE   = "#E56200"
ACCENT_BRIGHT   = "#FFA052"   # tope de gradiente en hover premium
ACCENT_TINT     = "#3A281B"   # naranja apagado (burbuja de usuario)
ACCENT_BORDER   = "#56361D"

BG_WINDOW       = "#0E0E10"   # fondo del chat / ventana
BG_SIDEBAR      = "#141517"   # sidebar y headers
BG_TITLEBAR     = "#111114"
BG_ELEVATED     = "#1A1B1F"   # tarjetas, grupos, composer
BG_INPUT        = "#1F2024"   # campos de texto y listas
BG_HOVER        = "#24252B"   # hover de filas y botones fantasma

BORDER          = "#26262C"
BORDER_SOFT     = "#1E1E23"
BORDER_STRONG   = "#32333B"

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
    """QSS global premium: scrollbars finos, focus, menús y diálogos."""
    return f"""
    /* ---------- Scrollbars finos y redondeados ---------- */
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER};
        border-radius: 4px;
        min-height: 36px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(255, 112, 0, 0.55);
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {BORDER};
        border-radius: 4px;
        min-width: 36px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: rgba(255, 112, 0, 0.55);
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

    /* ---------- Selección de texto con tinte naranja ---------- */
    QLineEdit, QTextEdit, QPlainTextEdit, QTextBrowser {{
        selection-background-color: rgba(255, 112, 0, 0.45);
        selection-color: #FFFFFF;
    }}

    /* ---------- Tooltips pulidos ---------- */
    QToolTip {{
        background: {BG_ELEVATED};
        color: {TEXT};
        border: 1px solid {BORDER_STRONG};
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 12px;
    }}

    /* ---------- Diálogos ---------- */
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
    QMessageBox QPushButton:pressed {{ background: {ACCENT_ACTIVE}; }}

    QDialog {{ background: {BG_WINDOW}; }}

    /* ---------- Menús contextuales con barra de acento ---------- */
    QMenu {{
        background: {BG_ELEVATED};
        color: {TEXT};
        border: 1px solid {BORDER_STRONG};
        border-radius: 10px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 7px 24px 7px 12px;
        border-radius: 6px;
        font-size: 12px;
        border-left: 2px solid transparent;
    }}
    QMenu::item:selected {{
        background: {ACCENT_TINT};
        color: {TEXT};
        border-left: 2px solid {ACCENT};
    }}
    QMenu::item:disabled {{ color: {TEXT_MUTED}; }}
    QMenu::separator {{
        height: 1px;
        background: {BORDER};
        margin: 5px 8px;
    }}

    /* ---------- Desplegable de combos ---------- */
    QComboBox QAbstractItemView {{
        background: {BG_ELEVATED};
        border: 1px solid {BORDER_STRONG};
        border-radius: 8px;
        padding: 4px;
        selection-background-color: {ACCENT_TINT};
        selection-color: {TEXT};
        outline: none;
    }}
    """
