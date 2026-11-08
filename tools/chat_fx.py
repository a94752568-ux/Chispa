# chat_fx.py — Animaciones de estado para el chat (≤200 ms, curva OutCubic)
# Solo se anima lo que cambia de estado: aparición, expansión, actividad.
# Nunca decorativo.

from PySide6.QtCore import QEasingCurve, QTimer, Qt, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel

CURVA = QEasingCurve.OutCubic


def fade_in(w, ms=180):
    """Aparición suave de un mensaje nuevo."""
    eff = QGraphicsOpacityEffect(w)
    w.setGraphicsEffect(eff)
    a = QPropertyAnimation(eff, b"opacity")
    a.setDuration(ms)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(CURVA)
    a.finished.connect(lambda: w.setGraphicsEffect(None))
    w._fx = a  # evitar que el GC mate la animación
    a.start()


def animate_height(w, expand, ms=140):
    """Colapso/expansión sin salto: anima maximumHeight."""
    w.setVisible(True)
    a = QPropertyAnimation(w, b"maximumHeight")
    a.setDuration(ms)
    a.setEasingCurve(CURVA)
    if expand:
        a.setStartValue(0)
        a.setEndValue(w.sizeHint().height())
        a.finished.connect(lambda: w.setMaximumHeight(16777215))  # libera tope al terminar
    else:
        a.setStartValue(w.height())
        a.setEndValue(0)
        a.finished.connect(lambda: w.setVisible(False))
    w._fx = a  # evitar que el GC mate la animación
    a.start()


class Spinner(QLabel):
    """Actividad en filas de herramienta: braille girando, luego ✓/✗."""
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("color: #9aa0a6; font-size: 12px;")
        self._i = 0
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(90)

    def _tick(self):
        self._i = (self._i + 1) % len(self.FRAMES)
        self.setText(self.FRAMES[self._i])

    def stop(self, ok=True):
        self._t.stop()
        self.setText("✓" if ok else "✗")
        self.setStyleSheet(
            ("color: #34c759;" if ok else "color: #ff453a;") + " font-size: 12px;"
        )


class PensandoDots(QLabel):
    """'Pensando...' con puntos vivos; se asienta en 'Pensó durante N s'."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("color: #9aa0a6; font-weight: 600; font-size: 11px;")
        self._n = 0
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(350)
        self._tick()

    def _tick(self):
        self._n = (self._n + 1) % 4
        self.setText("🤔 Pensando" + "." * self._n)

    def stop(self, secs):
        self._t.stop()
        self.setText(f"🤔 Pensó durante {secs:.0f} s")
