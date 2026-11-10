#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
find_files.py — Búsqueda de archivos/carpetas por NOMBRE bajo la carpeta personal.

Tool de LECTURA (sin gate de mutación): responde "¿dónde está el archivo X?".
Recorre el árbol con os.walk podando directorios pesados o peligrosos
(.cache, .config, .local, node_modules, venv…) con tope de resultados y de
tiempo para no arrastrar el disco del laptop ni desbordar el contexto.
"""
from __future__ import annotations

import fnmatch
import os
import time
from pathlib import Path

RAIZ = Path(os.environ.get("FIND_ROOT", str(Path.home()))).expanduser().resolve()

# Carpetas que nunca se recorren: enormes, de sistema o ruido para el usuario
BLACKLIST = {
    ".git", ".ssh", ".gnupg", ".cache", ".mozilla", ".thunderbird",
    ".config", ".local", ".Papelera", "node_modules",
    "venv", ".venv", "env", "__pycache__",
}

TOPE_RESULTADOS = 50
TOPE_SEGUNDOS = 15

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "find_files",
        "description": (
            "USAR CUANDO el usuario pregunte dónde está un archivo o carpeta por su NOMBRE. "
            "Ejemplos: '¿dónde guardé el informe?', 'encuentra los PDF', '¿hay algún archivo "
            "de presupuestos?'. Busca por patrón de nombre (glob, insensible a mayúsculas, "
            "ej: '*.pdf', 'informe*') bajo su carpeta personal. Devuelve rutas y tamaños "
            "(tope 50 resultados). NO sirve para buscar dentro del CONTENIDO de archivos "
            "(eso es rag_search) ni en la web (web_search)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "patron": {"type": "string", "description": "Patrón de nombre de archivo o carpeta, ej: '*.pdf', 'informe*', 'factura'"},
                "carpeta": {"type": "string", "description": "Carpeta donde buscar (defecto: toda la carpeta personal ~)"},
            },
            "required": ["patron"],
        },
    },
}


def execute(patron: str = "", carpeta: str = "", **kwargs) -> str:
    try:
        # Tolerancia a argumentos mal nombrados por el modelo
        patron = str(patron or kwargs.get("patrón", "") or kwargs.get("pattern", "")
                     or kwargs.get("nombre", "") or kwargs.get("query", "")).strip()
        carpeta = str(carpeta or kwargs.get("folder", "") or kwargs.get("ruta", "")).strip()

        if not patron:
            return "⚠️ find_files necesita 'patron' (ej: '*.pdf', 'informe*')."
        if "/" in patron or patron.startswith("~"):
            return "⚠️ 'patron' es solo el nombre, sin rutas. La carpeta va en 'carpeta'."

        base = Path(carpeta).expanduser() if carpeta else RAIZ
        base = base.resolve()
        try:
            rel_base = base.relative_to(RAIZ)
        except ValueError:
            return f"🚫 Solo se busca dentro de {RAIZ}."
        if any(c in BLACKLIST for c in rel_base.parts):
            return "🚫 Carpeta en ruta protegida. Acción cancelada."

        # Sin comodines → búsqueda difusa por substring
        patron_l = patron.lower()
        if not any(ch in patron for ch in "*?"):
            patron_l = f"*{patron.lower()}*"

        hallados: list[tuple[str, int]] = []
        limite_ts = time.time() + TOPE_SEGUNDOS
        cortado = False

        for dirpath, dirnames, filenames in os.walk(base):
            if time.time() > limite_ts:
                cortado = True
                break
            # Poda de carpetas pesadas/peligrosas
            dirnames[:] = [d for d in dirnames if d not in BLACKLIST]

            nombres = filenames + dirnames
            for nombre in nombres:
                if not fnmatch.fnmatch(nombre.lower(), patron_l):
                    continue
                full = Path(dirpath) / nombre
                try:
                    tam = full.stat().st_size if full.is_file() else -1
                except OSError:
                    tam = -1
                hallados.append((str(full), tam))
                if len(hallados) >= TOPE_RESULTADOS:
                    break
            if len(hallados) >= TOPE_RESULTADOS:
                break

        if not hallados:
            return (f"Sin resultados para '{patron}' bajo {base}. "
                    "Si buscabas contenido dentro de archivos, usa rag_search.")

        lineas = [f"🔍 {len(hallados)} resultado(s) para '{patron}':"]
        for ruta, tam in hallados:
            peso = f"{tam / 1024:.0f} KB" if tam >= 0 else "(carpeta)"
            lineas.append(f"  {ruta} · {peso}")
        if cortado:
            lineas.append("  ⏱ Búsqueda cortada por tiempo: hay más resultados; afina 'carpeta'.")
        lineas.append(f"(tope {TOPE_RESULTADOS} resultados; para leer uno usa read_file)")
        return "\n".join(lineas)
    except Exception as e:
        return f"Error buscando: {e}"
