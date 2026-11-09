#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
desktop_writer.py — Tool de MUTACIÓN. Escribe/crea en /home/aegis2 con blacklist de peligro.

La autorización NO la decide esta tool: la decide el orquestador (agent_orchestrator).
Esta función solo ejecuta si el orquestador ya validó el paso. El dry_run interno es
una segunda capa para pruebas por CLI, no el gate de seguridad.

Blacklist: rutas dentro de la raíz que NUNCA se tocan, aunque el plan las pida.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

RAIZ = Path(os.environ.get("WRITER_ROOT", str(Path.home()))).expanduser().resolve()

# Peligrosas aunque estén dentro de la raíz. Comparación por componente de ruta.
BLACKLIST = [
    ".ssh", ".gnupg", ".config/pulse", ".config/waydroid", ".local/share/waydroid",
    "venv", ".venv", "env", "node_modules", ".cache", ".mozilla", ".thunderbird",
]

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "write_desktop",
        "description": (
            "USAR CUANDO el usuario pida GUARDAR, CREAR o EXPORTAR un archivo en su carpeta personal. "
            "Ejemplos: 'guarda el resumen en ~/Documentos/informe.md', 'crea una carpeta con los datos', "
            "'exporta la lista a CSV en el escritorio'. Escribe SOLO dentro de /home/aegis2 y nunca en "
            "rutas de sistema (.ssh, .gnupg, venv…). El orquestador pedirá autorización antes de escribir. "
            "NO usar para: leer (read_file), buscar (rag_search/web_search), ni borrar (no permitido)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ruta": {"type": "string", "description": "Ruta destino bajo /home/aegis2 (admite ~)"},
                "contenido": {"type": "string", "description": "Texto a escribir"},
                "modo": {"type": "string", "description": "'crear' (defecto) o 'append'"},
                "dry_run": {"type": "boolean", "description": "true simula sin tocar disco (defecto en CLI)"},
            },
            "required": ["ruta", "contenido"],
        },
    },
}


def _peligrosa(p: Path) -> str | None:
    try:
        rel = p.expanduser().resolve().relative_to(RAIZ)
    except (ValueError, FileNotFoundError):
        return "fuera de la raíz permitida"
    partes = rel.parts
    for i, comp in enumerate(partes):
        if comp in BLACKLIST or any(comp.startswith(b + ".") for b in BLACKLIST):
            return "ruta en blacklist: " + "/".join(partes[: i + 1])
    return None


def _valida(ruta: Path) -> str | None:
    err = _peligrosa(ruta)
    if err:
        return err
    return None


def execute(*args, **kwargs) -> str:
    params: dict = {}
    for a in args:
        if isinstance(a, dict):
            params.update(a)
    params.update({k: v for k, v in kwargs.items() if v is not None})
    ruta = Path(str(params.get("ruta", "")).strip())
    contenido = str(params.get("contenido", ""))
    modo = str(params.get("modo", "crear")).lower()
    dry = bool(params.get("dry_run", True))  # CLI: seguro por defecto

    if not ruta or not contenido:
        return "⚠️ write_desktop necesita 'ruta' y 'contenido'."
    err = _valida(ruta)
    if err:
        return f"🚫 {err}. Acción cancelada."
    if len(contenido.encode("utf-8")) > 2_000_000:
        return "🚫 Contenido >2 MB. Divide en varios archivos."

    ruta.parent.mkdir(parents=True, exist_ok=True)
    existe = ruta.exists()
    if dry:
        accion = (
            "SOBREESCRIBIRÁ (con backup)"
            if existe and modo == "crear"
            else "CREARÁ" if not existe else "AÑADIRÁ a"
        )
        return (
            f"🔎 SIMULACIÓN\n  {accion}: {ruta}\n  Bytes: {len(contenido.encode())}\n"
            f"  Vista:\n  {contenido[:200]}"
        )
    if existe and modo == "crear":
        shutil.copy2(ruta, str(ruta) + f".bak.{int(time.time())}")
    with open(ruta, "a" if modo == "append" else "w", encoding="utf-8") as f:
        f.write(contenido)
    return f"✔ Escrito: {ruta} · {ruta.stat().st_size} bytes" + (
        "  (backup .bak)" if existe and modo == "crear" else ""
    )


write_desktop = execute

if __name__ == "__main__":
    print(execute(ruta=sys.argv[1], contenido=sys.argv[2] if len(sys.argv) > 2 else "prueba"))
