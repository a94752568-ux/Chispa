"""Neon Nexus × Akira — central theme tokens and Qt palette.

The theme layer centralizes app-wide colors and supports persisted dark/light
selection. Component-specific QSS can progressively migrate to these tokens.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES = {
    "dark": {
        "name": "Neon Nexus · Dark",
        "window": "#11151C",
        "surface": "#171B23",
        "surface_elevated": "#202631",
        "surface_hover": "#293241",
        "border": "#303947",
        "text": "#E8EDF5",
        "muted": "#9AA8BA",
        "accent": "#32D9F5",
        "accent_hover": "#78E8FA",
        "danger": "#F04452",
        "selection": "#174B59",
        "code": "#0C1016",
    },
    "light": {
        "name": "Neon Nexus · Light",
        "window": "#F2F4F7",
        "surface": "#FFFFFF",
        "surface_elevated": "#E8EDF3",
        "surface_hover": "#DDE5EE",
        "border": "#CAD3DF",
        "text": "#18202B",
        "muted": "#596575",
        "accent": "#087F98",
        "accent_hover": "#056779",
        "danger": "#C92738",
        "selection": "#BDECF4",
        "code": "#E9EEF4",
    },
}


def palette_for(theme: str = "dark") -> QPalette:
    """Return a Fusion-compatible palette for the requested theme."""
    colors = THEMES.get(theme, THEMES["dark"])
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(colors["window"]))
    palette.setColor(QPalette.WindowText, QColor(colors["text"]))
    palette.setColor(QPalette.Base, QColor(colors["surface"]))
    palette.setColor(QPalette.AlternateBase, QColor(colors["surface_elevated"]))
    palette.setColor(QPalette.ToolTipBase, QColor(colors["surface_elevated"]))
    palette.setColor(QPalette.ToolTipText, QColor(colors["text"]))
    palette.setColor(QPalette.Text, QColor(colors["text"]))
    palette.setColor(QPalette.Button, QColor(colors["surface_elevated"]))
    palette.setColor(QPalette.ButtonText, QColor(colors["text"]))
    palette.setColor(QPalette.BrightText, QColor(colors["danger"]))
    palette.setColor(QPalette.Link, QColor(colors["accent"]))
    palette.setColor(QPalette.Highlight, QColor(colors["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor(colors["window"]))
    return palette


def app_stylesheet(theme: str = "dark") -> str:
    """App-wide baseline QSS; specialized widgets may layer their own styling."""
    c = THEMES.get(theme, THEMES["dark"])
    return f"""
        QWidget {{ color: {c['text']}; }}
        QToolTip {{
            background: {c['surface_elevated']};
            color: {c['text']};
            border: 1px solid {c['border']};
            padding: 5px 8px;
        }}
        QMenu {{
            background: {c['surface_elevated']};
            color: {c['text']};
            border: 1px solid {c['border']};
            padding: 5px;
        }}
        QMenu::item {{ padding: 6px 24px; border-radius: 5px; }}
        QMenu::item:selected {{ background: {c['selection']}; }}
        QScrollBar:vertical {{
            background: transparent; width: 9px; margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            background: {c['border']}; min-height: 28px; border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {c['accent']}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar:horizontal {{
            background: transparent; height: 9px; margin: 2px;
        }}
        QScrollBar::handle:horizontal {{
            background: {c['border']}; min-width: 28px; border-radius: 4px;
        }}
    """


def apply_theme(app: QApplication, theme: str = "dark") -> str:
    """Apply a named theme to QApplication and return its normalized key."""
    normalized = theme if theme in THEMES else "dark"
    app.setPalette(palette_for(normalized))
    app.setStyleSheet(app_stylesheet(normalized))
    return normalized
