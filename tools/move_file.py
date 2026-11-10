#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
move_file.py — Tool de MUTACIÓN. Mueve o renombra UN archivo o carpeta concreta.

La autorización la decide el orquestador (agent_orchestrator) con su diálogo
de autorización; el dry_run interno es la segunda capa (defecto en CLI/chat).
Nunca mueve fuera de la carpeta personal ni toca rutas de sistema (blacklist).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

RAIZ = Path(os.environ.get("MOVE_ROOT", str(Path.home()))).expanduser().resolve()

BLACKLIST = {
    ".ssh", ".gnupg", ".cache", ".mozilla", ".thunderbird", ".Papelera",
    "venv", ".venv", "env", "node_modules",
}

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "move_file",
        "description": (
            "USAR CUANDO el usuario pida MOVER o RENOMBRAR un archivo o carpeta CONCRETA. "
            "Ejemplos: 'mueve el informe.md a Documentos', 'renombra foto.jpg a foto_final.jpg', "
            "'pasa ese PDF a la carpeta del proyecto'. Origen y destino bajo su carpeta personal, "
            "fuera de rutas de sistema. Si el destino ya existe, añade sufijo _1, _2 (se reporta "
            "el nombre final). El orquestador pedirá autorización antes de mover. "
            "NO usar para organizar una carpeta ENTERA por tipos (organize_files)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "origen": {"type": "string", "description": "Ruta del archivo/carpeta a mover (admite ~)"},
                "destino": {"type": "string", "description": "Ruta destino: carpeta existente (conserva nombre) o ruta completa con el nombre final (admite ~)"},
                "dry_run": {"type": "boolean", "description": "true (defecto) simula sin mover"},
            },
            "required": ["origen", "destino"],
        },
    },
}


def _bloqueada(p: Path) -> str | None:
    try:
        rel = p.expanduser().resolve().relative_to(RAIZ)
    except (ValueError, FileNotFoundError):
        return "fuera de la carpeta personal"
    for comp in rel.parts:
        if comp in BLACKLIST:
            return f"ruta protegida ({comp})"
    return None


def _destino_unico(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suf, i = dest.stem, dest.suffix, 1
    while True:
        cand = dest.with_name(f"{stem}_{i}{suf}")
        if not cand.exists():
            return cand
        i += 1


def execute(*args, **kwargs) -> str:
    params: dict = {}
    for a in args:
        if isinstance(a, dict):
            params.update(a)
        elif isinstance(a, str) and "origen" not in params:
            params["origen"] = a
    params.update({k: v for k, v in kwargs.items() if v is not None})

    raw_o = str(params.get("origen", "")).strip()
    raw_d = str(params.get("destino", "")).strip()
    dry = bool(params.get("dry_run", True))

    if not raw_o or not raw_d:
        return "⚠️ move_file necesita 'origen' y 'destino'."

    origen = Path(raw_o).expanduser()
    destino = Path(raw_d).expanduser()

    err = _bloqueada(origen)
    if err:
        return f"🚫 Origen {err}. Acción cancelada."
    err = _bloqueada(destino)
    if err:
        return f"🚫 Destino {err}. Acción cancelada."
    if not origen.exists():
        return f"⚠️ No existe el origen: {origen}"

    # Destino como carpeta existente → conservar el nombre original
    if destino.is_dir():
        destino = destino / origen.name
    destino = _destino_unico(destino)

    if origen.resolve() == destino.resolve():
        return "⚠️ Origen y destino son la misma ruta."

    tipo = "carpeta" if origen.is_dir() else "archivo"
    if dry:
        return (f"🔎 SIMULACIÓN\n  MOVERÁ ({tipo}): {origen}\n  → {destino}")

    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(origen), str(destino))
    except Exception as e:
        return f"Error moviendo {origen} → {destino}: {e}"
    return f"✔ Movido ({tipo}): {origen} → {destino}"


if __name__ == "__main__":
    print(execute(origen=sys.argv[1], destino=sys.argv[2] if len(sys.argv) > 2 else ""))
