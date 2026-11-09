import sys
import time
import os
import re
import json
import base64
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
        except Exception:
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
        data = memoria.cargar()
        if data:
            print(f"Memoria cargada: {len(data)} mensajes desde {memoria.MEMORY_FILE}")
        self.chat_history = data

    def _save_memory(self):
        """Guarda el historial de chat en disco."""
        memoria.guardar(self.chat_history)

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
        # Mantener el historial acotado: lo mismo que se envía al modelo.
        if len(self.chat_history) > memoria.MAX_MEMORY_MESSAGES:
            self.chat_history = self.chat_history[-memoria.MAX_MEMORY_MESSAGES:]
        self._save_memory()
        self.input_edit.clear()
        attached_copy = self.attached_images.copy()
        self.attached_images = []
        self.update_attached_label()

        enable_tools = self.tools_check.isChecked()
        enable_think = self.think_check.isChecked() and self.modelo_piensa(self.current_model)

        # Pre-router: filtrar tools según el mensaje del usuario.
        # Cuando thinking está activado (qwen3.5:4b), enviar TODAS las tools
        # sin filtrar: el modo reasoning no soporta bien el filtrado selectivo
        # y el modelo necesita ver todas las opciones para decidir invocarlas.
        route_defs = self.tools_def
        route_execs = self.executors
        if self.tool_router is not None and enable_tools and not enable_think:
            try:
                route_defs = self.tool_router.route(text)
                route_execs = {k: v for k, v in self.executors.items()
                               if k in {d.get("function", {}).get("name") for d in route_defs}}
                print(f"Pre-router: {len(route_defs)} tools de {len(self.tools_def)} totales")
            except Exception as e:
                print(f"⚠ Pre-router falló, usando todas las tools: {e}")
        elif enable_think:
            print(f"Thinking ON: todas las herramientas ({len(self.tools_def)})")

        # Inyectar SIEMPRE el system prompt vigente: la memoria persistida
        # nunca debe congelar una versión vieja del prompt.
        history_with_system = [{"role": "system", "content": SYSTEM_PROMPT}]
        history_with_system.extend(
            m for m in self.chat_history if m.get("role") != "system"
        )

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
        self.worker.status_update.connect(self._on_worker_status)
        self.worker.finished.connect(lambda: self.send_btn.setEnabled(True))

        # Ruta de tools + cronómetro del turno en el status bar
        self._turn_start = time.time()
        if enable_tools:
            if route_defs is self.tools_def:
                ruta_desc = f"todas las tools ({len(self.tools_def)})"
            else:
                ruta_desc = f"{len(route_defs)}/{len(self.tools_def)} tools (pre-router)"
            self.status_label.setText(f"Consultando... · {ruta_desc}")
        self.send_btn.setEnabled(False)
        self.worker.start()

    @Slot(str)
    def _on_worker_status(self, s: str):
        """Status del worker + cronómetro del turno."""
        elapsed = int(time.time() - getattr(self, "_turn_start", time.time()))
        self.status_label.setText(f"{s} · {elapsed}s")

    def closeEvent(self, event):
        """Apagado limpio: detiene el hilo del orquestador antes de salir."""
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