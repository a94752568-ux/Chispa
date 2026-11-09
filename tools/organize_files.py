#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
organize_files.py — Organiza una carpeta por tipo de archivo (imágenes, docs, audio, video, código…).

MUTACIÓN: mueve archivos. El orquestador pide autorización antes de ejecutar.
Nunca borra. Nunca mueve fuera de RAIZ. Colisiones de nombre se resuelven con sufijo _1, _2.
Dry-run por defecto: imprime el plan origen→destino sin mover nada.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

RAIZ = Path(os.environ.get("ORGANIZE_ROOT", str(Path.home()))).expanduser().resolve()
BLACKLIST = {".ssh", ".gnupg", "venv", ".venv", "env", "node_modules", ".cache", ".config"}

# extensión → subcarpeta destino
TIPOS = {
    "Imágenes": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".heic"},
    "Documentos": {".pdf", ".doc", ".docx", ".odt", ".txt", ".md", ".rst", ".rtf", ".epub"},
    "Hoja de cálculo": {".xls", ".xlsx", ".ods", ".csv", ".tsv"},
    "Audio": {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus"},
    "Video": {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"},
    "Código": {".py", ".js", ".ts", ".html", ".css", ".json", ".sh", ".c", ".cpp", ".java", ".go", ".rs"},
    "Comprimidos": {".zip", ".tar", ".gz", ".bz2", ".7z", ".rar", ".xz"},
    "Ejecutables/AppImage": {".appimage", ".deb", ".rpm", ".flatpak", ".run"},
}
_EXT2CAT = {e: cat for cat, exts in TIPOS.items() for e in exts}

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "organize_files",
        "description": (
            "USAR CUANDO el usuario pida ORGANIZAR, CLASIFICAR o ORDENAR una carpeta por tipo de archivo. "
            "Ejemplos: 'organiza mi Descargas por tipo', 'clasifica los archivos de ~/Documentos en carpetas', "
            "'ordena las fotos y documentos de esta carpeta'. Crea subcarpetas (Imágenes, Documentos, Audio…) "
            "y MUEVE los archivos dentro de la misma raíz. Nunca borra. El orquestador pedirá autorización. "
            "NO usar para: mover fuera de casa, borrar, ni renombrar contenido de archivos."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "carpeta": {"type": "string", "description": "Carpeta a organizar bajo /home/aegis2 (admite ~)"},
                "dry_run": {"type": "boolean", "description": "true (defecto) muestra el plan sin mover"},
            },
            "required": ["carpeta"],
        },
    },
}


def _peligrosa(p: Path) -> bool:
    try:
        rel = p.resolve().relative_to(RAIZ)
    except (ValueError, FileNotFoundError):
        return True
    return any(c in BLACKLIST for c in rel.parts)


def _destino_unico(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suf, i = dest.stem, dest.suffix, 1
    while True:
        cand = dest.with_name(f"{stem}_{i}{suf}")
        if not cand.exists():
            return cand
        i += 1


def _plan(carpeta: Path):
    """Genera lista (origen, destino, categoria) sin mover nada."""
    movimientos, ignorados = [], []
    for entry in sorted(carpeta.iterdir()):
        if entry.is_dir():
            continue
        if _peligrosa(entry):
            ignorados.append((entry, "en blacklist"))
            continue
        cat = _EXT2CAT.get(entry.suffix.lower())
        if not cat:
            ignorados.append((entry, "tipo desconocido"))
            continue
        destino = _destino_unico(carpeta / cat / entry.name)
        movimientos.append((entry, destino, cat))
    return movimientos, ignorados


def execute(*args, **kwargs) -> str:
    params: dict = {}
    for a in args:
        if isinstance(a, dict):
            params.update(a)
        elif isinstance(a, str) and "carpeta" not in params:
            params["carpeta"] = a
    params.update({k: v for k, v in kwargs.items() if v is not None})
    carpeta = Path(str(params.get("carpeta", "")).strip()).expanduser()
    dry = bool(params.get("dry_run", True))

    if not carpeta.exists() or not carpeta.is_dir():
        return f"⚠️ No existe la carpeta: {carpeta}"
    if _peligrosa(carpeta):
        return "🚫 Carpeta en ruta protegida. Acción cancelada."

    movimientos, ignorados = _plan(carpeta)
    if not movimientos:
        return f"Sin archivos clasificables en {carpeta}. Ignorados: {len(ignorados)}."

    if dry:
        lineas = [f"🔎 PLAN de organización (dry_run) · {len(movimientos)} movimiento(s)", ""]
        por_cat: dict[str, list[tuple[str, str]]] = {}
        for o, d, c in movimientos:
            por_cat.setdefault(c, []).append((o.name, d.name))
        for c, pares in sorted(por_cat.items()):
            lineas.append(f"📁 {c}/  ({len(pares)} archivos)")
            for orig, dest in pares[:8]:
                lineas.append(f"   {orig}  →  {dest}")
            if len(pares) > 8:
                lineas.append(f"   … y {len(pares) - 8} más")
            lineas.append("")
        if ignorados:
            lineas.append(
                f"⏭  Ignorados ({len(ignorados)}): "
                + ", ".join(n.name for n, _ in ignorados[:6])
            )
        lineas.append(
            "\nPara ejecutar de verdad, el orquestador debe autorizar con dry_run=false."
        )
        return "\n".join(lineas)

    movidos = 0
    for orig, dest, _ in movimientos:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(orig), str(dest))
        movidos += 1
    return f"✔ Organizada {carpeta}: {movidos} archivos movidos, {len(ignorados)} ignorados."


organize_files = execute

if __name__ == "__main__":
    print(execute(carpeta=sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / "Descargas")))
