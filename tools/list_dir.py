#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
list_dir.py — Lista el contenido de UNA carpeta (un nivel, sin recursión).

Tool de LECTURA (sin gate de mutación): responde "¿qué hay en ~/Descargas?"
con nombres, tipo, tamaño y fecha de modificación. A diferencia de find_files
(búsqueda por nombre en todo el árbol), aquí se lista la carpeta indicada:
es el equivalente seguro de 'ls -lh'.

Blacklist de rutas protegidas y topes de entradas/tamaño de respuesta para
no desbordar el contexto del modelo en carpetas enormes.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(os.environ.get("LIST_ROOT", str(Path.home()))).expanduser().resolve()

# Rutas que nunca se listan (mismas reglas que find_files/read_file)
BLACKLIST = {".git", ".ssh", ".gnupg", ".cache", ".mozilla", ".thunderbird",
             ".config", ".local", ".Papelera", "node_modules",
             "venv", ".venv", "env", "__pycache__"}

TOPE_ENTRADAS = 200
TOPE_CHARS = 6000  # margen bajo TOOL_RESULT_MAX (3500) del worker


TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "list_dir",
        "description": (
            "USAR CUANDO el usuario pida VER o LISTAR el contenido de una carpeta. "
            "Ejemplos: '¿qué hay en ~/Descargas?', 'lista los archivos de ~/Proyectos', "
            "'muéstrame el contenido de mi escritorio'. Lista UN nivel de la carpeta "
            "(sin recursión) con nombre, tipo, tamaño y fecha de modificación, "
            "carpetas primero (tope 200 entradas). NO sirve para buscar por nombre en "
            "todo el árbol (eso es find_files), leer un archivo (read_file) ni buscar "
            "dentro de documentos (rag_search)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "carpeta": {"type": "string", "description": "Ruta de la carpeta a listar (admite ~). Defecto: la carpeta personal"},
                "ocultos": {"type": "boolean", "description": "Incluir archivos ocultos (punto inicial). Defecto: false"},
            },
            "required": [],
        },
    },
}


def execute(carpeta: str = "", ocultos: bool = False, **kwargs) -> str:
    try:
        # Tolerancia a argumentos mal nombrados por el modelo
        carpeta = str(carpeta or kwargs.get("ruta", "") or kwargs.get("path", "")
                      or kwargs.get("folder", "") or kwargs.get("directorio", "") or "").strip()
        ocultos = bool(ocultos or kwargs.get("hidden", False) or kwargs.get("incluir_ocultos", False))

        base = Path(carpeta).expanduser() if carpeta else RAIZ
        try:
            base = base.resolve()
        except Exception:
            return f"⚠️ Ruta inválida: '{carpeta}'"
        if not base.exists():
            return f"⚠️ La carpeta no existe: {base}"
        if not base.is_dir():
            return f"⚠️ No es una carpeta (¿es un archivo? usa read_file): {base}"

        try:
            rel = base.relative_to(RAIZ)
        except ValueError:
            return f"🚫 Solo se lista dentro de {RAIZ}."
        if any(c in BLACKLIST for c in rel.parts):
            return "🚫 Carpeta en ruta protegida. Acción cancelada."

        try:
            entradas = list(base.iterdir())
        except PermissionError:
            return f"🚫 Sin permiso para leer {base}"

        if not ocultos:
            entradas = [e for e in entradas if not e.name.startswith(".")]

        dirs = sorted((e for e in entradas if e.is_dir()), key=lambda e: e.name.lower())
        files = sorted((e for e in entradas if not e.is_dir()), key=lambda e: e.name.lower())

        lineas = [f"📂 {base} — {len(dirs)} carpeta(s), {len(files)} archivo(s)"]
        total = 0
        cortado = False
        for e in dirs + files:
            if total >= TOPE_ENTRADAS:
                cortado = True
                break
            try:
                st = e.stat()
                fecha = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                if e.is_dir():
                    lineas.append(f"  📁 {e.name}/  ·  {fecha}")
                else:
                    tam = st.st_size
                    peso = f"{tam / 1024:.0f} KB" if tam < 1024 * 1024 else f"{tam / (1024 * 1024):.1f} MB"
                    lineas.append(f"  📄 {e.name}  ·  {peso}  ·  {fecha}")
            except OSError:
                lineas.append(f"  ❓ {e.name} (sin acceso)")
            total += 1

        if cortado:
            lineas.append(f"  ⏱ Mostradas {total} de {len(dirs) + len(files)} entradas; pide una subcarpeta para ver más.")
        salida = "\n".join(lineas)
        if len(salida) > TOPE_CHARS:
            salida = salida[:TOPE_CHARS] + "\n  ⏱ Lista recortada por tamaño; pide una subcarpeta."
        return salida
    except Exception as e:
        return f"Error listando: {e}"


if __name__ == "__main__":
    import sys
    print(execute(carpeta=sys.argv[1] if len(sys.argv) > 1 else "~"))
