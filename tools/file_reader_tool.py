from pathlib import Path
import os

RAIZ = Path(os.environ.get("READER_ROOT", str(Path.home()))).expanduser().resolve()

# Rutas que nunca se leen aunque estén bajo la carpeta personal
BLACKLIST = {".ssh", ".gnupg", "venv", ".venv", "env", "node_modules",
             "__pycache__", ".cache", ".mozilla", ".thunderbird"}

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "USAR CUANDO necesites leer el contenido de un archivo de texto de su carpeta personal (código, config, notas, documentos exportados) para responder sobre él ('mira ~/Documentos/informe.md', '¿qué hay en settings.json?'). Solo rutas dentro de ~ (nunca .ssh, venv, .cache…); hasta 20,000 caracteres; no lee binarios. Para buscar archivos por NOMBRE usa find_files.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Ruta absoluta o relativa a ~ del archivo a leer"}
            },
            "required": ["path"]
        }
    }
}


def _permitida(p: Path) -> bool:
    try:
        rel = p.relative_to(RAIZ)
    except ValueError:
        return False
    return not any(c in BLACKLIST for c in rel.parts)


def execute(path: str) -> str:
    try:
        raw = str(path or "").strip()
        if not raw:
            return "⚠️ read_file necesita 'path'."

        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = RAIZ / p
        p = p.resolve()

        if not _permitida(p):
            return f"Acceso denegado: fuera de la carpeta personal o en ruta protegida ({p})"

        if not p.exists():
            return f"Archivo no existe: {path}"
        if p.is_dir():
            return f"Es un directorio, no un archivo: {path}. Para buscar por nombre usa find_files."

        data = p.read_text(encoding="utf-8", errors="ignore")
        if "\x00" in data[:2000]:
            return f"🚫 Archivo binario: {path}. read_file solo lee texto."
        if len(data) > 20000:
            return (f"Archivo muy grande ({p.stat().st_size} bytes). "
                    f"Mostrando primeros 20000 caracteres.\n\n{data[:20000]}")
        return data
    except Exception as e:
        return f"Error leyendo {path}: {e}"
