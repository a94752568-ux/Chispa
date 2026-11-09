#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""widgets.py — Widgets de chat.

ThinkingBlockWidget (pensamiento colapsable con cronómetro), ToolBlockWidget
(bloque de herramientas estilo ChatGPT), MessageBubble (burbuja con dedup de
streaming, proyecto E3), ChatContainer (columna centrada máx 760 px) y
TitleBar (barra de título frameless).
"""
import json
import time
from pathlib import Path
from typing import List

import markdown as _md
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QTextBrowser, QSizePolicy, QApplication,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap

from common import trace, MD_CSS, DEDUP_ENABLED, DEBUG_DEDUP, DEDUP_LOG_PATH
from tools.chat_fx import fade_in, animate_height, Spinner, PensandoDots
import theme

# ================= UI WIDGETS =================
class ThinkingBlockWidget(QFrame):
    """Línea de pensamiento colapsable: mide tiempo real, cabecera clicable con chevron."""
    def __init__(self):
        super().__init__()
        self.setObjectName("thinkingBlock")
        self.setStyleSheet("""
            #thinkingBlock {
                background: transparent;
                border: none;
                border-radius: 0;
                margin: 0;
            }
        """)
        self.is_expanded = False  # colapsado por defecto
        self._t0 = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Encabezado clicable: chevron + PensandoDots (puntos vivos)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self.chevron = QLabel("⌄")
        self.chevron.setFixedSize(14, 14)
        self.chevron.setStyleSheet(f"color: {theme.TEXT_SECOND}; font-size: 10px;")
        header.addWidget(self.chevron)

        self.dots = PensandoDots()
        self.dots.setFixedHeight(16)
        header.addWidget(self.dots)
        header.addStretch()

        self.header_widget = QFrame()
        self.header_widget.setLayout(header)
        self.header_widget.setCursor(Qt.PointingHandCursor)
        self.header_widget.mousePressEvent = lambda e: self.toggle()
        layout.addWidget(self.header_widget)

        # Cuerpo: texto sin borde ni fondo, sangría 12px
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.setStyleSheet(f"""
            QLabel {{
                background: transparent;
                border: none;
                color: {theme.TEXT_SECOND};
                font-size: 13px;
                line-height: 1.5;
                padding: 0 0 0 12px;
                font-family: {theme.FONT_STACK};
            }}
        """)
        self.body.setVisible(False)
        layout.addWidget(self.body)

    def start(self):
        self.show()
        self.body.setVisible(False)
        self._t0 = time.monotonic()
        self.dots._tick()
        trace(f"ThinkingBlockWidget.start t0={self._t0:.3f}")
        self._notify_parent()

    def update_content(self, text: str):
        self.show()
        self.body.setVisible(True)
        self.body.setText(text[:3000])
        self._notify_parent()

    def finish(self, text: str, secs: float | None = None):
        if secs is None:
            secs = (time.monotonic() - self._t0) if self._t0 else 0.0
        trace(f"ThinkingBlockWidget.finish secs={secs:.3f} text_len={len(text or '')}")
        self.dots.stop(secs)
        # Cinturón: si no hay pensamiento real, ocultar el bloque por completo
        if not text or not text.strip() or secs <= 0.5:
            self.hide()
            self._notify_parent()
            return
        self.body.setVisible(True)
        self.body.setText(text)
        self._notify_parent()

    def _notify_parent(self):
        parent = self.parentWidget()
        if parent:
            parent.updateGeometry()
            if parent.layout():
                parent.layout().activate()

    def toggle(self):
        if self.is_expanded:
            animate_height(self.body, False, ms=140)
            self.chevron.setText("⌄")
            self.is_expanded = False
        else:
            animate_height(self.body, True, ms=140)
            self.chevron.setText("⌃")
            self.is_expanded = True
        self._notify_parent()


class ToolBlockWidget(QFrame):
    """Bloque de herramientas estilo ChatGPT: filas limpias, sin JSON crudo."""
    def __init__(self):
        super().__init__()
        self.setObjectName("toolBlock")
        self.setStyleSheet("""
            #toolBlock {
                background: transparent;
                border: none;
                border-radius: 0;
                margin: 0;
            }
        """)
        self.is_expanded = False  # colapsado por defecto
        self._has_error = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Encabezado clicable: chevron + título + estado
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self.chevron = QLabel("⌄")
        self.chevron.setFixedSize(14, 14)
        self.chevron.setStyleSheet(f"color: {theme.TEXT_SECOND}; font-size: 10px;")
        header.addWidget(self.chevron)

        self.label = QLabel("🔧 Herramientas")
        self.label.setStyleSheet(f"color: {theme.TEXT_SECOND}; font-weight: 600; font-size: 11px;")
        header.addWidget(self.label)
        header.addStretch()

        self.header_widget = QFrame()
        self.header_widget.setLayout(header)
        self.header_widget.setCursor(Qt.PointingHandCursor)
        self.header_widget.mousePressEvent = lambda e: self.toggle()
        layout.addWidget(self.header_widget)

        # Cuerpo: filas de herramientas (oculto al inicio)
        self.body_widget = QFrame()
        self.body_widget.setStyleSheet(f"""
            QFrame {{
                background: {theme.BG_ELEVATED};
                border: none;
                border-top: none;
                border-radius: 0 0 10px 10px;
            }}
        """)
        self.body_widget.setVisible(False)

        body_layout = QVBoxLayout(self.body_widget)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self._entries = []
        layout.addWidget(self.body_widget)

    def _notify_parent(self):
        parent = self.parentWidget()
        if parent:
            parent.updateGeometry()
            if parent.layout():
                parent.layout().activate()

    def add_call(self, name: str, args: dict):
        """Crea una fila limpia por tool ejecutado."""
        trace(f"ToolBlockWidget.add_call name={name} args={args}")
        row = QFrame()
        row.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border-bottom: 1px solid {theme.BORDER_SOFT};
                padding: 6px 12px;
            }}
        """)
        row.setCursor(Qt.PointingHandCursor)
        row.mousePressEvent = lambda e: self._toggle_detail_by_row(row)

        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        # Icono de estado: Spinner mientras corre
        status_icon = Spinner()
        status_icon.setFixedSize(16, 16)
        row_layout.addWidget(status_icon)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600; font-size: 13px;")
        row_layout.addWidget(name_lbl)

        status_lbl = QLabel("ejecutando…")
        status_lbl.setStyleSheet(f"color: {theme.TEXT_SECOND}; font-size: 11px; font-style: italic;")
        row_layout.addWidget(status_lbl)
        row_layout.addStretch()

        # Chevron inline al final de la fila
        row_chevron = QLabel("⌄")
        row_chevron.setFixedSize(12, 12)
        row_chevron.setStyleSheet(f"color: {theme.TEXT_SECOND}; font-size: 9px;")
        row_layout.addWidget(row_chevron)

        body_layout = self.body_widget.layout()
        body_layout.addWidget(row)
        self._entries.append({
            "name": name,
            "args": args,
            "result": "",
            "row": row,
            "row_layout": row_layout,
            "status_icon": status_icon,
            "status_lbl": status_lbl,
            "row_chevron": row_chevron,
            "expanded": False,
            "detail_widget": None,
            "done": False,
        })
        self.show()
        self._notify_parent()

    def add_result(self, name: str, result: str):
        """Actualiza la fila del tool con su resultado y resumen."""
        trace(f"ToolBlockWidget.add_result name={name} result_len={len(result or '')} preview={str(result)[:60]!r}")
        for entry in self._entries:
            if entry["name"] == name and not entry["done"]:
                entry["result"] = result
                entry["done"] = True
                summary = self._make_summary(name, result)
                entry["status_lbl"].setText(summary)
                entry["status_lbl"].setStyleSheet(f"color: {theme.SUCCESS}; font-size: 11px; font-weight: 600;")
                entry["status_icon"].stop(True)
                entry["row_chevron"].setText("⌃")
                self._notify_parent()
                break

    def _make_summary(self, name: str, result: str) -> str:
        """Genera un resumen legible sin JSON crudo."""
        if not result or result.startswith("Error"):
            return "error"
        r = result.strip()
        if name == "web_search":
            parts = [p.strip() for p in r.split("---") if p.strip()]
            n = len(parts)
            return f"{n} resultado{'s' if n != 1 else ''} encontrado{'s' if n != 1 else ''}"
        if name == "get_weather":
            return r[:60] + ("…" if len(r) > 60 else "")
        if name == "get_current_time":
            return r[:60] + ("…" if len(r) > 60 else "")
        if name == "system_info":
            return "info del sistema"
        if name == "calculator":
            return r[:60] + ("…" if len(r) > 60 else "")
        if name == "read_file":
            return "archivo leído"
        if name == "speak":
            return "reproducido por voz"
        if name == "listen":
            return "texto dictado"
        return r[:60] + ("…" if len(r) > 60 else "")

    def _toggle_detail_by_row(self, row):
        """Alterna el detalle de la fila clicada."""
        for entry in self._entries:
            if entry["row"] is row:
                self._toggle_detail(entry)
                break

    def _toggle_detail(self, entry):
        """Muestra/oculta el detalle formateado de un tool."""
        if entry["expanded"]:
            if entry.get("detail_widget"):
                animate_height(entry["detail_widget"], False, ms=140)
                entry["detail_widget"].deleteLater()
                entry["detail_widget"] = None
            entry["expanded"] = False
            entry["row_chevron"].setText("⌃")
        else:
            detail = QTextBrowser()
            detail.setOpenExternalLinks(True)
            result_text = entry["result"]
            lines = [l.strip() for l in result_text.splitlines() if l.strip()]
            result_text = "\n\n".join(lines)
            html = _md.markdown(result_text, extensions=["extra"])
            detail.setHtml(html)
            detail.setStyleSheet(f"""
                QTextBrowser {{
                    background: transparent;
                    border: none;
                    border-left: 2px solid {theme.BORDER};
                    border-radius: 0;
                    color: {theme.TEXT};
                    font-size: 13px;
                    line-height: 1.5;
                    padding: 0 0 0 12px;
                    font-family: {theme.FONT_STACK};
                }}
                QTextBrowser a {{ color: {theme.LINK}; text-decoration: underline; }}
            """)
            detail.document().setDefaultStyleSheet(MD_CSS)
            detail.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            detail.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            detail.setMaximumHeight(250)
            body_layout = self.body_widget.layout()
            idx = body_layout.indexOf(entry["row"])
            body_layout.insertWidget(idx + 1, detail)
            entry["detail_widget"] = detail
            entry["expanded"] = True
            entry["row_chevron"].setText("⌄")
            animate_height(detail, True, ms=140)
        self._notify_parent()

    def _set_header_state(self):
        if self._has_error:
            self.label.setText("🔧 Herramientas finalizadas con errores")
            self.label.setStyleSheet(f"color: {theme.ERROR}; font-weight: 600; font-size: 11px;")
        else:
            self.label.setText("🔧 Herramientas completadas")
            self.label.setStyleSheet(f"color: {theme.SUCCESS}; font-weight: 600; font-size: 11px;")

    def finish(self):
        """Contención inmediata: filas sin resultado pasan a error.
        Todas las filas quedan colapsadas al terminar: solo filas compactas visibles."""
        trace(f"ToolBlockWidget.finish entries={len(self._entries)} done={sum(1 for e in self._entries if e.get('done'))}")
        for entry in self._entries:
            if entry.get("detail_widget"):
                entry["detail_widget"].setVisible(False)
                entry["detail_widget"].deleteLater()
                entry["detail_widget"] = None
            entry["expanded"] = False
            entry["row_chevron"].setText("⌃")
            if not entry["done"]:
                entry["done"] = True
                entry["status_lbl"].setText("sin respuesta (timeout)")
                entry["status_lbl"].setStyleSheet(f"color: {theme.ERROR}; font-size: 11px; font-weight: 600;")
                entry["status_icon"].stop(False)
                self._has_error = True
        self._set_header_state()
        animate_height(self.body_widget, True, ms=140)
        self._notify_parent()

    def toggle(self):
        if self.is_expanded:
            animate_height(self.body_widget, False, ms=140)
            self.chevron.setText("⌄")
            self.is_expanded = False
        else:
            animate_height(self.body_widget, True, ms=140)
            self.chevron.setText("⌃")
            self.is_expanded = True
        self._notify_parent()


class MessageBubble(QFrame):
    """Burbuja de mensaje estilo ChatGPT: 3 niveles para OLLAMA, simple para usuario."""
    def __init__(self, role: str, content: str, images: List[str] = None, enable_think: bool = True):
        super().__init__()
        self.role = role
        self.full_text = content or ""
        self.images = images or []
        self.enable_think = enable_think and (role == "assistant")
        self._answer_started = False
        self._last_emit = ""  # Track last emitted delta for deduplication
        self._duplicate_consecutive_count = 0
        self._duplicate_fulltext_count = 0
        self._accepted_delta_count = 0
        self._raw_delta_count = 0
        self._empty_delta_count = 0
        self._dedup_enabled = DEDUP_ENABLED  # E3 dedup control
        trace(f"MessageBubble.__init__ role={role} enable_think={enable_think} images={len(self.images or [])}")

        self.setObjectName("messageBubble")
        self.setStyleSheet("""
            QFrame#messageBubble {
                background: transparent;
                border: none;
                border-radius: 0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ================================================================
        # Nivel 1: Header estilo Vibe (solo asistente: chispa naranja)
        # ================================================================
        if role == "assistant":
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 6)
            head.setSpacing(8)

            spark = QLabel("✦")
            spark.setFixedSize(22, 22)
            spark.setAlignment(Qt.AlignCenter)
            spark.setStyleSheet(f"""
                QLabel {{
                    background: {theme.ACCENT};
                    color: {theme.TEXT_ON_ACCENT};
                    border-radius: 11px;
                    font-size: 13px;
                    font-weight: bold;
                }}
            """)
            head.addWidget(spark)
            head.addStretch()
            layout.addLayout(head)

        # ================================================================
        # Nivel 2: Contenido del mensaje (burbujas o zona de proceso)
        # ================================================================
        if role == "user":
            # Usuario: burbuja a la derecha, estilo ChatGPT (#343541)
            bubble_container = QHBoxLayout()
            bubble_container.setContentsMargins(0, 0, 0, 0)
            bubble_container.setSpacing(0)

            self.bubble = QFrame()
            self.bubble.setObjectName("userBubble")
            self.bubble.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            self.bubble.setMaximumWidth(620)
            self.bubble.setStyleSheet(f"""
                QFrame#userBubble {{
                    background: {theme.ACCENT_TINT};
                    border: 1px solid {theme.ACCENT_BORDER};
                    border-radius: 18px;
                }}
            """)

            bubble_layout = QVBoxLayout(self.bubble)
            bubble_layout.setContentsMargins(16, 12, 16, 12)
            bubble_layout.setSpacing(10)

            if self.images:
                for img_path in self.images:
                    try:
                        pix = QPixmap(img_path)
                        if not pix.isNull():
                            img_lbl = QLabel()
                            img_lbl.setPixmap(pix.scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                            img_lbl.setStyleSheet("border-radius: 8px; background: #0a0a0b; padding: 4px;")
                            bubble_layout.addWidget(img_lbl)
                        name_lbl = QLabel(f"📎 {Path(img_path).name}")
                        name_lbl.setStyleSheet(f"color: {theme.TEXT_SECOND}; font-size: 11px; font-weight: 600;")
                        bubble_layout.addWidget(name_lbl)
                    except Exception:
                        pass

            self.text_browser = QTextBrowser()
            self.text_browser.setOpenExternalLinks(True)
            self.text_browser.setMarkdown(content or "")
            self.text_browser.setStyleSheet(f"""
                QTextBrowser {{
                    background: transparent;
                    border: none;
                    color: {theme.TEXT};
                    font-size: 14px;
                    line-height: 1.6;
                    padding: 0;
                    font-family: {theme.FONT_STACK};
                }}
                QTextBrowser a {{ color: {theme.LINK}; text-decoration: underline; }}
            """)
            self.text_browser.document().setDefaultStyleSheet(MD_CSS)
            self.text_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.text_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            bubble_layout.addWidget(self.text_browser)

            bubble_container.addStretch()
            bubble_container.addWidget(self.bubble, 0, Qt.AlignRight)
            layout.addLayout(bubble_container)

        else:
            # OLLAMA: Nivel 2 - Zona de proceso (Think + Tools, fondo sutil)
            process_zone = QFrame()
            process_zone.setObjectName("processZone")
            process_zone.setStyleSheet("""
                #processZone {
                    background: transparent;
                    border: none;
                    border-radius: 0;
                }
            """)
            process_layout = QVBoxLayout(process_zone)
            process_layout.setContentsMargins(0, 0, 0, 0)
            process_layout.setSpacing(0)

            self.thinking_block = None
            self.tool_block = ToolBlockWidget()

            if self.enable_think:
                self.thinking_block = ThinkingBlockWidget()
                process_layout.addWidget(self.thinking_block)

            process_layout.addWidget(self.tool_block)

            layout.addWidget(process_zone)

            # Nivel 3 - Respuesta final: SIN burbuja (transparent), texto directo
            self.text_browser = QTextBrowser()
            self.text_browser.setOpenExternalLinks(True)
            self.text_browser.setMarkdown(content or "")
            self.text_browser.setStyleSheet(f"""
                QTextBrowser {{
                    background: transparent;
                    border: none;
                    color: {theme.TEXT};
                    font-size: 15px;
                    line-height: 1.6;
                    padding: 0 0 12px 0;
                    font-family: {theme.FONT_STACK};
                }}
                QTextBrowser a {{ color: {theme.LINK}; text-decoration: underline; }}
            """)
            self.text_browser.document().setDefaultStyleSheet(MD_CSS)
            self.text_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.text_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            layout.addWidget(self.text_browser)

            # Fila de iconos (meta): ⧉ ♻ 🔊 , oculta por defecto, visible al hover
            icon_row = QHBoxLayout()
            icon_row.setContentsMargins(0, 4, 0, 0)
            icon_row.setSpacing(10)

            copy_btn = QPushButton("⧉")
            copy_btn.setFixedSize(24, 24)
            copy_btn.setToolTip("Copiar respuesta")
            copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.full_text or ""))
            copy_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {theme.TEXT_SECOND};
                    border: none;
                    border-radius: 4px;
                    font-size: 14px;
                }}
                QPushButton:hover {{ background: {theme.BG_INPUT}; color: {theme.TEXT}; }}
            """)

            retry_btn = QPushButton("♻")
            retry_btn.setFixedSize(24, 24)
            retry_btn.setToolTip("Regenerar respuesta")
            retry_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {theme.TEXT_SECOND};
                    border: none;
                    border-radius: 4px;
                    font-size: 14px;
                }}
                QPushButton:hover {{ background: {theme.BG_INPUT}; color: {theme.TEXT}; }}
            """)

            tts_btn = QPushButton("🔊")
            tts_btn.setFixedSize(24, 24)
            tts_btn.setToolTip("Leer respuesta en voz alta (TTS)")
            tts_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {theme.TEXT_SECOND};
                    border: none;
                    border-radius: 4px;
                    font-size: 14px;
                }}
                QPushButton:hover {{ background: {theme.BG_INPUT}; color: {theme.TEXT}; }}
            """)
            tts_btn.clicked.connect(lambda: self.window().speak_response(self.full_text))

            icon_row.addWidget(copy_btn)
            icon_row.addWidget(retry_btn)
            icon_row.addWidget(tts_btn)
            icon_row.addStretch()

            icon_container = QFrame()
            icon_container.setLayout(icon_row)
            icon_container.setVisible(False)
            self.icon_container = icon_container
            layout.addWidget(icon_container)

        # Reflow diferido: colapsa el hueco entre respuesta e iconos
        QTimer.singleShot(0, self._reflow)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._reflow()

    def _reflow(self):
        """Ajusta la altura del text_browser a su contenido real."""
        if hasattr(self, 'text_browser'):
            doc_height = self.text_browser.document().size().height()
            self.text_browser.setMinimumHeight(int(doc_height) + 8)

    # --- hover para mostrar/ocultar iconos (solo asistente) ---
    def enterEvent(self, event):
        if self.role == "assistant" and hasattr(self, 'icon_container'):
            self.icon_container.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.role == "assistant" and hasattr(self, 'icon_container'):
            self.icon_container.setVisible(False)
        super().leaveEvent(event)

    def setAnswer(self, text: str):
        self.full_text = text
        self.text_browser.setMarkdown(text)
        self._last_emit = ""  # Reset last_emit when answer is set directly
        self._duplicate_consecutive_count = 0
        self._duplicate_fulltext_count = 0
        self._accepted_delta_count = 0
        self._raw_delta_count = 0
        self._empty_delta_count = 0

    def appendAnswer(self, delta: str):
        """
        Append answer delta with deduplication and metrics tracking.
        
        Thread Safety: This method should only be called from the main thread
        via Qt signal/slot mechanisms. It is not thread-safe and may cause
        segfaults if called from other threads.
        
        IMPORTANT: In production, this is called via:
        OllamaWorker.chunk_received -> MainWindow.on_chunk -> current_assistant_widget.appendAnswer
        
        The Qt signal/slot mechanism ensures thread safety when used correctly.
        Do not call appendAnswer() directly from non-main threads.
        """
        # Thread safety check - ensure this is called from main thread
        from PySide6.QtCore import QThread, QCoreApplication
        
        app = QCoreApplication.instance()
        if app is not None:
            current_thread = QThread.currentThread()
            app_thread = app.thread()
            if current_thread != app_thread:
                # Log error for debugging
                import sys
                print(f"WARNING: appendAnswer() called from thread {current_thread.objectName()} instead of main thread.", file=sys.stderr)
                print(f"         This may cause segfaults. Call should be via Qt signal/slot mechanism.", file=sys.stderr)
                # Don't crash, just continue - defensive approach
                # In production, this should never happen if architecture is correct
                return

        # Handle None delta gracefully
        if delta is None:
            self._raw_delta_count = getattr(self, "_raw_delta_count", 0) + 1
            return

        # Increment raw delta count for all non-None deltas
        self._raw_delta_count = getattr(self, "_raw_delta_count", 0) + 1

        # Handle empty deltas (consistent with original behavior)
        if not delta:
            self._empty_delta_count = getattr(self, "_empty_delta_count", 0) + 1
            return

        last_emit = getattr(self, "_last_emit", "")

        # --------------------------------------------------
        # DEDUP 2: snapshot completo repetido.
        # Prioridad alta porque evita duplicar toda la respuesta.
        # --------------------------------------------------
        if self.full_text and delta == self.full_text:
            self._duplicate_fulltext_count = (
                getattr(self, "_duplicate_fulltext_count", 0) + 1
            )
            self._last_emit = delta

            # Opcional: healing solo si el widget no refleja full_text.
            # Evitar setMarkdown() incondicional para no provocar repintado.
            if self.text_browser.toPlainText().strip() != self.full_text.strip():
                self.text_browser.setMarkdown(self.full_text)
                self._reflow()
            return

        # --------------------------------------------------
        # DEDUP 1: duplicado consecutivo exacto.
        # --------------------------------------------------
        if delta == last_emit:
            self._duplicate_consecutive_count = (
                getattr(self, "_duplicate_consecutive_count", 0) + 1
            )
            return

        # --------------------------------------------------
        # Snapshot creciente opcional.
        # Si delta contiene full_text + sufijo nuevo, aceptar solo sufijo.
        # --------------------------------------------------
        if self.full_text and delta.startswith(self.full_text):
            suffix = delta[len(self.full_text):]

            if suffix:
                self.full_text = delta
                self._last_emit = delta
                self._accepted_delta_count = (
                    getattr(self, "_accepted_delta_count", 0) + 1
                )
                self.text_browser.insertPlainText(suffix)
                self._reflow()
                return

            # Si suffix vacío, ya lo trató DEDUP 2, pero por seguridad:
            self._duplicate_fulltext_count = (
                getattr(self, "_duplicate_fulltext_count", 0) + 1
            )
            self._last_emit = delta
            return

        # --------------------------------------------------
        # DEDUP 3: delta incremental normal.
        # --------------------------------------------------
        self.full_text += delta
        self._last_emit = delta
        self._accepted_delta_count = (
            getattr(self, "_accepted_delta_count", 0) + 1
        )
        trace(f"appendAnswer: agregando nuevo delta, total aceptado {self._accepted_delta_count}: {delta[:40]!r}")

        trace(f"appendAnswer after len={len(self.full_text)}")
        if self.role == "user" and hasattr(self, 'bubble') and self.bubble.isHidden():
            self.bubble.show()
        if self.role == "assistant" and not getattr(self, "_answer_started", False):
            self.text_browser.show()
            self._answer_started = True
        self.text_browser.setMarkdown(self.full_text + " ▍")
        self._reflow()

    def showTTS(self):
        if hasattr(self, 'icon_container'):
            self.icon_container.setVisible(True)

    def _snapshot_dedup_metrics(self) -> dict:
        return {
            "raw_delta_count": getattr(self, "_raw_delta_count", 0),
            "accepted_delta_count": getattr(self, "_accepted_delta_count", 0),
            "duplicate_consecutive_count": getattr(self, "_duplicate_consecutive_count", 0),
            "duplicate_fulltext_count": getattr(self, "_duplicate_fulltext_count", 0),
            "empty_delta_count": getattr(self, "_empty_delta_count", 0),
            "dedup_enabled": getattr(self, "_dedup_enabled", True),
        }

    def finishAnswer(self, answer: str, thinking: str, error: str = None):
        """
        Finish answer with final content, thinking block, or error.
        
        Thread Safety: This method should only be called from the main thread.
        It mutates UI widgets and should only be accessed via proper Qt
        signal/slot mechanisms in production.
        """
        # Thread safety check - ensure this is called from main thread
        from PySide6.QtCore import QThread, QCoreApplication
        
        app = QCoreApplication.instance()
        if app is not None:
            current_thread = QThread.currentThread()
            app_thread = app.thread()
            if current_thread != app_thread:
                # Log error for debugging
                import sys
                print(f"WARNING: finishAnswer() called from thread {current_thread.objectName()} instead of main thread.", file=sys.stderr)
                print(f"         UI widgets should only be mutated from main thread.", file=sys.stderr)
                # Don't crash, just continue - defensive approach
                return
        try:
            if error is not None:
                # Error takes absolute priority but preserves existing content
                if self.full_text:
                    self.text_browser.setMarkdown(f"{self.full_text}\n[ERROR] {error}")
                else:
                    self.text_browser.setMarkdown(f"[ERROR] {error}")
                # When error is shown, answer is considered started
                if not getattr(self, "_answer_started", False):
                    self.text_browser.show()
                    self._answer_started = True
            elif answer.strip():
                # Normal answer with content
                self.text_browser.setMarkdown(answer)
                # When answer is shown, mark as started
                if not getattr(self, "_answer_started", False):
                    self.text_browser.show()
                    self._answer_started = True
            elif self.thinking_block is not None:
                # Show placeholder when there's thinking block
                if self.full_text:
                    self.text_browser.setMarkdown(self.full_text)
                else:
                    self.text_browser.setMarkdown("_(el modelo no produjo síntesis tras las herramientas)_")
                if not getattr(self, "_answer_started", False):
                    self.text_browser.show()
                    self._answer_started = True
            elif self.tool_block is not None:
                # Show placeholder when there's tool block
                if self.full_text:
                    self.text_browser.setMarkdown(self.full_text)
                else:
                    self.text_browser.setMarkdown("_(el modelo no produjo síntesis tras las herramientas)_")
                if not getattr(self, "_answer_started", False):
                    self.text_browser.show()
                    self._answer_started = True
            elif self.full_text:
                # Preserve streaming content when answer is empty
                self.text_browser.setMarkdown(self.full_text)
                if not getattr(self, "_answer_started", False):
                    self.text_browser.show()
                    self._answer_started = True
            else:
                # Empty answer, thinking, or tool block only - hide text browser
                self.text_browser.hide()
                self.text_browser.setMarkdown("")
                # Don't start answer when there's no content
                self._answer_started = False
        finally:
            # Cleanup structural blocks regardless of exceptions
            if self.thinking_block is not None:
                self.thinking_block.finish(thinking)
            if self.tool_block is not None:
                self.tool_block.finish()
            self.updateGeometry()
            if self.layout():
                self.layout().activate()
            # Snapshot deduplication metrics before resetting
            metrics = self._snapshot_dedup_metrics()
            metrics["dedup_enabled"] = getattr(self, "_dedup_enabled", True)
            self._last_dedup_metrics = metrics
            
            # Log metrics if debug enabled
            if DEBUG_DEDUP:
                import logging
                logger = logging.getLogger(__name__)
                logger.info(
                    "E3 dedup metrics: raw=%s accepted=%s dup_consecutive=%s "
                    "dup_fulltext=%s empty=%s dedup_enabled=%s",
                    metrics.get("raw_delta_count"),
                    metrics.get("accepted_delta_count"),
                    metrics.get("duplicate_consecutive_count"),
                    metrics.get("duplicate_fulltext_count"),
                    metrics.get("empty_delta_count"),
                    metrics.get("dedup_enabled"),
                )
            
            if DEDUP_LOG_PATH:
                try:
                    from pathlib import Path
                    log_file = Path(DEDUP_LOG_PATH)
                    log_file.parent.mkdir(parents=True, exist_ok=True)
                    with log_file.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(metrics, ensure_ascii=False) + "\n")
                except Exception:
                    # No romper la UI por fallos de logging.
                    pass
            
            # Reset deduplication metrics after answer is complete
            self._duplicate_consecutive_count = 0
            self._duplicate_fulltext_count = 0
            self._accepted_delta_count = 0
            self._raw_delta_count = 0
            self._empty_delta_count = 0
            self._last_emit = ""


class ChatContainer(QWidget):
    """Contenedor del chat con columna centrada (máx 760 px)."""
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 8, 12, 8)
        self.layout.setSpacing(12)
        self.layout.setAlignment(Qt.AlignTop)
        self._max_width = 760

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        m = max(0, (w - self._max_width) // 2)
        self.layout.setContentsMargins(m, 8, m, 8)

    def add_message_widget(self, widget: MessageBubble):
        self.layout.addWidget(widget)
        fade_in(widget)

    def clear_except_welcome(self):
        while self.layout.count() > 1:
            item = self.layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()


class TitleBar(QFrame):
    """Barra de título personalizada con botones de ventana (sin header nativo)"""
    def __init__(self, parent: QMainWindow):
        super().__init__(parent)
        self.window = parent
        self.setFixedHeight(40)
        self.setStyleSheet(f"""
            QFrame {{
                background: {theme.BG_TITLEBAR};
                border-bottom: 1px solid {theme.BORDER_SOFT};
            }}
            QLabel {{
                color: {theme.TEXT};
                font-size: 13px;
                font-weight: bold;
                padding-left: 12px;
            }}
            QPushButton {{
                background: transparent;
                color: {theme.TEXT};
                border: none;
                font-size: 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {theme.BG_ELEVATED};
                border-radius: 6px;
            }}
            QPushButton#closeBtn:hover {{
                background: #4a1a1a;
                color: {theme.ERROR};
            }}
        """)
        self._pressing = False
        self._start_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_label = QLabel("Ollama GUI - Lubuntu Edition")
        layout.addWidget(self.title_label)
        layout.addStretch()

        self.min_btn = QPushButton("−")
        self.min_btn.setFixedSize(40, 40)
        self.min_btn.clicked.connect(self.window.showMinimized)
        layout.addWidget(self.min_btn)

        self.max_btn = QPushButton("□")
        self.max_btn.setFixedSize(40, 40)
        self.max_btn.clicked.connect(self.toggle_maximize)
        layout.addWidget(self.max_btn)

        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("closeBtn")
        self.close_btn.setFixedSize(40, 40)
        self.close_btn.clicked.connect(self.window.close)
        layout.addWidget(self.close_btn)

    def toggle_maximize(self):
        if self.window.isMaximized():
            self.window.showNormal()
            self.max_btn.setText("□")
        else:
            self.window.showMaximized()
            self.max_btn.setText("❐")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressing = True
            self._start_pos = event.globalPosition().toPoint()
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pressing and self._start_pos is not None:
            diff = event.globalPosition().toPoint() - self._start_pos
            self.window.move(self.window.pos() + diff)
            self._start_pos = event.globalPosition().toPoint()
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressing = False
        super().mouseReleaseEvent(event)


