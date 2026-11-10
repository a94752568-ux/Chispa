import sys
import time
import os
import re
import json
import base64
import threading
import requests
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

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
except Exception:
    ollama = None

from common import trace
import memoria  # persistencia del historial del chat
import theme  # paleta centralizada "estilo Vibe"
from worker import OllamaWorker
from widgets import ThinkingBlockWidget, ToolBlockWidget, MessageBubble, ChatContainer, TitleBar


# Tools registry - robusto con fallback
try:
    from tools import load_tools, MUTACIONES
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

    # Fallback: mismo set de mutaciones que tools/__init__.py (MUTACIONES).
    # Si cambia la lista ahí, actualizarla aquí también.
    MUTACIONES = {"write_desktop", "organize_files", "db_writer", "move_file"}



VISION_MODELS = ["llava", "bakllava", "gemma3", "qwen2-vl", "qwen2.5-vl", "llama3.2-vision", "minicpm-v", "moondream", "vision"]
VISION_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Tools interactivas propiedad de la GUI: sus executors alimentan los botones
# 🔊 (TTS) y 🎤 (STT), pero el modelo NO debe poder invocarlas — listen
# bloquearía el worker esperando audio del micrófono y speak sintetizaría
# minutos de audio en medio del turno. Se filtran de tools_def SIEMPRE.
GUI_ONLY_TOOLS = {"speak", "listen"}

# ================================================================
# System prompt inyectado en cada llamada al modelo
# ================================================================
SYSTEM_PROMPT = """Identidad: eres Chispa, un asistente de escritorio LOCAL que corre en la computadora del usuario, sin nube. Tienes herramientas reales que llegan como funciones en el contexto de cada turno: buscar archivos por nombre (find_files), leer (read_file), crear documentos (write_desktop), mover (move_file), borrar a papelera (delete_file), organizar carpetas (organize_files), notas, búsqueda en documentos propios (rag_search), clima, hora, calculadora, búsqueda web, OSINT, git, contenedores y monitor del sistema, además de un agente de escritorio para planes multi-paso con autorización del usuario.

Cuando te pregunten quién eres o qué puedes hacer, describe SOLO estas capacidades reales y las herramientas visibles en este turno, por su nombre. NUNCA inventes listas de capacidades, productos, fechas de corte ni personalidades.

Idioma: respondes SIEMPRE en español, el idioma del usuario, salvo que pida explícitamente otro idioma. Si el usuario escribe en español, respondes en español. No uses chino ni inglés salvo que se te pida. Si herramientas devuelven texto en otro idioma, traduce o explica en español.

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



def encode_image(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None

# ================= MAIN WINDOW =================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chispa - Asistente local")
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
        self.chat_id: str = ""
        self._chat_title: str = "Nuevo chat"
        self.chats: List[Dict] = []
        self.current_model = "llama3.1"
        self.models: List[str] = []
        self.attached_images: List[str] = []
        self.worker: Optional[OllamaWorker] = None
        self.settings_dialog = None
        self._answer_buffer: str = ""
        self._stop_requested: bool = False
        self._speaking: bool = False
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
        # Vive en su propio QThread: las tools no congelan la GUI.
        self.tools_map: dict = self.executors
        self.orch: Optional[Orchestrator] = None
        self.orch_thread: Optional[QThread] = None
        try:
            self.orch_thread = QThread(self)
            self.orch = Orchestrator(self.tools_map)
            self.orch.moveToThread(self.orch_thread)
            self.orch_thread.start()
            self.orch.necesita_aprobacion.connect(self._pedir_aprobacion)
            self.orch.terminado.connect(self._mostrar_informe_agente)
            self.orch.error.connect(self._mostrar_error_agente)
            print("Orquestador listo (QThread dedicado)")
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
        splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {theme.BORDER_SOFT};
                width: 2px;
            }}
            QSplitter::handle:hover {{
                background: {theme.ACCENT};
            }}
        """)
        main_layout.addWidget(splitter, 1)

        # ---------------------------------------------------------------
        # 1. SIDEBAR: ancho fijo 280px, con QScrollArea interno
        # ---------------------------------------------------------------
        sidebar = QFrame()
        sidebar.setFixedWidth(280)
        sidebar.setStyleSheet(f"""
            QFrame {{
                background: {theme.BG_SIDEBAR};
                border-right: 1px solid {theme.BORDER_SOFT};
            }}
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 16, 16, 16)
        sidebar_layout.setSpacing(14)

        app_title = QLabel("✦ Chispa")
        app_title.setStyleSheet(f"font-size: 17px; font-weight: 800; color: {theme.ACCENT};")
        sidebar_layout.addWidget(app_title)

        self.new_chat_btn = QPushButton("＋ Nuevo Chat")
        self.new_chat_btn.setFixedHeight(38)
        self.new_chat_btn.setCursor(Qt.PointingHandCursor)
        self.new_chat_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 {theme.ACCENT_HOVER}, stop:1 {theme.ACCENT});
                color: {theme.TEXT_ON_ACCENT};
                border: none;
                border-radius: 10px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 {theme.ACCENT_BRIGHT}, stop:1 {theme.ACCENT_HOVER});
            }}
            QPushButton:pressed {{ background: {theme.ACCENT_ACTIVE}; }}
        """)
        self.new_chat_btn.clicked.connect(self.new_chat)
        sidebar_layout.addWidget(self.new_chat_btn)

        # Conversaciones (multi-chat persistente)
        chats_label = QLabel("CONVERSACIONES")
        chats_label.setStyleSheet(f"color: {theme.TEXT_SECOND}; font-weight: 700; font-size: 11px;")
        sidebar_layout.addWidget(chats_label)

        self.chats_list = QListWidget()
        self.chats_list.setMinimumHeight(96)
        self.chats_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chats_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chats_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                color: {theme.TEXT};
                font-size: 12px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 8px 10px;
                border-radius: 8px;
                margin: 1px 4px 1px 0px;
                border-left: 2px solid transparent;
            }}
            QListWidget::item:hover {{
                background: {theme.BG_HOVER};
            }}
            QListWidget::item:selected {{
                background: {theme.ACCENT_TINT};
                color: {theme.TEXT};
                border-left: 2px solid {theme.ACCENT};
            }}
        """)
        self.chats_list.itemClicked.connect(self._switch_chat)
        self.chats_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chats_list.customContextMenuRequested.connect(self._chat_context_menu)
        sidebar_layout.addWidget(self.chats_list, 1)

        sidebar_layout.addStretch()

        self.status_label = QLabel("Listo")
        self.status_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px; font-style: italic;")
        sidebar_layout.addWidget(self.status_label)

        # Ajustes en diálogo: todo lo técnico vive aquí, como en Vibe
        self.settings_btn = QPushButton("⚙ Ajustes")
        self.settings_btn.setFixedHeight(34)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {theme.TEXT_SECOND};
                border: 1px solid {theme.BORDER};
                border-radius: 10px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border-color: {theme.ACCENT};
                color: {theme.TEXT};
                background: {theme.ACCENT_TINT};
            }}
        """)
        self.settings_btn.clicked.connect(self._open_settings)
        sidebar_layout.addWidget(self.settings_btn)

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
        central_panel.setStyleSheet(f"background: {theme.BG_WINDOW};")
        central_layout = QVBoxLayout(central_panel)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # 2a. Header pequeño de chat (título de la conversación activa)
        chat_header = QFrame()
        chat_header.setFixedHeight(44)
        chat_header.setStyleSheet(f"""
            QFrame {{
                background: {theme.BG_SIDEBAR};
                border-bottom: 1px solid {theme.BORDER_SOFT};
            }}
        """)
        header_layout = QHBoxLayout(chat_header)
        header_layout.setContentsMargins(16, 0, 16, 0)
        header_layout.setSpacing(10)

        self.chat_title_label = QLabel("Chat")
        self.chat_title_label.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px; font-weight: bold;")
        header_layout.addWidget(self.chat_title_label)
        header_layout.addStretch()

        central_layout.addWidget(chat_header)

        # 2b. ChatScrollArea con stretch 1, widgetResizable True, sin scrollbar horizontal
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setStyleSheet(f"border: none; background: {theme.BG_WINDOW};")

        self.chat_container_widget = ChatContainer()
        self.chat_container_widget.setStyleSheet(f"background: {theme.BG_WINDOW};")
        self.scroll.setWidget(self.chat_container_widget)
        central_layout.addWidget(self.scroll, 1)  # stretch 1

        # 2c. Composer estilo Vibe: contenedor redondeado con input e iconos
        input_frame = QFrame()
        input_frame.setStyleSheet(f"QFrame {{ background: {theme.BG_WINDOW}; border: none; }}")
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(16, 8, 16, 12)
        input_layout.setSpacing(6)

        composer = QFrame()
        composer.setObjectName("composer")
        composer.setStyleSheet(f"""
            QFrame#composer {{
                background: {theme.BG_ELEVATED};
                border: 1px solid {theme.BORDER};
                border-radius: 24px;
            }}
            QFrame#composer:hover {{
                border-color: {theme.ACCENT};
            }}
        """)
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(0, 0, 0, 0)
        composer_layout.setSpacing(0)

        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText("Escribe tu mensaje… (Enter envía · Shift+Enter salto de línea · arrastra imágenes)")
        self.input_edit.setFixedHeight(58)
        self.input_edit.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                border: none;
                color: {theme.TEXT};
                font-size: 14px;
                line-height: 1.4;
                padding: 12px 18px 6px 18px;
                font-family: {theme.FONT_STACK};
            }}
        """)
        # Event filter: Enter envía, Shift+Enter nueva línea
        self.input_edit.installEventFilter(self)
        composer_layout.addWidget(self.input_edit)

        # Fila inferior del composer: iconos a la izquierda, enviar a la derecha
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(8, 0, 8, 8)
        bottom_row.setSpacing(2)

        self.attach_btn = QPushButton("📎")
        self.attach_btn.setFixedSize(32, 32)
        self.attach_btn.setCursor(Qt.PointingHandCursor)
        self.attach_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {theme.TEXT_SECOND};
                border: none;
                border-radius: 16px;
                font-size: 15px;
            }}
            QPushButton:hover {{ background: {theme.BG_HOVER}; color: {theme.TEXT}; }}
        """)
        self.attach_btn.clicked.connect(self.attach_image)
        self.attach_btn.setToolTip("Adjuntar imagen para visión")
        bottom_row.addWidget(self.attach_btn)

        self.mic_btn = QPushButton("🎤")
        self.mic_btn.setFixedSize(32, 32)
        self.mic_btn.setCheckable(True)
        self.mic_btn.setCursor(Qt.PointingHandCursor)
        self.mic_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {theme.TEXT_SECOND};
                border: none;
                border-radius: 16px;
                font-size: 15px;
            }}
            QPushButton:hover {{ background: {theme.BG_HOVER}; color: {theme.TEXT}; }}
            QPushButton:checked {{
                background: {theme.ERROR};
                color: #fff;
            }}
        """)
        self.mic_btn.clicked.connect(self.toggle_dictation)
        self.mic_btn.setToolTip("Dictado por voz (STT)")
        self.mic_btn.hide()
        bottom_row.addWidget(self.mic_btn)

        self.clear_images_btn = QPushButton("🗑️")
        self.clear_images_btn.setFixedSize(32, 32)
        self.clear_images_btn.setCursor(Qt.PointingHandCursor)
        self.clear_images_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {theme.TEXT_SECOND};
                border: none;
                border-radius: 16px;
                font-size: 15px;
            }}
            QPushButton:hover {{ background: {theme.BG_HOVER}; color: {theme.TEXT}; }}
        """)
        self.clear_images_btn.clicked.connect(lambda: self.clear_attached_images())
        self.clear_images_btn.hide()
        self.clear_images_btn.setToolTip("Limpiar imágenes adjuntas")
        bottom_row.addWidget(self.clear_images_btn)

        bottom_row.addStretch()

        self.send_btn = QPushButton("➤")
        self.send_btn.setFixedSize(36, 36)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setToolTip("Enviar (Enter)")
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 {theme.ACCENT_HOVER}, stop:1 {theme.ACCENT});
                color: {theme.TEXT_ON_ACCENT};
                border: none;
                border-radius: 18px;
                font-size: 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 {theme.ACCENT_BRIGHT}, stop:1 {theme.ACCENT_HOVER});
            }}
            QPushButton:pressed {{ background: {theme.ACCENT_ACTIVE}; }}
            QPushButton:disabled {{
                background: {theme.BORDER};
                color: {theme.TEXT_MUTED};
            }}
        """)
        self.send_btn.clicked.connect(self._on_send_clicked)
        bottom_row.addWidget(self.send_btn)

        composer_layout.addLayout(bottom_row)
        input_layout.addWidget(composer)

        self.images_label = QLabel("")
        self.images_label.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px; font-weight: 600; padding-left: 6px;")
        self.images_label.hide()
        input_layout.addWidget(self.images_label)

        central_layout.addWidget(input_frame)

        splitter.addWidget(central_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # Shortcuts
        self.input_edit.textChanged.connect(self.on_input_changed)

        # Diálogo de Ajustes: construir antes de load_models (contiene model_combo)
        self._init_settings_dialog()

        # Cargar modelos al inicio
        self.load_models()

        # Cargar conversaciones persistentes y renderizar la activa
        self._init_chats()

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
        return f"""
            QCheckBox {{
                color: {theme.TEXT};
                font-size: 12px;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                background: {theme.BG_INPUT};
                border: 1px solid {theme.BORDER};
                border-radius: 5px;
            }}
            QCheckBox::indicator:checked {{
                background: {theme.ACCENT};
                border-color: {theme.ACCENT};
            }}
            QCheckBox::indicator:checked::hover {{
                background: {theme.ACCENT_HOVER};
            }}
            QCheckBox:hover {{ color: {theme.TEXT}; }}
        """

    def _init_settings_dialog(self):
        """Construye el diálogo de Ajustes (modelo, funciones automáticas y tools)."""
        from PySide6.QtWidgets import QDialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Ajustes")
        dlg.setModal(False)
        dlg.resize(430, 580)
        dlg.setStyleSheet(f"QDialog {{ background: {theme.BG_WINDOW}; }}")
        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        settings_layout = QVBoxLayout(content)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(14)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # Selector de modelo
        model_group = QFrame()
        model_group.setStyleSheet(f"""
            QFrame {{
                background: {theme.BG_ELEVATED};
                border: 1px solid {theme.BORDER_SOFT};
                border-radius: 12px;
            }}
        """)
        model_layout = QVBoxLayout(model_group)
        model_layout.setContentsMargins(12, 10, 12, 10)
        model_layout.setSpacing(8)

        model_label = QLabel("MODELO")
        model_label.setStyleSheet(f"color: {theme.TEXT_SECOND}; font-weight: 700; font-size: 11px;")
        model_layout.addWidget(model_label)

        self.model_combo = QComboBox()
        self.model_combo.setFixedHeight(32)
        self.model_combo.setCursor(Qt.PointingHandCursor)
        self.model_combo.setStyleSheet(f"""
            QComboBox {{
                background: {theme.BG_INPUT};
                color: {theme.TEXT};
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 12px;
            }}
            QComboBox:focus {{ border-color: {theme.ACCENT}; }}
            QComboBox::drop-down {{
                border: none;
                width: 22px;
            }}
            QComboBox QAbstractItemView {{
                background: {theme.BG_INPUT};
                color: {theme.TEXT};
                border: 1px solid {theme.BORDER};
                selection-background-color: {theme.ACCENT};
                selection-color: {theme.TEXT_ON_ACCENT};
            }}
        """)
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        model_layout.addWidget(self.model_combo)

        self.model_status = QLabel("Cargando modelos...")
        self.model_status.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 10px;")
        model_layout.addWidget(self.model_status)

        self.pull_model_btn = QPushButton("⬇️ Pull Modelo")
        self.pull_model_btn.setFixedHeight(30)
        self.pull_model_btn.setCursor(Qt.PointingHandCursor)
        self.pull_model_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {theme.TEXT_SECOND};
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{ border-color: {theme.ACCENT}; color: {theme.TEXT}; }}
            QPushButton:disabled {{ color: {theme.TEXT_MUTED}; border-color: {theme.BORDER_SOFT}; }}
        """)
        self.pull_model_btn.clicked.connect(self.pull_model)
        model_layout.addWidget(self.pull_model_btn)

        settings_layout.addWidget(model_group)

        # Funciones automáticas
        func_group = QFrame()
        func_group.setStyleSheet(f"""
            QFrame {{
                background: {theme.BG_ELEVATED};
                border: 1px solid {theme.BORDER_SOFT};
                border-radius: 12px;
            }}
        """)
        func_layout = QVBoxLayout(func_group)
        func_layout.setContentsMargins(12, 10, 12, 10)
        func_layout.setSpacing(8)

        func_label = QLabel("FUNCIONES AUTOMÁTICAS")
        func_label.setStyleSheet(f"color: {theme.TEXT_SECOND}; font-weight: 700; font-size: 11px;")
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
        self.think_check.setChecked(True)
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

        self.tts_check = QCheckBox("🔊 Leer respuestas automáticamente")
        self.tts_check.setChecked(False)
        self.tts_check.setToolTip("Lee en voz alta cada respuesta nueva (TTS)")
        self.tts_check.setStyleSheet(self._checkbox_style())
        func_layout.addWidget(self.tts_check)

        settings_layout.addWidget(func_group)

        # Plugins / Tools
        tools_group = QFrame()
        tools_group.setStyleSheet(f"""
            QFrame {{
                background: {theme.BG_ELEVATED};
                border: 1px solid {theme.BORDER_SOFT};
                border-radius: 12px;
            }}
        """)
        tools_layout = QVBoxLayout(tools_group)
        tools_layout.setContentsMargins(12, 10, 12, 10)
        tools_layout.setSpacing(8)

        tools_label = QLabel("TOOLS INSTALADOS")
        tools_label.setStyleSheet(f"color: {theme.TEXT_SECOND}; font-weight: 700; font-size: 11px;")
        tools_layout.addWidget(tools_label)

        self.tools_list = QListWidget()
        self.tools_list.setMinimumHeight(140)
        self.tools_list.setStyleSheet(f"""
            QListWidget {{
                background: {theme.BG_INPUT};
                color: {theme.TEXT};
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
                font-size: 11px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 6px 8px;
                border-bottom: 1px solid {theme.BORDER_SOFT};
            }}
            QListWidget::item:selected {{
                background: {theme.ACCENT};
                color: {theme.TEXT_ON_ACCENT};
            }}
        """)
        self.tools_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tools_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.refresh_tools_list()
        tools_layout.addWidget(self.tools_list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.add_tool_btn = QPushButton("＋ Nuevo Tool")
        self.add_tool_btn.setFixedHeight(28)
        self.add_tool_btn.setCursor(Qt.PointingHandCursor)
        self.add_tool_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {theme.TEXT_SECOND};
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{ border-color: {theme.ACCENT}; color: {theme.TEXT}; }}
        """)
        self.add_tool_btn.clicked.connect(self.create_new_tool)
        btn_row.addWidget(self.add_tool_btn)

        self.open_tools_folder_btn = QPushButton("📁")
        self.open_tools_folder_btn.setFixedSize(28, 28)
        self.open_tools_folder_btn.setCursor(Qt.PointingHandCursor)
        self.open_tools_folder_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {theme.TEXT_SECOND};
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
                font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {theme.ACCENT}; color: {theme.TEXT}; }}
        """)
        self.open_tools_folder_btn.clicked.connect(self.open_tools_folder)
        self.open_tools_folder_btn.setToolTip("Abrir carpeta tools")
        btn_row.addWidget(self.open_tools_folder_btn)

        tools_layout.addLayout(btn_row)
        settings_layout.addWidget(tools_group)

        settings_layout.addStretch()
        self.settings_dialog = dlg

    def _open_settings(self):
        """Abre el diálogo de Ajustes (no modal: se puede chatear con él abierto)."""
        if self.settings_dialog is None:
            self._init_settings_dialog()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

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
                # Preferir un modelo de chat: los embeddings no conversan
                chat_models = [m for m in models if "embed" not in m.lower()]
                self.current_model = (chat_models or models)[0]
                # Sincronizar el combo con el modelo elegido por defecto
                idx = self.model_combo.findText(self.current_model)
                if idx >= 0:
                    self.model_combo.setCurrentIndex(idx)
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
        urls = event.mimeData.urls()
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
        """Crea una conversación nueva (si la activa ya está vacía, solo enfoca)."""
        if self.worker and self.worker.isRunning():
            self.status_label.setText("Espera a que termine el turno para crear otra conversación")
            return
        if not self.chat_history and self._chat_title == "Nuevo chat":
            self.input_edit.setFocus()
            return
        cid = memoria.crear_chat()
        self.chats.insert(0, {"id": cid, "title": "Nuevo chat", "updated": ""})
        self.chats_list.blockSignals(True)
        self.chats_list.insertItem(0, QListWidgetItem("Nuevo chat"))
        self.chats_list.blockSignals(False)
        self._select_chat(0)
        self.status_label.setText("Nuevo chat")
        self.input_edit.setFocus()

    def open_tools_folder(self):
        import subprocess
        tools_path = str((SCRIPT_DIR / "tools").absolute())
        try:
            subprocess.Popen(["xdg-open", tools_path])
        except Exception:
            QMessageBox.information(self, "Carpeta tools", f"Abre manualmente: {tools_path}")

    def create_new_tool(self):
        from PySide6.QtWidgets import QDialog, QFormLayout, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Crear Nuevo Tool")
        dlg.setFixedSize(400, 200)
        dlg.setStyleSheet(f"""
            QDialog {{ background: {theme.BG_ELEVATED}; }}
            QLabel {{ color: {theme.TEXT}; font-size: 12px; }}
            QLineEdit {{
                background: {theme.BG_INPUT};
                color: {theme.TEXT};
                border: 1px solid {theme.BORDER};
                border-radius: 6px;
                padding: 6px;
                font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {theme.ACCENT}; }}
            QPushButton {{
                background: {theme.ACCENT};
                color: {theme.TEXT_ON_ACCENT};
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background: {theme.ACCENT_HOVER}; }}
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

    @staticmethod
    def _speakable_text(text: str) -> str:
        """Aproximación a texto plano para TTS: sin sintaxis markdown ruidosa
        (piper no debe leer '##' ni '**' en voz alta)."""
        t = re.sub(r"```[\s\S]*?```", " (bloque de código) ", text)
        t = re.sub(r"`([^`]*)`", r"\1", t)
        t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
        t = re.sub(r"^>\s?", "", t, flags=re.M)
        t = re.sub(r"(\*\*|__|\*|~~)", "", t)
        t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.M)
        t = re.sub(r"\|{2,}", ", ", t)
        t = re.sub(r"\s{3,}", " ", t)
        return t.strip()

    @staticmethod
    def _tts_problema():
        """Chequeo rápido de salud del TTS (sin audio): piper y modelo de voz.
        Devuelve el problema legible o None si el TTS está listo."""
        try:
            from tools import tts_tool
        except Exception:
            return "Motor TTS no cargado (revisa la consola de la app)"
        try:
            return tts_tool.health_check()
        except Exception as e:
            return f"No se pudo verificar el TTS: {e}"

    def speak_response(self, text: str):
        """Lee un texto en voz alta (TTS) en segundo plano, sin congelar la GUI.
        Es un TOGGLE: si ya hay una lectura en curso, este clic la DETIENE
        (antes no había forma de cortar el audio: subprocess.run bloqueaba el
        hilo hasta el final y el reproductor era intocable).
        Los fallos del TTS se muestran (aviso + status); antes se tragaban
        en silencio: el tool devuelve errores como texto y el status decía 'Listo'."""
        if not text or not text.strip():
            self.status_label.setText("Nada que leer: la respuesta está vacía")
            return
        if self._speaking:
            self._stop_speech()
            return
        speak = self.executors.get("speak")
        if speak is None:
            QMessageBox.warning(self, "TTS no disponible", "Motor TTS no cargado")
            return
        # Chequeo de salud ANTES de lanzar el hilo: modelo de voz, piper, etc.
        problema = self._tts_problema()
        if problema:
            QMessageBox.warning(self, "TTS no disponible", problema)
            self.status_label.setText("🔇 TTS no disponible (revisa el aviso)")
            return
        self._speaking = True
        self.status_label.setText("🔊 Leyendo respuesta… (🔊 otra vez para detener)")

        def _do_speak():
            try:
                # tts_tool NO lanza excepciones: devuelve el error como texto.
                result = str(speak(text=self._speakable_text(text)) or "")
                if result.startswith("Error TTS") or result.startswith("TTS no disponible"):
                    self.status_label.setText(f"🔇 {result[:80]}")
                elif result.startswith("Lectura detenida"):
                    self.status_label.setText("🔇 Lectura detenida")
                else:
                    self.status_label.setText("Listo")
            except Exception as e:
                self.status_label.setText(f"Error TTS: {e}")
            finally:
                self._speaking = False

        threading.Thread(target=_do_speak, daemon=True).start()

    def _stop_speech(self):
        """Detiene la lectura TTS en curso (mata al reproductor desde tts_tool)."""
        try:
            from tools import tts_tool
            tts_tool.stop_speech()
        except Exception:
            pass
        self._speaking = False
        self.status_label.setText("🔇 Lectura detenida")

    def _save_memory(self):
        """Guarda la conversación activa en disco."""
        if self.chat_id:
            memoria.guardar_chat(self.chat_id, self._chat_title, self.chat_history)
            self._refresh_chat_entry()

    def _init_chats(self):
        """Carga la lista de conversaciones persistentes y selecciona la activa."""
        self.chats = memoria.listar_chats()
        if not self.chats:
            memoria.crear_chat()
            self.chats = memoria.listar_chats()
        self.chats_list.blockSignals(True)
        self.chats_list.clear()
        for c in self.chats:
            item = QListWidgetItem(c["title"])
            item.setToolTip(c["title"])
            self.chats_list.addItem(item)
        self.chats_list.blockSignals(False)
        self._select_chat(0)

    def _select_chat(self, row: int):
        """Carga la conversación de la fila dada y la renderiza."""
        if row < 0 or row >= len(self.chats):
            return
        meta = self.chats[row]
        self.chat_id = meta["id"]
        self._chat_title = meta["title"]
        self.chat_history = memoria.cargar_chat(self.chat_id)
        self.chats_list.setCurrentRow(row)
        self.chat_title_label.setText(self._chat_title)
        self._render_chat()

    def _current_row(self) -> int:
        return self.chats_list.currentRow()

    def _refresh_chat_entry(self):
        """Refresca título y posición de la conversación activa en la lista."""
        row = self._current_row()
        if row < 0 or row >= len(self.chats):
            return
        self.chats[row]["title"] = self._chat_title
        item = self.chats_list.item(row)
        if item:
            item.setText(self._chat_title)
        # Burbujear la conversación activa al tope de la lista
        if row > 0:
            meta = self.chats.pop(row)
            self.chats.insert(0, meta)
            self.chats_list.blockSignals(True)
            item = self.chats_list.takeItem(row)
            self.chats_list.insertItem(0, item)
            self.chats_list.setCurrentRow(0)
            self.chats_list.blockSignals(False)

    def _switch_chat(self, item):
        """Cambia de conversación, con guard: no interrumpir un turno en curso."""
        if self.worker and self.worker.isRunning():
            self.status_label.setText("Espera a que termine el turno para cambiar de conversación")
            for i, c in enumerate(self.chats):
                if c["id"] == self.chat_id:
                    self.chats_list.blockSignals(True)
                    self.chats_list.setCurrentRow(i)
                    self.chats_list.blockSignals(False)
                    break
            return
        self._select_chat(self.chats_list.row(item))

    def _delete_chat_at(self, row: int):
        """Elimina la conversación de la fila dada, con confirmación."""
        if row < 0 or row >= len(self.chats):
            return
        meta = self.chats[row]
        btn = QMessageBox.question(
            self, "Eliminar conversación",
            f"¿Eliminar «{meta['title']}»? Su historial se borrará definitivamente.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if btn != QMessageBox.Yes:
            return
        memoria.eliminar_chat(meta["id"])
        del self.chats[row]
        self.chats_list.blockSignals(True)
        self.chats_list.takeItem(row)
        self.chats_list.blockSignals(False)
        if not self.chats:
            memoria.crear_chat()
            self.chats = memoria.listar_chats()
            self.chats_list.blockSignals(True)
            self.chats_list.clear()
            for c in self.chats:
                self.chats_list.addItem(QListWidgetItem(c["title"]))
            self.chats_list.blockSignals(False)
        self._select_chat(min(row, self.chats_list.count() - 1))

    def _chat_context_menu(self, pos):
        """Menú contextual sobre la lista de conversaciones."""
        from PySide6.QtWidgets import QMenu
        item = self.chats_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        ren = menu.addAction("✏️ Renombrar conversación")
        act = menu.addAction("🗑️ Eliminar conversación")
        chosen = menu.exec(self.chats_list.mapToGlobal(pos))
        if chosen is ren:
            self._rename_chat_at(self.chats_list.row(item))
        elif chosen is act:
            self._delete_chat_at(self.chats_list.row(item))

    def _clear_chat_view(self):
        """Vacía la vista del chat (los widgets se destruyen)."""
        while self.chat_container_widget.layout.count() > 0:
            item = self.chat_container_widget.layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _render_chat(self):
        """Redibuja la conversación activa desde el historial persistido."""
        self._clear_chat_view()
        if not self.chat_history:
            self.chat_container_widget.add_message_widget(self._build_empty_state())
        else:
            last_user_idx = -1
            for i in range(len(self.chat_history) - 1, -1, -1):
                if self.chat_history[i].get("role") == "user":
                    last_user_idx = i
                    break
            for i, m in enumerate(self.chat_history):
                role = m.get("role", "assistant")
                if role == "system":
                    continue
                w = MessageBubble(role, m.get("content", ""), [], enable_think=False)
                if role == "assistant":
                    w.tool_block.hide()
                    if w.thinking_block is not None:
                        w.thinking_block.hide()
                    self._wire_assistant_actions(w)
                else:
                    self._wire_user_actions(w)
                    if i != last_user_idx:
                        w.edit_btn.hide()
                    else:
                        self._last_user_widget = w
                self.chat_container_widget.add_message_widget(w)
        self.scroll_to_bottom(force=True)

    def _build_empty_state(self):
        """Estado vacío estilo Vibe: logo, saludo y chips de sugerencias."""
        wrap = QWidget()
        vl = QVBoxLayout(wrap)
        vl.setContentsMargins(24, 40, 24, 40)
        vl.setSpacing(0)

        logo_row = QHBoxLayout()
        logo_row.addStretch()
        logo = QLabel("✦")
        logo.setFixedSize(56, 56)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(f"""
            QLabel {{
                background: {theme.ACCENT};
                color: {theme.TEXT_ON_ACCENT};
                border-radius: 28px;
                font-size: 26px;
                font-weight: bold;
            }}
        """)
        logo_row.addWidget(logo)
        logo_row.addStretch()
        vl.addLayout(logo_row)

        vl.addSpacing(20)
        title = QLabel("¿En qué te ayudo hoy?")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"color: {theme.TEXT}; font-size: 22px; font-weight: bold;")
        vl.addWidget(title)

        sub = QLabel("Escribe, arrastra una imagen o toca una sugerencia")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"color: {theme.TEXT_SECOND}; font-size: 13px;")
        vl.addSpacing(6)
        vl.addWidget(sub)

        vl.addSpacing(24)
        sugerencias = [
            "🌤️ ¿Qué clima hace en La Paz?",
            "🔎 Noticias de hoy en México",
            "🧮 Propina del 15% de $350",
            "💻 Estado de mi sistema",
        ]
        for sug in sugerencias:
            row = QHBoxLayout()
            row.addStretch()
            chip = QPushButton(sug)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setStyleSheet(f"""
                QPushButton {{
                    background: {theme.BG_ELEVATED};
                    color: {theme.TEXT_SECOND};
                    border: 1px solid {theme.BORDER};
                    border-radius: 16px;
                    padding: 8px 14px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    border-color: {theme.ACCENT};
                    color: {theme.TEXT};
                    background: {theme.ACCENT_TINT};
                }}
            """)
            chip.clicked.connect(lambda _=False, t=sug: self._use_suggestion(t))
            row.addWidget(chip)
            row.addStretch()
            vl.addLayout(row)
            vl.addSpacing(6)

        vl.addStretch(2)
        return wrap

    def _use_suggestion(self, text: str):
        """Rellena el composer con una sugerencia y le da foco."""
        self.input_edit.setPlainText(text)
        self.input_edit.setFocus()

    def _rename_chat_at(self, row: int):
        """Renombra la conversación de la fila dada."""
        if row < 0 or row >= len(self.chats):
            return
        from PySide6.QtWidgets import QInputDialog
        meta = self.chats[row]
        nuevo, ok = QInputDialog.getText(
            self, "Renombrar conversación", "Nuevo título:", text=meta["title"])
        nuevo = (nuevo or "").strip()
        if not ok or not nuevo or nuevo == meta["title"]:
            return
        memoria.guardar_chat(meta["id"], nuevo, memoria.cargar_chat(meta["id"]))
        meta["title"] = nuevo
        item = self.chats_list.item(row)
        if item:
            item.setText(nuevo)
            item.setToolTip(nuevo)
        if meta["id"] == self.chat_id:
            self._chat_title = nuevo
            self.chat_title_label.setText(nuevo)

    def _edit_user_message(self):
        """Edita el último mensaje del usuario: lo regresa al composer y descarta lo posterior."""
        if self.worker and self.worker.isRunning():
            self.status_label.setText("Detén la generación antes de editar un mensaje")
            return
        last_user_idx = -1
        for i in range(len(self.chat_history) - 1, -1, -1):
            if self.chat_history[i].get("role") == "user":
                last_user_idx = i
                break
        if last_user_idx < 0:
            return
        texto = self.chat_history[last_user_idx].get("content", "")
        # Descartar desde ese mensaje en adelante y regresar el texto al composer
        self.chat_history = self.chat_history[:last_user_idx]
        self._save_memory()
        self._render_chat()
        self.input_edit.setPlainText(texto)
        self.input_edit.setFocus()
        self.status_label.setText("Edita tu mensaje y presiona Enter")

    def _wire_user_actions(self, w):
        """Conecta las acciones de una burbuja de usuario (editar)."""
        btn = getattr(w, "edit_btn", None)
        if btn is not None:
            btn.clicked.connect(lambda _=False: self._edit_user_message())

    def _wire_assistant_actions(self, w):
        """Conecta las acciones de una burbuja de asistente (regenerar)."""
        btn = getattr(w, "retry_btn", None)
        if btn is not None:
            btn.clicked.connect(lambda _=False: self._regenerate_response())

    def _regenerate_response(self):
        """Regenerar: descarta la(s) respuesta(s) tras el último mensaje y repite el turno."""
        if self.worker and self.worker.isRunning():
            self.status_label.setText("Espera a que termine el turno para regenerar")
            return
        last_user_idx = -1
        for i in range(len(self.chat_history) - 1, -1, -1):
            if self.chat_history[i].get("role") == "user":
                last_user_idx = i
                break
        if last_user_idx < 0:
            return
        text = self.chat_history[last_user_idx].get("content", "")
        # Descartar las respuestas tras el último mensaje del usuario
        self.chat_history = self.chat_history[:last_user_idx + 1]
        self._save_memory()
        self._render_chat()
        self._start_turn(text)

    def send_message(self):
        text = self.input_edit.toPlainText().strip()
        if not text and not self.attached_images:
            return
        if self.worker and self.worker.isRunning():
            self.status_label.setText("Generando… usa el botón ⏹ para detener")
            return

        user_widget = MessageBubble("user", text or "(solo imagen)", self.attached_images.copy())
        self._wire_user_actions(user_widget)
        # Solo el último mensaje del usuario conserva el botón de editar
        prev_user = getattr(self, "_last_user_widget", None)
        if prev_user is not None:
            try:
                prev_user.edit_btn.hide()
            except Exception:
                pass
        self._last_user_widget = user_widget
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
        # Auto-título de la conversación con el primer mensaje del usuario
        if text and self._chat_title == "Nuevo chat":
            self._chat_title = memoria.titulo(text)
            self.chat_title_label.setText(self._chat_title)
        # Mantener el historial acotado: lo mismo que se envía al modelo.
        if len(self.chat_history) > memoria.MAX_MEMORY_MESSAGES:
            self.chat_history = self.chat_history[-memoria.MAX_MEMORY_MESSAGES:]
        self._save_memory()
        self.input_edit.clear()
        attached_copy = self.attached_images.copy()
        self.attached_images = []
        self.update_attached_label()

        self._start_turn(text)

    def _start_turn(self, text: str):
        """Inicia el turno del asistente para el último mensaje del historial."""
        enable_tools = self.tools_check.isChecked()
        enable_think = self.think_check.isChecked() and self.modelo_piensa(self.current_model)

        # Pre-router: filtrar tools según el mensaje del usuario.
        # Ahora también con thinking activado: la FASE 1 del worker corre con
        # think=False, así que la razón original del salto (qwen razonando con
        # tools filtradas) ya no aplica al loop de tools. Si el modelo alucina
        # una tool filtrada, el worker le devuelve la lista de disponibles del
        # turno; y si Ollama tronara, el worker cae a responder sin tools.
        # Sin el filtrado, cada turno con thinking mandaba ~3,200 tokens de
        # tools y Ollama trunca el prompt en silencio al superar num_ctx:
        # el system prompt era lo primero en caer.
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

        # Tools interactivas de la GUI (speak/listen) nunca se exponen al
        # modelo, vengan o no del pre-router: listen bloquearía el worker
        # esperando el micrófono y speak sintetiza audio de minutos dentro
        # del turno. Los botones 🔊/🎤 usan self.executors directamente.
        route_defs = [d for d in route_defs
                      if d.get("function", {}).get("name") not in GUI_ONLY_TOOLS]
        route_execs = {k: v for k, v in route_execs.items() if k not in GUI_ONLY_TOOLS}

        # Inyectar SIEMPRE el system prompt vigente: la memoria persistida
        # nunca debe congelar una versión vieja del prompt.
        history_with_system = [{"role": "system", "content": SYSTEM_PROMPT}]
        history_with_system.extend(
            m for m in self.chat_history if m.get("role") != "system"
        )

        assistant_widget = MessageBubble("assistant", "", [], enable_think=enable_think)
        self.chat_container_widget.add_message_widget(assistant_widget)
        self.current_assistant_widget = assistant_widget
        self._wire_assistant_actions(assistant_widget)
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
        self.worker.status_update.connect(self._on_worker_status)
        self.worker.finished.connect(lambda: self._set_send_mode("send"))

        # Ruta de tools + cronómetro del turno en el status bar
        self._turn_start = time.time()
        if enable_tools:
            # Total expuesto al modelo: tools_def menos las de solo-GUI
            total_exposed = sum(
                1 for d in self.tools_def
                if d.get("function", {}).get("name") not in GUI_ONLY_TOOLS
            )
            if len(route_defs) == total_exposed:
                ruta_desc = f"todas las tools ({len(route_defs)})"
            else:
                ruta_desc = f"{len(route_defs)}/{total_exposed} tools (pre-router)"
            self.status_label.setText(f"Consultando... · {ruta_desc}")
        self._stop_requested = False
        self._set_send_mode("stop")
        self.worker.start()

    def _on_send_clicked(self):
        """El botón envía o detiene según el estado del turno."""
        if self.worker and self.worker.isRunning():
            self._stop_generation()
        else:
            self.send_message()

    def _stop_generation(self):
        """Detiene el turno en curso conservando lo generado hasta ahora."""
        if self.worker and self.worker.isRunning():
            self._stop_requested = True
            self.worker.stop()
            self.status_label.setText("Deteniendo…")

    def _set_send_mode(self, mode: str):
        """Alterna el botón enviar/detener según el estado del turno."""
        if mode == "stop":
            self.send_btn.setText("⏹")
            self.send_btn.setToolTip("Detener generación")
            self.send_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {theme.ERROR};
                    color: #ffffff;
                    border: none;
                    border-radius: 18px;
                    font-size: 14px;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background: #ff7f7f; }}
            """)
        else:
            self.send_btn.setText("➤")
            self.send_btn.setToolTip("Enviar (Enter)")
            self.send_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {theme.ACCENT};
                    color: {theme.TEXT_ON_ACCENT};
                    border: none;
                    border-radius: 18px;
                    font-size: 16px;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background: {theme.ACCENT_HOVER}; }}
                QPushButton:pressed {{ background: {theme.ACCENT_ACTIVE}; }}
            """)

    @Slot(str)
    def _on_worker_status(self, s: str):
        """Status del worker + cronómetro del turno."""
        elapsed = int(time.time() - getattr(self, "_turn_start", time.time()))
        self.status_label.setText(f"{s} · {elapsed}s")

    def closeEvent(self, event):
        """Apagado limpio: detiene el hilo del orquestador y el audio TTS antes de salir."""
        try:
            from tools import tts_tool
            tts_tool.stop_speech()
        except Exception:
            pass
        if getattr(self, "orch_thread", None) is not None:
            self.orch_thread.quit()
            if not self.orch_thread.wait(2000):
                self.orch_thread.terminate()
                self.orch_thread.wait(1000)
        event.accept()

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
            # Si se detuvo la generación sin texto, no guardar una respuesta vacía
            if answer.strip() or not getattr(self, "_stop_requested", False):
                self.chat_history.append({"role": "assistant", "content": answer})
                self._save_memory()
            try:
                self.current_assistant_widget.finishAnswer(answer, thinking)
                self.current_assistant_widget.showTTS()
                if self.tts_check.isChecked() and answer.strip():
                    self.speak_response(answer)
            except Exception:
                import traceback
                traceback.print_exc()
                self.status_label.setText("Error al renderizar respuesta")
        # Vista nunca bloquea el turno: el botón siempre se habilita
        self._set_send_mode("send")
        self.status_label.setText("Listo")
        self.scroll_to_bottom()

    @Slot(str)
    def on_error(self, err: str):
        QMessageBox.critical(self, "Error Ollama", f"{err}\n\nVerifica que 'ollama serve' esté corriendo y el modelo exista.\nollama pull {self.current_model}")
        self._set_send_mode("send")
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
        self._set_send_mode("send")
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
        self._set_send_mode("send")
        self.status_label.setText("Agente: error")

    # ---------- Ayuda: añadir burbuja de asistente desde cualquier contexto ----------
    def _agregar_burbuja_asistente(self, texto: str, enable_think: bool = False):
        widget = MessageBubble("assistant", texto, [], enable_think=enable_think)
        self.chat_container_widget.add_message_widget(widget)
        self.current_assistant_widget = widget
        self._wire_assistant_actions(widget)
        self.chat_history.append({"role": "assistant", "content": texto})
        self._save_memory()
        self.scroll_to_bottom()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    from PySide6.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(theme.BG_WINDOW))
    palette.setColor(QPalette.WindowText, QColor(theme.TEXT))
    palette.setColor(QPalette.Base, QColor(theme.BG_ELEVATED))
    palette.setColor(QPalette.AlternateBase, QColor(theme.BG_WINDOW))
    palette.setColor(QPalette.ToolTipBase, QColor(theme.BG_ELEVATED))
    palette.setColor(QPalette.ToolTipText, QColor(theme.TEXT))
    palette.setColor(QPalette.Text, QColor(theme.TEXT))
    palette.setColor(QPalette.Button, QColor(theme.BG_ELEVATED))
    palette.setColor(QPalette.ButtonText, QColor(theme.TEXT))
    palette.setColor(QPalette.BrightText, QColor(theme.ERROR))
    palette.setColor(QPalette.Link, QColor(theme.ACCENT))
    palette.setColor(QPalette.Highlight, QColor(theme.ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor(theme.TEXT_ON_ACCENT))
    app.setPalette(palette)
    app.setStyleSheet(theme.app_qss())
    app.setFont(QFont("Inter", 10))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
