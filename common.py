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
# Evita el look "ensayo viejo" de los títulos enormes de Qt.
# Acabado premium: negritas que brillan, código con borde, citas con
# acento naranja y tablas con encabezado elevado.
# ================================================================
MD_CSS = """
h1 { font-size: 19px; font-weight: bold; margin: 14px 0 6px; color: #f5f5f7;
     border-bottom: 1px solid #2a2c31; padding-bottom: 5px; }
h2 { font-size: 17px; font-weight: bold; margin: 12px 0 5px; color: #f5f5f7; }
h3 { font-size: 15px; font-weight: bold; margin: 10px 0 4px; color: #FF9D57; }
h4 { font-size: 14px; font-weight: bold; margin: 8px 0 3px; color: #e5e5ea; }
p  { margin: 6px 0; }
strong { color: #ffffff; font-weight: bold; }
ul, ol { margin: 6px 0; padding-left: 20px; }
li { margin: 3px 0; }
code { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 13px;
       background: #241a12; border: 1px solid #35291d; border-radius: 5px;
       padding: 1px 5px; color: #ffb380; }
pre { background: #101014; border: 1px solid #2a2c31; border-radius: 10px;
      padding: 11px 13px; }
pre code { background: transparent; border: none; padding: 0; color: #e6e6ea; }
blockquote { border-left: 3px solid #FF7000; margin: 8px 0;
             padding: 4px 0 4px 12px; color: #b0b0ba; background: #171310; }
a { color: #FF9D57; font-weight: 600; text-decoration: none; }
hr { border: none; border-top: 1px solid #2a2c31; margin: 12px 0; }
table { border-collapse: collapse; margin: 10px 0; }
th, td { border: 1px solid #2a2c31; padding: 6px 11px; }
th { background: #1a1b20; color: #ffffff; font-weight: bold; }
td { color: #e5e5ea; }
"""

import time as _time
import threading as _threading


def trace(msg):
    print(f"[{_time.strftime('%H:%M:%S')}] {_threading.current_thread().name:>12} | {msg}", flush=True)
