import sys
import time
import os
import re
import json
import base64
import requests
import markdown as _md
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# Asegurar que el directorio del script esté en sys.path para encontrar tools/
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

# E3 dedup debug flags
DEDUP_ENABLED = os.getenv("OLLAMA_GUI_DEDUP", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}

DEBUG_DEDUP = os.getenv("OLLAMA_GUI_DEBUG_DEDUP", "0").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

DEDUP_LOG_PATH = os.getenv("OLLAMA_GUI_DEDUP_LOG", "")

# Asegurar que el directorio del script esté en sys.path para encontrar tools/
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QTextEdit, QPushButton, QLabel, QComboBox, QCheckBox,
    QListWidget, QListWidgetItem, QFrame, QSplitter, QFileDialog, QMessageBox,
    QProgressBar, QGroupBox, QTextBrowser, QLineEdit, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QSize, QMimeData, QTimer, QEvent, QPropertyAnimation
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPixmap, QIcon, QFont, QColor

# Ollama
try:
    import ollama
except:
    ollama = None

# ================================================================
# Estilos de jerarquía para markdown (setDefaultStyleSheet)
# Evita el look "ensayo viejo" de los títulos enormes de Qt
# ================================================================
MD_CSS = """
h1 { font-size: 19px; font-weight: bold; margin: 14px 0 6px; color: #e5e5ea; }
h2 { font-size: 17px; font-weight: bold; margin: 12px 0 5px; color: #e5e5ea; }
h3 { font-size: 15px; font-weight: bold; margin: 10px 0 4px; color: #e5e5ea; }
p  { margin: 6px 0; }
ul, ol { margin: 6px 0; padding-left: 20px; }
li { margin: 3px 0; }
code { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 13px;
       background: #1f2126; border-radius: 4px; padding: 1px 5px; color: #e8b48a; }
pre { background: #1f2126; border-radius: 8px; padding: 10px 12px; }
pre code { background: transparent; padding: 0; }
blockquote { border-left: 3px solid #2a2c31; margin: 8px 0;
             padding: 2px 0 2px 10px; color: #9aa0a6; }
a { color: #6cb6ff; text-decoration: none; }
hr { border: none; border-top: 1px solid #2a2c31; margin: 10px 0; }
"""

import time as _time
import threading as _threading


def trace(msg):
    print(f"[{_time.strftime('%H:%M:%S')}] {_threading.current_thread().name:>12} | {msg}", flush=True)


# Tools registry - robusto con fallback
try:
    from tools import load_tools
    from tools.pre_router import ToolRouter
    from tools.agent_orchestrator import Orchestrator
except ImportError as e:
    print(f"⚠ No se pudo importar tools.load_tools: {e}")
    print(f"  Buscando en: {SCRIPT_DIR / 'tools'}")
    import importlib.util
    import traceback

    def load_tools():
        definitions = []
        executors = {}
        tools_dir = SCRIPT_DIR / "tools"
        if not tools_dir.exists():
            print(f"⚠ Carpeta tools no existe en {tools_dir}")
            return definitions, executors

        print(f"🔍 Cargando tools desde fallback: {tools_dir}")
        for file in tools_dir.glob("*.py"):
            if file.name.startswith("_") or file.name == "__init__.py":
                continue
            try:
                spec = importlib.util.spec_from_file_location(file.stem, file)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "TOOL_DEFINITION") and hasattr(mod, "execute"):
                    definitions.append(mod.TOOL_DEFINITION)
                    executors[mod.TOOL_DEFINITION["function"]["name"]] = mod.execute
                    print(f"✓ Tool cargado (fallback): {mod.TOOL_DEFINITION['function']['name']}")
            except Exception as ex:
                print(f"✗ Error cargando {file.name}: {ex}")
                traceback.print_exc()
        return definitions, executors

from tools.chat_fx import fade_in, animate_height, Spinner, PensandoDots


VISION_MODELS = ["llava", "bakllava", "gemma3", "qwen2-vl", "qwen2.5-vl", "llama3.2-vision", "minicpm-v", "moondream", "vision"]
VISION_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# ================================================================
# System prompt inyectado en cada llamada al modelo
# ================================================================
SYSTEM_PROMPT = """Idioma: respondes SIEMPRE en español, el idioma del usuario, salvo que pida explícitamente otro idioma. Si el usuario escribe en español, respondes en español. No uses chino ni inglés salvo que se te pida. Si herramientas devuelven texto en otro idioma, traduce o explica en español.

Estilo: no narres tu proceso interno en la respuesta final ("we need to...", "debemos analizar..."). La respuesta comienza directo con el hallazgo central; el razonamiento pertenece al canal de pensamiento, no al texto visible.

Cuando uses herramientas, sintetiza, nunca transcribas:
1) Una frase de apertura con el hallazgo central.
2) 3-6 bullets con ideas principales y datos concretos.
3) Un párrafo breve de matices o contexto.
4) Fuentes como enlaces markdown al final.
Prohibido volcar resultados crudos o listar URLs sin interpretarlas."""

def is_vision_model(name: str) -> bool:
    low = name.lower()
    return any(v in low for v in VISION_MODELS)


# ================================================================
# Memoria persistente del chat
# ================================================================
MEMORY_DIR = Path.home() / ".local" / "share" / "OllamaChat-GUI"
MEMORY_FILE = MEMORY_DIR / "chat_history.json"


def _ensure_memory_dir():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

def encode_image(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except:
        return None

# ================= WORKER =================
class OllamaWorker(QThread):
    chunk_received = Signal(str)  # delta answer
    thinking_chunk = Signal(str)  # thinking delta
    tool_call_detected = Signal(str, dict)  # name, args
    tool_result_ready = Signal(str, str)  # name, result
    thinking_started = Signal()
    thinking_finished = Signal(str)
    final_answer = Signal(str, str)  # answer, thinking
    error_occurred = Signal(str)
    status_update = Signal(str)

    def __init__(self, model: str, history: List[Dict], tools_def: List[Dict], executors: Dict, enable_tools: bool = True, enable_think: bool = True):
        super().__init__()
        self.model = model
        self.history = history.copy()
        self.tools_def = tools_def if enable_tools else []
        self.executors = executors
        self.enable_tools = enable_tools
        self.enable_think = enable_think
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        if ollama is None:
            self.error_occurred.emit("ollama no instalado. pip install ollama")
            return

        client = ollama.Client()
        try:
            # FASE 1: Tools loop (hasta 3 iteraciones)
            current_history = self.history.copy()
            tool_iterations = 0

            while self.enable_tools and tool_iterations < 3 and not self._stop:
                self.status_update.emit(f"Analizando si necesita herramientas... (iter {tool_iterations+1})")
                try:
                    resp = client.chat(model=self.model, messages=current_history, tools=self.tools_def, stream=False, think=self.enable_think)
                except Exception as e:
                    # Ollama devolvió 500 (ej: tool calls malformados del modelo).
                    # Reintentar SIN tools para que el usuario obtenga respuesta.
                    self.status_update.emit(f"Herramientas no disponibles, respondiendo directo: {str(e)[:60]}")
                    tools_def_sin = self.tools_def
                    self.tools_def = []
                    try:
                        resp = client.chat(model=self.model, messages=current_history, tools=[], stream=False, think=self.enable_think)
                        msg = resp.get('message', {})
                        final_ans = msg.get('content', '')
                        self.final_answer.emit(final_ans, msg.get('thinking', ''))
                    except Exception as e2:
                        self.error_occurred.emit(f"Ollama error: {e2}")
                    finally:
                        self.tools_def = tools_def_sin
                    self.send_btn.setEnabled(True)
                    self.status_label.setText("Listo")
                    return
                msg = resp.get('message', {})
                tool_calls = msg.get('tool_calls', [])

                if tool_calls:
                    for tc in tool_calls:
                        func = tc.get('function', {})
                        name = func.get('name','')
                        args = func.get('arguments', {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except:
                                args = {"query": args}

                        self.tool_call_detected.emit(name, args)

                        executor = self.executors.get(name)
                        if executor:
                            try:
                                result = executor(**args) if args else executor()
                            except Exception as e:
                                result = f"Error ejecutando {name}: {e}"
                        else:
                            result = f"Tool {name} no encontrado"

                        self.tool_result_ready.emit(name, result)

                        current_history.append(msg)
                        current_history.append({"role": "tool", "content": str(result)})

                    tool_iterations += 1
                    continue
                else:
                    break

            # FASE 2: Streaming final con deteccion de think
            self.status_update.emit("Generando respuesta...")
            raw_accum = ""
            self._emitted_len = 0  # origen: solo emitimos lo nuevo desde la última emisión
            thinking_content = ""
            answer_content = ""
            has_think = False
            think_closed = False
            last_tool_result = ""

            for m in reversed(current_history):
                if m.get("role") == "tool":
                    last_tool_result = str(m.get("content", ""))
                    break

            stream = client.chat(model=self.model, messages=current_history, stream=True, think=self.enable_think)

            for chunk in stream:
                if self._stop:
                    break
                if chunk.get('done'):
                    break

                thinking_delta = chunk.get('message', {}).get('thinking', '')
                if thinking_delta and not has_think:
                    has_think = True
                    self.thinking_started.emit()
                if thinking_delta and has_think and not think_closed:
                    self.thinking_chunk.emit(thinking_delta[:2000])
                    continue

                delta = chunk.get('message', {}).get('content', '')
                if not delta:
                    continue

                raw_accum += delta

                if "<<thinking>>" in raw_accum and not has_think:
                    has_think = True
                    self.thinking_started.emit()

                if has_think and not think_closed:
                    if "</thinking>>" in raw_accum:
                        think_closed = True
                        m = re.search(r"<<thinking>>(.*?)</thinking>>", raw_accum, re.DOTALL)
                        if m:
                            thinking_content = m.group(1).strip()
                            answer_content = re.sub(r"<<thinking>>.*?</thinking>>", "", raw_accum, flags=re.DOTALL)
                            self.thinking_finished.emit(thinking_content)
                            if answer_content.strip():
                                self.chunk_received.emit(answer_content)
                        else:
                            parts = raw_accum.split("</thinking>>", 1)
                            thinking_content = parts[0].replace("<<thinking>>", "").strip()
                            self.thinking_finished.emit(thinking_content)
                            answer_content = parts[1] if len(parts) > 1 else ""
                            if answer_content.strip():
                                self.chunk_received.emit(answer_content)
                        
                        # IMPORTANTE: después de procesar thinking y emitir answer_content,
                        # saltar la emisión posterior de delta para evitar duplicación
                        continue
                    else:
                        think_part = raw_accum.split("<<thinking>>")[-1]
                        self.thinking_chunk.emit(think_part[:2000])
                else:
                    if not has_think:
                        self.chunk_received.emit(delta)
                        answer_content += delta

            if has_think:
                m = re.search(r"<<thinking>>.*?</thinking>>(.*)", raw_accum, re.DOTALL)
                final_ans = m.group(1).strip() if m else re.sub(r"<<thinking>>.*?</thinking>>", "", raw_accum, flags=re.DOTALL).strip()
                if not final_ans:
                    final_ans = answer_content.strip()
            else:
                final_ans = raw_accum.strip()

            if not final_ans and last_tool_result:
                final_ans = last_tool_result

            self.final_answer.emit(final_ans, thinking_content)

        except Exception as e:
            self.error_occurred.emit(str(e))

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
        self.chevron.setStyleSheet("color: #9aa0a6; font-size: 10px;")
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
        self.body.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
                color: #9aa0a6;
                font-size: 13px;
                line-height: 1.5;
                padding: 0 0 0 12px;
                font-family: "Inter", "Noto Sans", "Ubuntu", sans-serif;
            }
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
        self.chevron.setStyleSheet("color: #9aa0a6; font-size: 10px;")
        header.addWidget(self.chevron)

        self.label = QLabel("🔧 Herramientas")
        self.label.setStyleSheet("color: #9aa0a6; font-weight: 600; font-size: 11px;")
        header.addWidget(self.label)
        header.addStretch()

        self.header_widget = QFrame()
        self.header_widget.setLayout(header)
        self.header_widget.setCursor(Qt.PointingHandCursor)
        self.header_widget.mousePressEvent = lambda e: self.toggle()
        layout.addWidget(self.header_widget)

        # Cuerpo: filas de herramientas (oculto al inicio)
        self.body_widget = QFrame()
        self.body_widget.setStyleSheet("""
            QFrame {
                background: #1a1a1c;
                border: none;
                border-top: none;
                border-radius: 0 0 8px 8px;
            }
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
        row.setStyleSheet("""
            QFrame {
                background: transparent;
                border-bottom: 1px solid #272729;
                padding: 6px 12px;
            }
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
        name_lbl.setStyleSheet("color: #e5e5ea; font-weight: 600; font-size: 13px;")
        row_layout.addWidget(name_lbl)

        status_lbl = QLabel("ejecutando…")
        status_lbl.setStyleSheet("color: #9aa0a6; font-size: 11px; font-style: italic;")
        row_layout.addWidget(status_lbl)
        row_layout.addStretch()

        # Chevron inline al final de la fila
        row_chevron = QLabel("⌄")
        row_chevron.setFixedSize(12, 12)
        row_chevron.setStyleSheet("color: #9aa0a6; font-size: 9px;")
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
                entry["status_lbl"].setStyleSheet("color: #34c759; font-size: 11px; font-weight: 600;")
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
            detail.setStyleSheet("""
                QTextBrowser {
                    background: transparent;
                    border: none;
                    border-left: 2px solid #2a2c31;
                    border-radius: 0;
                    color: #e5e5ea;
                    font-size: 13px;
                    line-height: 1.5;
                    padding: 0 0 0 12px;
                    font-family: "Inter", "Noto Sans", "Ubuntu", sans-serif;
                }
                QTextBrowser a { color: #34c759; text-decoration: underline; }
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
            self.label.setStyleSheet("color: #ff453a; font-weight: 600; font-size: 11px;")
        else:
            self.label.setText("🔧 Herramientas completadas")
            self.label.setStyleSheet("color: #34c759; font-weight: 600; font-size: 11px;")

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
                entry["status_lbl"].setStyleSheet("color: #ff453a; font-size: 11px; font-weight: 600;")
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
        # Nivel 1: Header con avatar (estilo ChatGPT: avatar pequeño, sin nombre)
        # ================================================================
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        avatar = QLabel()
        avatar.setFixedSize(28, 28)
        avatar.setAlignment(Qt.AlignCenter)
        if role == "user":
            avatar.setText("👤")
            avatar.setStyleSheet("""
                QLabel {
                    background: #343541;
                    color: #ffffff;
                    border-radius: 14px;
                    font-size: 14px;
                }
            """)
            header.addStretch()
            header.addWidget(avatar)
            layout.addLayout(header)
        else:
            avatar.setText("🤖")
            avatar.setStyleSheet("""
                QLabel {
                    background: #10a37f;
                    color: #ffffff;
                    border-radius: 14px;
                    font-size: 14px;
                }
            """)

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
            self.bubble.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.bubble.setMinimumWidth(280)
            self.bubble.setStyleSheet("""
                QFrame#userBubble {
                    background: #3d4653;
                    border: none;
                    border-radius: 18px;
                }
            """)

            bubble_layout = QVBoxLayout(self.bubble)
            bubble_layout.setContentsMargins(14, 12, 14, 12)
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
                        name_lbl.setStyleSheet("color: #9aa0a6; font-size: 11px; font-weight: 600;")
                        bubble_layout.addWidget(name_lbl)
                    except:
                        pass

            self.text_browser = QTextBrowser()
            self.text_browser.setOpenExternalLinks(True)
            self.text_browser.setMarkdown(content or "")
            self.text_browser.setStyleSheet("""
                QTextBrowser {
                    background: transparent;
                    border: none;
                    color: #ffffff;
                    font-size: 14px;
                    line-height: 1.6;
                    padding: 0;
                    font-family: "Inter", "Noto Sans", "Ubuntu", sans-serif;
                }
                QTextBrowser a { color: #34c759; text-decoration: underline; }
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
            self.text_browser.setStyleSheet("""
                QTextBrowser {
                    background: transparent;
                    border: none;
                    color: #e5e5ea;
                    font-size: 15px;
                    line-height: 1.6;
                    padding: 0 0 12px 0;
                    font-family: "Inter", "Noto Sans", "Ubuntu", sans-serif;
                }
                QTextBrowser a { color: #34c759; text-decoration: underline; }
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
            copy_btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #9aa0a6;
                    border: none;
                    border-radius: 4px;
                    font-size: 14px;
                }
                QPushButton:hover { background: #1f2126; color: #ffffff; }
            """)

            retry_btn = QPushButton("♻")
            retry_btn.setFixedSize(24, 24)
            retry_btn.setToolTip("Regenerar respuesta")
            retry_btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #9aa0a6;
                    border: none;
                    border-radius: 4px;
                    font-size: 14px;
                }
                QPushButton:hover { background: #1f2126; color: #ffffff; }
            """)

            tts_btn = QPushButton("🔊")
            tts_btn.setFixedSize(24, 24)
            tts_btn.setToolTip("Leer respuesta en voz alta (TTS)")
            tts_btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #9aa0a6;
                    border: none;
                    border-radius: 4px;
                    font-size: 14px;
                }
                QPushButton:hover { background: #1f2126; color: #ffffff; }
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
        self.setStyleSheet("""
            QFrame {
                background: #16161a;
                border-bottom: 1px solid #2a2a30;
            }
            QLabel {
                color: #e0e0e0;
                font-size: 13px;
                font-weight: bold;
                padding-left: 12px;
            }
            QPushButton {
                background: transparent;
                color: #e0e0e0;
                border: none;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #2a2a30;
                border-radius: 6px;
            }
            QPushButton#closeBtn:hover {
                background: #4a1a1a;
                color: #ff6b6b;
            }
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


# ================= MAIN WINDOW =================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ollama GUI - Lubuntu Edition")
        self.setAcceptDrops(True)
        # Ventana sin borde nativo (barra de título personalizada)
        self.setWindowFlags(Qt.FramelessWindowHint)

        # Tamaño inicial dinámico basado en availableGeometry
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry()
        w = min(1150, int(avail.width() * 0.92))
        h = min(750, int(avail.height() * 0.92))
        self.resize(w, h)
        self.setMinimumSize(860, 520)

        self.move(
            avail.x() + (avail.width() - w) // 2,
            avail.y() + (avail.height() - h) // 2,
        )

        self.chat_history: List[Dict] = []
        self._load_memory()
        self.current_model = "llama3.1"
        self.models: List[str] = []
        self.attached_images: List[str] = []
        self.worker: Optional[OllamaWorker] = None
        self._answer_buffer: str = ""
        self._think_caps: Dict[str, bool] = {}

        # Cargar tools
        self.tools_def, self.executors = load_tools()
        print(f"Tools cargados: {list(self.executors.keys())}")

        # Pre-router por embeddings (Rama B - Fase 1)
        self.tool_router: Optional[ToolRouter] = None
        try:
            self.tool_router = ToolRouter()
            print(f"Pre-router listo (categorías: {list(self.tool_router.anchor_embeddings.keys())})")
        except Exception as e:
            print(f"⚠ Pre-router no disponible: {e}")

        # Orquestador de agentes (gate de autorización estructural)
        self.tools_map: dict = self.executors
        self.orch: Optional[Orchestrator] = None
        try:
            self.orch = Orchestrator(self.tools_map)
            self.orch.necesita_aprobacion.connect(self._pedir_aprobacion)
            self.orch.terminado.connect(self._mostrar_informe_agente)
            self.orch.error.connect(self._mostrar_error_agente)
            print("Orquestador listo")
        except Exception as e:
            print(f"⚠ Orquestador no disponible: {e}")

        # =====================================================================
        # ESTRUCTURA UNICA: MainWindow -> centralWidget -> QSplitter(2 widgets)
        # =====================================================================
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Barra de título personalizada
        self.title_bar = TitleBar(self)
        main_layout.addWidget(self.title_bar)

        # QSplitter con SOLO 2 widgets: sidebar y central
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(2)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background: #2a2a30;
                width: 2px;
            }
            QSplitter::handle:hover {
                background: #8ab4f8;
            }
        """)
        main_layout.addWidget(splitter, 1)

        # ---------------------------------------------------------------
        # 1. SIDEBAR: ancho fijo 280px, con QScrollArea interno
        # ---------------------------------------------------------------
        sidebar = QFrame()
        sidebar.setFixedWidth(280)
        sidebar.setStyleSheet("""
            QFrame {
                background: #16161a;
                border-right: 1px solid #2a2a30;
            }
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 16, 16, 16)
        sidebar_layout.setSpacing(16)

        app_title = QLabel("Ollama GUI")
        app_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #8ab4f8;")
        sidebar_layout.addWidget(app_title)

        self.new_chat_btn = QPushButton("＋ Nuevo Chat")
        self.new_chat_btn.setFixedHeight(36)
        self.new_chat_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a30;
                color: #e0e0e0;
                border: 1px solid #3a3a44;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #3a3a44;
                border-color: #8ab4f8;
            }
        """)
        self.new_chat_btn.clicked.connect(self.new_chat)
        sidebar_layout.addWidget(self.new_chat_btn)

        # Selector de modelo
        model_group = QFrame()
        model_group.setStyleSheet("""
            QFrame {
                background: #1a1a1e;
                border: 1px solid #2a2a30;
                border-radius: 8px;
            }
        """)
        model_layout = QVBoxLayout(model_group)
        model_layout.setContentsMargins(12, 10, 12, 10)
        model_layout.setSpacing(8)

        model_label = QLabel("Modelo")
        model_label.setStyleSheet("color: #8ab4f8; font-weight: bold; font-size: 12px;")
        model_layout.addWidget(model_label)

        self.model_combo = QComboBox()
        self.model_combo.setFixedHeight(32)
        self.model_combo.setStyleSheet("""
            QComboBox {
                background: #17181c;
                color: #e0e0e0;
                border: 1px solid #3a3a44;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background: #17181c;
                color: #e0e0e0;
                border: 1px solid #3a3a44;
                selection-background-color: #8ab4f8;
                selection-color: #000;
            }
        """)
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        model_layout.addWidget(self.model_combo)

        self.model_status = QLabel("Cargando modelos...")
        self.model_status.setStyleSheet("color: #888; font-size: 10px;")
        model_layout.addWidget(self.model_status)

        self.pull_model_btn = QPushButton("⬇️ Pull Modelo")
        self.pull_model_btn.setFixedHeight(30)
        self.pull_model_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a30;
                color: #e0e0e0;
                border: 1px solid #3a3a44;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover { background: #3a3a44; }
            QPushButton:disabled { background: #222228; color: #666; }
        """)
        self.pull_model_btn.clicked.connect(self.pull_model)
        model_layout.addWidget(self.pull_model_btn)

        sidebar_layout.addWidget(model_group)

        # Funciones automáticas
        func_group = QFrame()
        func_group.setStyleSheet("""
            QFrame {
                background: #1a1a1e;
                border: 1px solid #2a2a30;
                border-radius: 8px;
            }
        """)
        func_layout = QVBoxLayout(func_group)
        func_layout.setContentsMargins(12, 10, 12, 10)
        func_layout.setSpacing(8)

        func_label = QLabel("Funciones Automáticas")
        func_label.setStyleSheet("color: #8ab4f8; font-weight: bold; font-size: 12px;")
        func_layout.addWidget(func_label)

        self.web_search_check = QCheckBox("🌐 Web Search Auto")
        self.web_search_check.setChecked(True)
        self.web_search_check.setStyleSheet(self._checkbox_style())
        func_layout.addWidget(self.web_search_check)

        self.tools_check = QCheckBox("🔧 Tools Auto")
        self.tools_check.setChecked(True)
        self.tools_check.setStyleSheet(self._checkbox_style())
        func_layout.addWidget(self.tools_check)

        self.think_check = QCheckBox("🧠 Mostrar Pensamiento")
        self.think_check.setChecked(False)
        self.think_check.setStyleSheet(self._checkbox_style())
        func_layout.addWidget(self.think_check)

        self.vision_check = QCheckBox("👁 Vision (llava/gemma3)")
        self.vision_check.setChecked(True)
        self.vision_check.setStyleSheet(self._checkbox_style())
        func_layout.addWidget(self.vision_check)

        self.stt_check = QCheckBox("🎤 Dictado por voz (STT)")
        self.stt_check.setChecked(False)
        self.stt_check.setStyleSheet(self._checkbox_style())
        func_layout.addWidget(self.stt_check)

        self.tts_check = QCheckBox("🔊 Leer respuestas (TTS)")
        self.tts_check.setChecked(False)
        self.tts_check.setStyleSheet(self._checkbox_style())
        func_layout.addWidget(self.tts_check)

        sidebar_layout.addWidget(func_group)

        # Plugins / Tools
        tools_group = QFrame()
        tools_group.setStyleSheet("""
            QFrame {
                background: #1a1a1e;
                border: 1px solid #2a2a30;
                border-radius: 8px;
            }
        """)
        tools_layout = QVBoxLayout(tools_group)
        tools_layout.setContentsMargins(12, 10, 12, 10)
        tools_layout.setSpacing(8)

        tools_label = QLabel("Tools instalados")
        tools_label.setStyleSheet("color: #8ab4f8; font-weight: bold; font-size: 12px;")
        tools_layout.addWidget(tools_label)

        self.tools_list = QListWidget()
        self.tools_list.setMinimumHeight(140)
        self.tools_list.setStyleSheet("""
            QListWidget {
                background: #17181c;
                color: #e0e0e0;
                border: 1px solid #2a2a30;
                border-radius: 4px;
                font-size: 11px;
                outline: none;
            }
            QListWidget::item {
                padding: 6px 8px;
                border-bottom: 1px solid #2a2a30;
            }
            QListWidget::item:selected {
                background: #8ab4f8;
                color: #000;
            }
        """)
        self.tools_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tools_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.refresh_tools_list()
        tools_layout.addWidget(self.tools_list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.add_tool_btn = QPushButton("＋ Nuevo Tool")
        self.add_tool_btn.setFixedHeight(28)
        self.add_tool_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a30;
                color: #e0e0e0;
                border: 1px solid #3a3a44;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover { background: #3a3a44; }
        """)
        self.add_tool_btn.clicked.connect(self.create_new_tool)
        btn_row.addWidget(self.add_tool_btn)

        self.open_tools_folder_btn = QPushButton("📁")
        self.open_tools_folder_btn.setFixedSize(28, 28)
        self.open_tools_folder_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a30;
                color: #e0e0e0;
                border: 1px solid #3a3a44;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover { background: #3a3a44; }
        """)
        self.open_tools_folder_btn.clicked.connect(self.open_tools_folder)
        self.open_tools_folder_btn.setToolTip("Abrir carpeta tools")
        btn_row.addWidget(self.open_tools_folder_btn)

        tools_layout.addLayout(btn_row)
        sidebar_layout.addWidget(tools_group)

        sidebar_layout.addStretch()

        self.status_label = QLabel("Listo")
        self.status_label.setStyleSheet("color: #666; font-size: 11px; font-style: italic;")
        sidebar_layout.addWidget(self.status_label)

        # Sidebar dentro de QScrollArea
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sidebar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sidebar_scroll.setFrameShape(QFrame.NoFrame)
        sidebar_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        sidebar_scroll.setWidget(sidebar)
        splitter.addWidget(sidebar_scroll)

        # ---------------------------------------------------------------
        # 2. CENTRAL: QVBoxLayout con 3 filas (header, chat, composer)
        # ---------------------------------------------------------------
        central_panel = QFrame()
        central_panel.setStyleSheet("background: #17181c;")
        central_layout = QVBoxLayout(central_panel)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # 2a. Header pequeño de chat
        chat_header = QFrame()
        chat_header.setFixedHeight(44)
        chat_header.setStyleSheet("""
            QFrame {
                background: #16161a;
                border-bottom: 1px solid #2a2a30;
            }
        """)
        header_layout = QHBoxLayout(chat_header)
        header_layout.setContentsMargins(16, 0, 16, 0)
        header_layout.setSpacing(10)

        chat_title = QLabel("Chat")
        chat_title.setStyleSheet("color: #e0e0e0; font-size: 14px; font-weight: bold;")
        header_layout.addWidget(chat_title)
        header_layout.addStretch()

        central_layout.addWidget(chat_header)

        # 2b. ChatScrollArea con stretch 1, widgetResizable True, sin scrollbar horizontal
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setStyleSheet("border: none; background: #17181c;")

        self.chat_container_widget = ChatContainer()
        self.chat_container_widget.setStyleSheet("background: #17181c;")
        self.scroll.setWidget(self.chat_container_widget)
        central_layout.addWidget(self.scroll, 1)  # stretch 1

        # 2c. Composer con stretch 0, siempre visible abajo
        input_frame = QFrame()
        input_frame.setFixedHeight(110)
        input_frame.setStyleSheet("""
            QFrame {
                background: #16161a;
                border-top: 1px solid #2a2a30;
            }
        """)
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(16, 12, 16, 12)
        input_layout.setSpacing(10)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(10)

        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText("Escribe tu mensaje... Arrastra imágenes aquí o usa el clip")
        self.input_edit.setFixedHeight(56)
        self.input_edit.setStyleSheet("""
            QTextEdit {
                background: #17181c;
                color: #e0e0e0;
                border: 1px solid #3a3a44;
                border-radius: 22px;
                padding: 8px 16px;
                font-size: 13px;
                line-height: 1.4;
            }
            QTextEdit:focus {
                border-color: #8ab4f8;
            }
        """)
        # Event filter: Enter envía, Shift+Enter nueva línea
        self.input_edit.installEventFilter(self)
        input_row.addWidget(self.input_edit, 1)

        btns_col = QVBoxLayout()
        btns_col.setSpacing(6)

        top_btns = QHBoxLayout()
        top_btns.setSpacing(6)

        self.attach_btn = QPushButton("📎")
        self.attach_btn.setFixedSize(36, 36)
        self.attach_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a30;
                color: #e0e0e0;
                border: none;
                border-radius: 18px;
                font-size: 16px;
            }
            QPushButton:hover { background: #3a3a44; }
        """)
        self.attach_btn.clicked.connect(self.attach_image)
        self.attach_btn.setToolTip("Adjuntar imagen para visión")
        top_btns.addWidget(self.attach_btn)

        self.mic_btn = QPushButton("🎤")
        self.mic_btn.setFixedSize(36, 36)
        self.mic_btn.setCheckable(True)
        self.mic_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a30;
                color: #e0e0e0;
                border: none;
                border-radius: 18px;
                font-size: 16px;
            }
            QPushButton:checked {
                background: #ff6b6b;
                color: #fff;
            }
            QPushButton:hover { background: #3a3a44; }
        """)
        self.mic_btn.clicked.connect(self.toggle_dictation)
        self.mic_btn.setToolTip("Dictado por voz (STT)")
        self.mic_btn.hide()
        top_btns.addWidget(self.mic_btn)

        self.clear_images_btn = QPushButton("🗑️")
        self.clear_images_btn.setFixedSize(36, 36)
        self.clear_images_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a30;
                color: #e0e0e0;
                border: none;
                border-radius: 18px;
                font-size: 16px;
            }
            QPushButton:hover { background: #3a3a44; }
        """)
        self.clear_images_btn.clicked.connect(lambda: self.clear_attached_images())
        self.clear_images_btn.hide()
        self.clear_images_btn.setToolTip("Limpiar imágenes adjuntas")
        top_btns.addWidget(self.clear_images_btn)

        top_btns.addStretch()
        btns_col.addLayout(top_btns)

        self.send_btn = QPushButton("Enviar ▶")
        self.send_btn.setFixedSize(140, 36)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: #8ab4f8;
                color: #000;
                font-weight: bold;
                font-size: 13px;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background: #a0c4ff; }
            QPushButton:disabled {
                background: #2a2a30;
                color: #666;
            }
        """)
        self.send_btn.clicked.connect(self.send_message)
        btns_col.addWidget(self.send_btn)

        input_row.addLayout(btns_col)
        input_layout.addLayout(input_row)

        self.images_label = QLabel("")
        self.images_label.setStyleSheet("color: #8ab4f8; font-size: 11px; font-weight: bold;")
        self.images_label.hide()
        input_layout.addWidget(self.images_label)

        central_layout.addWidget(input_frame)

        splitter.addWidget(central_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # Shortcuts
        self.input_edit.textChanged.connect(self.on_input_changed)

        # Cargar modelos al inicio
        self.load_models()

        # Mensaje bienvenida
        welcome = MessageBubble("assistant", "¡Hola! **Ollama GUI para Lubuntu**\n\n- 🌐 Web search automático\n- 🧠 Pensamiento visible\n- 👁 Vision drag & drop\n- 🔧 Sistema de plugins en carpeta tools/\n\nPrueba arrastrar una imagen o preguntar: *¿qué pasó hoy en México?*", [])
        welcome.thinking_block.hide()
        welcome.tool_block.hide()
        welcome.icon_container.hide()
        self.chat_container_widget.add_message_widget(welcome)

        # Verificar disponibilidad de STT (después de crear la UI)
        self.stt_available = False
        try:
            import speech_recognition as sr
            sr.Microphone()
            self.stt_available = True
        except Exception:
            self.stt_available = False
        self.mic_btn.setVisible(self.stt_available and self.stt_check.isChecked())

    @staticmethod
    def _checkbox_style():
        return """
            QCheckBox {
                color: #e0e0e0;
                font-size: 12px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                background: #17181c;
                border: 1px solid #3a3a44;
                border-radius: 4px;
            }
            QCheckBox::indicator:checked {
                background: #8ab4f8;
                border-color: #8ab4f8;
            }
            QCheckBox::indicator:checked::hover {
                background: #a0c4ff;
            }
        """

    def refresh_tools_list(self):
        self.tools_list.clear()
        for name in self.executors.keys():
            item = QListWidgetItem(f"✓ {name}")
            item.setToolTip(name)
            self.tools_list.addItem(item)
        for f in (SCRIPT_DIR / "tools").glob("*.py"):
            if f.name.startswith("_") or f.name == "__init__.py":
                continue
            if f.stem not in self.executors:
                item = QListWidgetItem(f"✗ {f.stem} (error)")
                item.setToolTip(f.stem)
                self.tools_list.addItem(item)

    def modelo_piensa(self, nombre: str) -> bool:
        """Devuelve True si el modelo expone capacidad de thinking ante Ollama."""
        if nombre not in self._think_caps:
            try:
                r = requests.post("http://localhost:11434/api/show",
                                  json={"name": nombre}, timeout=10)
                caps = (r.json() or {}).get("capabilities") or []
                self._think_caps[nombre] = "thinking" in caps
            except Exception:
                self._think_caps[nombre] = False
        return self._think_caps[nombre]

    def load_models(self):
        if ollama is None:
            self.model_status.setText("ollama no instalado")
            return
        try:
            client = ollama.Client()
            data = client.list()
            models = [m['name'] if isinstance(m, dict) else getattr(m, 'model', str(m)) for m in data.get('models',[])]
            self.models = models
            self.model_combo.clear()
            self.model_combo.addItems(models)
            if models:
                self.current_model = models[0]
                v = "👁 Vision" if is_vision_model(self.current_model) else "💬 Texto"
                self.model_status.setText(f"{v} | {len(models)} modelos")
        except Exception as e:
            self.model_status.setText(f"Error: {e} - ollama serve?")

    def on_model_changed(self, name: str):
        if name:
            self.current_model = name
            v = "👁 Vision" if is_vision_model(name) else "💬 Texto"
            self.status_label.setText(f"Modelo: {name} | {v}")

    def pull_model(self):
        if not self.current_model:
            return
        self.pull_model_btn.setEnabled(False)
        self.pull_model_btn.setText("⬇️ Descargando...")
        self.status_label.setText(f"Descargando {self.current_model}...")

        def _do_pull():
            try:
                import ollama
                client = ollama.Client()
                for progress in client.pull(self.current_model, stream=True):
                    pass
                self.pull_model_btn.setEnabled(True)
                self.pull_model_btn.setText("⬇️ Pull Modelo")
                self.status_label.setText(f"Modelo {self.current_model} listo")
                self.load_models()
            except Exception as e:
                self.pull_model_btn.setEnabled(True)
                self.pull_model_btn.setText("⬇️ Pull Modelo")
                self.status_label.setText(f"Error pull: {e}")
                QMessageBox.critical(self, "Error Pull", f"No se pudo descargar {self.current_model}:\n{e}")

        threading.Thread(target=_do_pull, daemon=True).start()

    def on_input_changed(self):
        pass

    def keyPressEvent(self, event):
        if event.key() == 16777220 and event.modifiers() == Qt.ShiftModifier:
            self.input_edit.insertPlainText("\n")
        elif event.key() == 16777220 and not event.modifiers() & Qt.ShiftModifier:
            if self.input_edit.hasFocus():
                self.send_message()
                return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if obj is self.input_edit and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Return or key == Qt.Key_Enter:
                if event.modifiers() & Qt.ShiftModifier:
                    # Shift+Enter: nueva línea, dejar que QTextEdit lo procese
                    return False
                else:
                    # Enter: enviar mensaje
                    self.send_message()
                    return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        for url in urls:
            path = url.toLocalFile()
            if Path(path).suffix.lower() in VISION_EXTS:
                self.attached_images.append(path)
        self.update_attached_label()
        self.status_label.setText(f"📎 {len(self.attached_images)} imagen(es) adjunta(s)")

    def attach_image(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Seleccionar imagen", str(Path.home()), "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        for f in files:
            self.attached_images.append(f)
        self.update_attached_label()

    def update_attached_label(self):
        if self.attached_images:
            self.clear_images_btn.show()
            self.clear_images_btn.setText(f"🗑️ {len(self.attached_images)}")
            names = ", ".join([Path(p).name for p in self.attached_images])
            self.images_label.setText(f"📎 {names}")
            self.images_label.show()
            self.status_label.setText(f"📎 {len(self.attached_images)} imagen(es) adjunta(s)")
        else:
            self.clear_images_btn.hide()
            self.images_label.hide()

    def clear_attached_images(self):
        self.attached_images = []
        self.update_attached_label()
        self.status_label.setText("Imágenes limpiadas")

    def new_chat(self):
        self.chat_history = []
        while self.chat_container_widget.layout.count() > 1:
            item = self.chat_container_widget.layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.status_label.setText("Nuevo chat")

    def open_tools_folder(self):
        import subprocess
        tools_path = str((SCRIPT_DIR / "tools").absolute())
        try:
            subprocess.Popen(["xdg-open", tools_path])
        except:
            QMessageBox.information(self, "Carpeta tools", f"Abre manualmente: {tools_path}")

    def create_new_tool(self):
        from PySide6.QtWidgets import QDialog, QFormLayout, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Crear Nuevo Tool")
        dlg.setFixedSize(400, 200)
        dlg.setStyleSheet("""
            QDialog { background: #16161a; }
            QLabel { color: #e0e0e0; font-size: 12px; }
            QLineEdit {
                background: #17181c;
                color: #e0e0e0;
                border: 1px solid #3a3a44;
                border-radius: 4px;
                padding: 6px;
                font-size: 12px;
            }
            QPushButton {
                background: #8ab4f8;
                color: #000;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 12px;
            }
            QPushButton:hover { background: #a0c4ff; }
        """)
        layout = QFormLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        name_input = QLineEdit()
        name_input.setPlaceholderText("mi_tool")
        desc_input = QLineEdit()
        desc_input.setPlaceholderText("Qué hace tu tool")
        layout.addRow("Nombre de función:", name_input)
        layout.addRow("Descripción:", desc_input)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec():
            name = name_input.text().strip()
            desc = desc_input.text().strip() or "Tool personalizado"
            if not name:
                return
            import re as _re
            if not _re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
                QMessageBox.warning(self, "Nombre inválido", "El nombre solo puede contener letras, números y guion bajo, y debe iniciar con letra o guion bajo.")
                return
            template_path = SCRIPT_DIR / "tools" / "_template_new_tool.py"
            new_path = SCRIPT_DIR / "tools" / f"{name}.py"
            if template_path.exists():
                content = template_path.read_text()
                content = content.replace("mi_tool", name).replace("Descripción de lo que hace tu tool", desc)
                new_path.write_text(content)
                QMessageBox.information(self, "Tool creado", f"Creado {new_path}\nEdita el archivo para implementar execute() y reinicia la app.")
                self.tools_def, self.executors = load_tools()
                self.refresh_tools_list()
            else:
                QMessageBox.warning(self, "Error", "No se encontró plantilla")

    def toggle_dictation(self):
        if not self.stt_available:
            QMessageBox.warning(self, "STT no disponible",
                "El reconocimiento de voz no está disponible.\n"
                "Instala dependencias:\n"
                "  sudo apt install portaudio19-dev python3-pyaudio\n"
                "  pip install pyaudio speechrecognition")
            self.mic_btn.setChecked(False)
            return

        if self.mic_btn.isChecked():
            self.mic_btn.setText("⏹️")
            self.status_label.setText("🎤 Escuchando... Habla ahora")
            QApplication.processEvents()

            import threading
            def _listen():
                try:
                    result = self.executors.get("listen")
                    if result:
                        text = result()
                        if text and not text.startswith("Error STT"):
                            self.input_edit.setPlainText(text)
                            self.status_label.setText("Dictado completado")
                        else:
                            self.status_label.setText(str(text)[:80])
                    else:
                        self.status_label.setText("STT no disponible")
                except Exception as e:
                    self.status_label.setText(f"Error STT: {e}")
                finally:
                    self.mic_btn.setChecked(False)
                    self.mic_btn.setText("🎤")

            threading.Thread(target=_listen, daemon=True).start()
        else:
            self.mic_btn.setText("🎤")
            self.status_label.setText("Listo")

    def speak_response(self, text: str):
        if not self.tts_check.isChecked():
            return
        try:
            result = self.executors.get("speak")
            if result:
                result(text=text)
            else:
                QMessageBox.warning(self, "TTS no disponible", "Motor TTS no cargado")
        except Exception as e:
            QMessageBox.warning(self, "Error TTS", str(e))

    def _load_memory(self):
        """Carga el historial de chat desde disco si existe."""
        try:
            if MEMORY_FILE.exists():
                with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.chat_history = data
                    print(f"Memoria cargada: {len(self.chat_history)} mensajes desde {MEMORY_FILE}")
        except Exception as e:
            print(f"⚠ No se pudo cargar la memoria persistente: {e}")
            self.chat_history = []

    def _save_memory(self):
        """Guarda el historial de chat en disco."""
        try:
            _ensure_memory_dir()
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.chat_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠ No se pudo guardar la memoria persistente: {e}")

    def send_message(self):
        text = self.input_edit.toPlainText().strip()
        if not text and not self.attached_images:
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Espera", "Ya estoy generando respuesta")
            return

        user_widget = MessageBubble("user", text or "(solo imagen)", self.attached_images.copy())
        self.chat_container_widget.add_message_widget(user_widget)

        user_dict = {"role": "user", "content": text}
        if self.attached_images and self.vision_check.isChecked():
            b64_list = []
            for p in self.attached_images:
                b64 = encode_image(p)
                if b64:
                    b64_list.append(b64)
            if b64_list:
                user_dict["images"] = b64_list

        self.chat_history.append(user_dict)
        self._save_memory()
        self.input_edit.clear()
        attached_copy = self.attached_images.copy()
        self.attached_images = []
        self.update_attached_label()

        enable_tools = self.tools_check.isChecked()
        enable_think = self.think_check.isChecked() and self.modelo_piensa(self.current_model)

        # Pre-router: filtrar tools según el mensaje del usuario
        route_defs = self.tools_def
        route_execs = self.executors
        if self.tool_router is not None and enable_tools:
            try:
                route_defs = self.tool_router.route(text)
                route_execs = {k: v for k, v in self.executors.items()
                               if k in {d.get("function", {}).get("name") for d in route_defs}}
                print(f"Pre-router: {len(route_defs)} tools de {len(self.tools_def)} totales")
            except Exception as e:
                print(f"⚠ Pre-router falló, usando todas las tools: {e}")

        # Inyectar system prompt al inicio del historial si no está ya
        history_with_system = []
        if not any(m.get("role") == "system" for m in self.chat_history):
            history_with_system.append({"role": "system", "content": SYSTEM_PROMPT})
        history_with_system.extend(self.chat_history)

        assistant_widget = MessageBubble("assistant", "", [], enable_think=enable_think)
        self.chat_container_widget.add_message_widget(assistant_widget)
        self.current_assistant_widget = assistant_widget
        self.scroll_to_bottom()

        # Limpieza de huérfanos del turno anterior (E1: widgets congelados)
        prev = getattr(self, "_prev_assistant_widget", None)
        if prev is not None:
            for bloque in ("thinking_block", "tool_block"):
                w = getattr(prev, bloque, None)
                if w is not None:
                    try:
                        w.hide()
                    except Exception:
                        pass
        self._prev_assistant_widget = assistant_widget

        self.worker = OllamaWorker(self.current_model, history_with_system, route_defs, route_execs, enable_tools=enable_tools, enable_think=enable_think)
        self.worker.chunk_received.connect(self.on_chunk)
        self.worker.thinking_chunk.connect(self.on_thinking_chunk)
        self.worker.thinking_started.connect(self.on_thinking_started)
        self.worker.thinking_finished.connect(self.on_thinking_finished)
        self.worker.tool_call_detected.connect(self.on_tool_call)
        self.worker.tool_result_ready.connect(self.on_tool_result)
        self.worker.final_answer.connect(self.on_final_answer)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.status_update.connect(lambda s: self.status_label.setText(s))
        self.worker.finished.connect(lambda: self.send_btn.setEnabled(True))

        self.send_btn.setEnabled(False)
        self.worker.start()

    def scroll_to_bottom(self, force=False):
        sb = self.scroll.verticalScrollBar()
        if force or sb.value() >= sb.maximum() - 80:
            a = QPropertyAnimation(sb, b"value")
            a.setDuration(120)
            a.setEndValue(sb.maximum())
            self._sb_anim = a
            a.start()
        else:
            sb.setValue(sb.maximum())

    @Slot(str)
    def on_chunk(self, delta: str):
        trace(f"WORKER_CHUNK len={len(delta)} preview={delta[:40]!r}")
        if hasattr(self, 'current_assistant_widget'):
            self._answer_buffer += delta
            self.current_assistant_widget.appendAnswer(delta)
            self.scroll_to_bottom()

    @Slot(str)
    def on_thinking_chunk(self, text: str):
        if hasattr(self, 'current_assistant_widget'):
            if self.think_check.isChecked():
                self.current_assistant_widget.thinking_block.show()
                self.current_assistant_widget.thinking_block.update_content(text[:2000])
            self.scroll_to_bottom()

    @Slot()
    def on_thinking_started(self):
        if hasattr(self, 'current_assistant_widget'):
            if self.think_check.isChecked():
                self.current_assistant_widget.thinking_block.start()
            self.status_label.setText("🧠 Pensando...")

    @Slot(str)
    def on_thinking_finished(self, text: str):
        if hasattr(self, 'current_assistant_widget'):
            self.current_assistant_widget.thinking_block.finish(text)
            self.status_label.setText("💭 Pensamiento completado")

    @Slot(str, dict)
    def on_tool_call(self, name: str, args: dict):
        if hasattr(self, 'current_assistant_widget'):
            self.current_assistant_widget.tool_block.add_call(name, args)
            self.scroll_to_bottom()

    @Slot(str, str)
    def on_tool_result(self, name: str, result: str):
        if hasattr(self, 'current_assistant_widget'):
            self.current_assistant_widget.tool_block.add_result(name, result)
            self.scroll_to_bottom()

    @Slot(str, str)
    def on_final_answer(self, answer: str, thinking: str):
        trace(f"on_final_answer answer_len={len(answer or '')} thinking_len={len(thinking or '')}")
        # Si el modelo devolvió un plan JSON del agente, enrutar al orquestador
        if self.orch is not None:
            try:
                plan = json.loads(answer)
                if isinstance(plan, dict) and "pasos" in plan:
                    self.orch.ejecutar(answer)
                    self.status_label.setText("Agente: plan recibido, ejecutando...")
                    return
            except (json.JSONDecodeError, TypeError):
                pass
        # Modelo primero: historial siempre se guarda, pase lo que pase en la vista
        if hasattr(self, 'current_assistant_widget'):
            self.chat_history.append({"role": "assistant", "content": answer})
            self._save_memory()
            try:
                self.current_assistant_widget.finishAnswer(answer, thinking)
                self.current_assistant_widget.showTTS()
            except Exception:
                import traceback
                traceback.print_exc()
                self.status_label.setText("Error al renderizar respuesta")
        # Vista nunca bloquea el turno: el botón siempre se habilita
        self.send_btn.setEnabled(True)
        self.status_label.setText("Listo")
        self.scroll_to_bottom()

    @Slot(str)
    def on_error(self, err: str):
        QMessageBox.critical(self, "Error Ollama", f"{err}\n\nVerifica que 'ollama serve' esté corriendo y el modelo exista.\nollama pull {self.current_model}")
        self.send_btn.setEnabled(True)
        self.status_label.setText(f"Error: {err[:50]}")

    # ---------- Orquestador: gate de autorización ----------
    @Slot(int, dict, str)
    def _pedir_aprobacion(self, idx: int, paso: dict, preview: str):
        """Diálogo de aprobación para pasos de MUTACIÓN."""
        btn = QMessageBox.question(
            self,
            "Autorizar operación de escritorio",
            f"Paso {idx + 1}: {paso.get('tool')}\n\n{preview}\n\n¿Autorizas?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        self.orch.resume(btn == QMessageBox.Yes)

    @Slot(str)
    def _mostrar_informe_agente(self, informe: str):
        """Muestra el informe final del orquestador como burbuja de asistente."""
        widget = MessageBubble("assistant", informe, [], enable_think=False)
        self.chat_container_widget.add_message_widget(widget)
        self.current_assistant_widget = widget
        self.chat_history.append({"role": "assistant", "content": informe})
        self._save_memory()
        self.scroll_to_bottom()
        self.send_btn.setEnabled(True)
        self.status_label.setText("Agente: plan completado")

    @Slot(int, str)
    def _mostrar_error_agente(self, idx: int, motivo: str):
        """Muestra un error del orquestador como burbuja de asistente."""
        widget = MessageBubble("assistant", f"⚠️ Error en paso {idx + 1}: {motivo}", [], enable_think=False)
        self.chat_container_widget.add_message_widget(widget)
        self.current_assistant_widget = widget
        self.chat_history.append({"role": "assistant", "content": f"Error en paso {idx + 1}: {motivo}"})
        self._save_memory()
        self.scroll_to_bottom()
        self.send_btn.setEnabled(True)
        self.status_label.setText("Agente: error")

    # ---------- Ayuda: añadir burbuja de asistente desde cualquier contexto ----------
    def _agregar_burbuja_asistente(self, texto: str, enable_think: bool = False):
        widget = MessageBubble("assistant", texto, [], enable_think=enable_think)
        self.chat_container_widget.add_message_widget(widget)
        self.current_assistant_widget = widget
        self.chat_history.append({"role": "assistant", "content": texto})
        self._save_memory()
        self.scroll_to_bottom()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    from PySide6.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(14,14,16))
    palette.setColor(QPalette.WindowText, QColor(224,224,224))
    palette.setColor(QPalette.Base, QColor(26,26,30))
    palette.setColor(QPalette.AlternateBase, QColor(14,14,16))
    palette.setColor(QPalette.ToolTipBase, QColor(255,255,255))
    palette.setColor(QPalette.ToolTipText, QColor(0,0,0))
    palette.setColor(QPalette.Text, QColor(224,224,224))
    palette.setColor(QPalette.Button, QColor(42,42,48))
    palette.setColor(QPalette.ButtonText, QColor(224,224,224))
    palette.setColor(QPalette.BrightText, QColor(255,0,0))
    palette.setColor(QPalette.Link, QColor(138,180,248))
    palette.setColor(QPalette.Highlight, QColor(138,180,248))
    palette.setColor(QPalette.HighlightedText, QColor(0,0,0))
    app.setPalette(palette)
    app.setFont(QFont("Inter", 10))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()