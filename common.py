#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.py — Constantes y utilidades compartidas por todos los módulos.

Flags de dedup del streaming (proyecto E3), estilos markdown (MD_CSS)
y trace() para logs con marca de tiempo y nombre de hilo.
"""
import os

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
a { color: #FF9D57; text-decoration: none; }
hr { border: none; border-top: 1px solid #2a2c31; margin: 10px 0; }
"""

import time as _time
import threading as _threading


def trace(msg):
    print(f"[{_time.strftime('%H:%M:%S')}] {_threading.current_thread().name:>12} | {msg}", flush=True)

