#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
delete_file.py — Tool de MUTACIÓN. Borrado SEGURO: mueve a ~/.Papelera/<fecha>/.

NADA se destruye de verdad: el archivo queda recuperable en la papelera local.
El orquestador pide autorización antes de ejecutar. Nunca toca la raíz de la
carpeta personal, la papelera misma, ni rutas de sistema (blacklist).
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(os.environ.get("DELETE_ROOT", str(Path.home()))).expanduser().resolve()
PAPELERA = RAIZ / ".Papelera"

BLACKLIST = {
    ".ssh", ".gnupg", ".cache", ".mozilla", ".thunderbird",
    ".config", ".local", "venv", ".venv", "env", "node_modules",
}

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "delete_file",
        "description": (
            "USAR CUANDO el usuario pida BORRAR o ELIMINAR un archivo o carpeta CONCRETA. "
            "Ejemplos: 'borra el borrador.txt', 'elimina esa carpeta vieja de Descargas'. "
            "Borrado SEGURO: el archivo se mueve a ~/.Papelera/<fecha>/ y queda RECUPERABLE; "
            "nada se destruye de verdad. Solo rutas bajo su carpeta personal, fuera de rutas "
            "de sistema. El orquestador pedirá autorización antes de borrar. "
            "NO usar para vaciar la papelera ni borrar carpetas enteras por tipos."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ruta": {"type": "string", "description": "Ruta del archivo/carpeta a borrar (admite ~)"},
                "dry_run": {"type": "boolean", "description": "true (defecto) simula sin borrar"},
            },
            "required": ["ruta"],
        },
    },
}


def _bloqueada(p: Path) -> str | None:
    try:
        rel = p.expanduser().resolve().relative_to(RAIZ)
    except (ValueError, FileNotFoundError):
        return "fuera de la carpeta personal"
    if not rel.parts:
        return "la raíz de la carpeta personal no se puede borrar"
    for comp in rel.parts:
        if comp in BLACKLIST:
            return f"ruta protegida ({comp})"
    resuelta = p.expanduser().resolve()
    if resuelta == PAPELERA or PAPELERA in resuelta.parents:
        return "la papelera misma (para vaciarla usa el gestor de archivos)"
    return None


def execute(*args, **kwargs) -> str:
    params: dict = {}
    for a in args:
        if isinstance(a, dict):
            params.update(a)
        elif isinstance(a, str) and "ruta" not in params:
            params["ruta"] = a
    params.update({k: v for k, v in kwargs.items() if v is not None})

    raw = str(params.get("ruta", "")).strip()
    dry = bool(params.get("dry_run", True))

    if not raw:
        return "⚠️ delete_file necesita 'ruta'."

    ruta = Path(raw).expanduser()
    err = _bloqueada(ruta)
    if err:
        return f"🚫 {err}. Acción cancelada."
    if not ruta.exists():
        return f"⚠️ No existe: {ruta}"

    destino_dir = PAPELERA / datetime.now().strftime("%Y-%m-%d")
    destino = destino_dir / ruta.name
    i = 1
    while destino.exists():
        destino = destino_dir / f"{ruta.stem}_{i}{ruta.suffix}"
        i += 1

    tipo = "carpeta" if ruta.is_dir() else "archivo"
    if dry:
        return (f"🔎 SIMULACIÓN\n  MOVERÁ A PAPELERA ({tipo}): {ruta}\n  → {destino}\n"
                f"  Nada se destruye: recuperable desde {destino_dir}.")

    try:
        destino_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(ruta), str(destino))
    except Exception as e:
        return f"Error moviendo a la papelera: {e}"
    return (f"🗑 Movido a la papelera ({tipo}): {ruta} → {destino}\n"
            f"Recuperable ahí mientras no se vacíe ~/.Papelera.")


if __name__ == "__main__":
    print(execute(ruta=sys.argv[1] if len(sys.argv) > 1 else ""))
