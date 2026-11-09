"""Neon Nexus × Akira — central theme tokens and Qt palette.

The theme layer centralizes app-wide colors and supports persisted dark/light
selection. Component-specific QSS can progressively migrate to these tokens.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

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
        "on_accent": "#07131A",
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
        "on_accent": "#FFFFFF",
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


# Legacy component styles use these fixed colors. Re-map them from their original
# source stylesheet on every theme change, so toggling remains reversible.
LEGACY_COLOR_TOKENS = {
    "#11151c": "window",
    "#16161a": "surface",
    "#1a1a1e": "surface_elevated",
    "#000": "on_accent",
    "#1a1a1e": "surface_elevated",
    "#17181c": "surface",
    "#1a1a1c": "surface_elevated",
    "#202631": "surface_elevated",
    "#2a2a30": "border",
    "#272729": "border",
    "#2a2c31": "border",
    "#303947": "border",
    "#3a3a44": "surface_hover",
    "#3d4653": "surface_elevated",
    "#343541": "surface_hover",
    "#0a0a0b": "code",
    "#e0e0e0": "text",
    "#e5e5ea": "text",
    "#e8edf5": "text",
    "#ffffff": "text",
    "#9aa0a6": "muted",
    "#9aa8ba": "muted",
    "#888": "muted",
    "#8ab4f8": "accent",
    "#32d9f5": "accent",
    "#34c759": "accent",
    "#10a37f": "accent",
    "#ff453a": "danger",
    "#ff6b6b": "danger",
    "#f04452": "danger",
    "#174b59": "selection",
    "#1f2126": "surface_hover",
    "#4a1a1a": "selection",
    "#222228": "surface",
    "#666": "muted",
    "#a0c4ff": "accent",
    "#fff": "text",
}


def retint_widget_styles(app: QApplication, theme: str = "dark") -> None:
    """Re-color legacy per-widget QSS while preserving its original stylesheet."""
    colors = THEMES.get(theme, THEMES["dark"])
    for widget in app.allWidgets():
        current = widget.styleSheet()
        if not current:
            continue
        original = widget.property("_nova_original_stylesheet")
        last_applied = widget.property("_nova_last_applied_stylesheet")
        # A widget may update its own QSS later (e.g. tool status changes).
        # Treat that newer stylesheet as the source instead of restoring stale QSS.
        if original is None or (last_applied is not None and current != last_applied):
            original = current
            widget.setProperty("_nova_original_stylesheet", original)
        updated = original
        for source, token in LEGACY_COLOR_TOKENS.items():
            updated = updated.replace(source, colors[token])
            updated = updated.replace(source.upper(), colors[token])
        if updated != current:
            widget.setStyleSheet(updated)
        widget.setProperty("_nova_last_applied_stylesheet", updated)


def apply_theme(app: QApplication, theme: str = "dark") -> str:
    """Apply a named theme to QApplication and return its normalized key."""
    normalized = theme if theme in THEMES else "dark"
    app.setProperty("nova_theme", normalized)
    app.setPalette(palette_for(normalized))
    app.setStyleSheet(app_stylesheet(normalized))
    return normalized


def apply_component_theme(root, theme: str = "dark") -> None:
    """Apply the coordinated Neon Nexus component skin to named shell widgets."""
    c = THEMES.get(theme, THEMES["dark"])
    styles = {
        "novaSidebar": f"QFrame#novaSidebar {{ background: {c['surface']}; border-right: 1px solid {c['border']}; }}",
        "novaModelCard, #novaFunctionsCard, #novaToolsCard": "",
    }
    card = f"""
        QFrame {{ background: {c['surface_elevated']}; border: 1px solid {c['border']};
                  border-radius: 13px; }}
    """
    styles.update({
        "novaModelCard": card,
        "novaFunctionsCard": card,
        "novaToolsCard": card,
        "novaCentralPanel": f"QFrame#novaCentralPanel {{ background: {c['window']}; border: none; }}",
        "novaChatHeader": f"QFrame#novaChatHeader {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}",
        "novaComposerFrame": f"QFrame#novaComposerFrame {{ background: {c['surface']}; border-top: 1px solid {c['border']}; }}",
        "novaModelCombo": f"""
            QComboBox {{ background: {c['window']}; color: {c['text']}; border: 1px solid {c['border']};
                         border-radius: 9px; padding: 7px 10px; selection-background-color: {c['selection']}; }}
            QComboBox:hover, QComboBox:focus {{ border: 1px solid {c['accent']}; }}
            QComboBox QAbstractItemView {{ background: {c['surface_elevated']}; color: {c['text']};
                         border: 1px solid {c['border']}; selection-background-color: {c['selection']}; }}
        """,
        "novaToolsList": f"""
            QListWidget {{ background: {c['window']}; color: {c['text']}; border: 1px solid {c['border']};
                          border-radius: 9px; padding: 4px; outline: none; }}
            QListWidget::item {{ padding: 8px 9px; border: none; border-radius: 6px; }}
            QListWidget::item:hover {{ background: {c['surface_hover']}; }}
            QListWidget::item:selected {{ background: {c['selection']}; color: {c['text']}; }}
        """,
        "novaMessageInput": f"""
            QTextEdit {{ background: {c['window']}; color: {c['text']}; border: 1px solid {c['border']};
                         border-radius: 15px; padding: 10px 14px; font-size: 13px; }}
            QTextEdit:focus {{ border: 1px solid {c['accent']}; }}
        """,
        "novaNewChat": f"""
            QPushButton {{ background: {c['surface_hover']}; color: {c['text']}; border: 1px solid {c['border']};
                           border-radius: 10px; padding: 8px 12px; font-weight: 650; }}
            QPushButton:hover {{ background: {c['selection']}; border-color: {c['accent']}; }}
        """,
        "novaPullModel": f"""
            QPushButton {{ background: {c['surface_hover']}; color: {c['text']}; border: 1px solid {c['border']};
                           border-radius: 9px; padding: 6px 10px; font-weight: 600; }}
            QPushButton:hover {{ border-color: {c['accent']}; }}
        """,
        "novaAddTool": f"""
            QPushButton {{ background: {c['surface_hover']}; color: {c['text']}; border: 1px solid {c['border']};
                           border-radius: 9px; padding: 6px 10px; font-weight: 600; }}
            QPushButton:hover {{ border-color: {c['accent']}; }}
        """,
        "novaAttach": f"""
            QPushButton {{ background: {c['surface_hover']}; color: {c['text']}; border: 1px solid {c['border']};
                           border-radius: 18px; font-size: 16px; }}
            QPushButton:hover {{ background: {c['selection']}; border-color: {c['accent']}; }}
        """,
        "novaSend": f"""
            QPushButton {{ background: {c['accent']}; color: {c['on_accent']}; border: none;
                           border-radius: 10px; font-weight: 700; padding: 8px 16px; }}
            QPushButton:hover {{ background: {c['accent_hover']}; }}
            QPushButton:disabled {{ background: {c['surface_hover']}; color: {c['muted']}; }}
        """,
        "themeToggle": f"""
            QPushButton {{ background: {c['surface_elevated']}; color: {c['text']}; border: 1px solid {c['border']};
                           border-radius: 9px; padding: 5px 12px; font-weight: 600; }}
            QPushButton:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}
        """,
    })
    for name, stylesheet in styles.items():
        if not stylesheet:
            continue
        widget = root.findChild(QWidget, name)
        if widget is not None:
            widget.setStyleSheet(stylesheet)
    for name in ("novaModelTitle", "novaFunctionsTitle", "novaToolsTitle"):
        label = root.findChild(QWidget, name)
        if label is not None:
            label.setStyleSheet(
                f"color: {c['accent']}; font-size: 11px; font-weight: 700; "
                f"background: transparent; border: none; padding: 2px 0;"
            )
