from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "USAR CUANDO necesites leer el contenido de un archivo de texto del proyecto (código, config, notas) para responder sobre él ('¿qué hay en settings.json?', 'mira el README'). Solo rutas dentro del directorio del proyecto; hasta 20,000 caracteres; no lee binarios.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Ruta absoluta o relativa al archivo dentro del proyecto"}
            },
            "required": ["path"]
        }
    }
}

def execute(path: str) -> str:
    try:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = BASE_DIR / p
        p = p.resolve()

        if BASE_DIR not in p.parents and p != BASE_DIR:
            return f"Acceso denegado: ruta fuera del directorio permitido ({BASE_DIR})"

        if not p.exists():
            return f"Archivo no existe: {path}"
        if p.is_dir():
            return f"Es un directorio, no un archivo: {path}"
        if p.stat().st_size > 20000:
            return f"Archivo muy grande ({p.stat().st_size} bytes). Mostrando primeros 20000 caracteres.\n\n{p.read_text(encoding='utf-8', errors='ignore')[:20000]}"
        return p.read_text(encoding='utf-8', errors='ignore')
    except Exception as e:
        return f"Error leyendo {path}: {e}"
