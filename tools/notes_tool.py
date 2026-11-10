import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "notes_tool",
        "description": "USAR CUANDO el usuario pida recordar/guardar algo para el futuro ('recuerda que...', 'apunta esto:...') o pregunte por notas previas ('¿qué te pedí que recordaras?', '¿qué anotaste de...?'). action='capture' guarda una nota (requiere note); action='search' busca entre las notas (requiere query).",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["capture", "search"], "description": "Acción a realizar: 'capture' para guardar nota, 'search' para buscar"},
                "note": {"type": "string", "description": "Texto de la nota a capturar (requerido si action='capture')"},
                "query": {"type": "string", "description": "Texto de búsqueda (requerido si action='search')"}
            },
            "required": ["action"]
        }
    }
}
def _get_notes_dir() -> Path:
    """Retorna la carpeta principal de notas: ~/Notas/"""
    return Path.home() / "Notas"
def _get_daily_file() -> Path:
    """Retorna el archivo diario para hoy: ~/Notas/diario/YYYY-MM-DD.md"""
    notes_dir = _get_notes_dir()
    daily_dir = notes_dir / "diario"
    daily_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    return daily_dir / f"{today}.md"
def _load_existing_notes() -> str:
    """Carga todas las notas existentes desde la carpeta de notas para reindexado."""
    notes_dir = _get_notes_dir()
    all_notes = []
    
    for md_file in list(notes_dir.glob("*.md")) + list((notes_dir / "diario").glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
            all_notes.append(content)
        except Exception:
            continue
    
    return "\n\n".join(all_notes)
def _search_notes(query: str) -> str:
    """Busca notas usando el sistema RAG B1 (rag_search)."""
    try:
        from tools.rag_tool import execute as rag_execute
        
        # Usar el RAG para buscar notas
        result = rag_execute(query=query)
        return result
    except Exception as e:
        return f"Error buscando notas: {e}"
def execute(action: str, note: str = None, query: str = None) -> str:
    """Ejecuta captura o búsqueda de notas."""
    try:
        if action == "capture":
            if not note:
                return "Error: parámetro 'note' requerido para captura."
            
            # Guardar nota en archivo diario
            daily_file = _get_daily_file()
            # Append: antes write_text SOBREESCRIBÍA el diario y la
            # nota anterior del mismo día se perdía.
            with daily_file.open("a", encoding="utf-8") as f:
                f.write(f"## {datetime.now().strftime('%Y-%m-%d %H:%M')}\n{note}\n\n")
            
            # Reindexar incrementalmente (<5s)
            reindex_start = datetime.now()
            all_notes = _load_existing_notes()
            
            if all_notes:
                # Usar RAG para reindexar
                try:
                    from tools.rag_tool import execute as rag_execute
                    rag_execute(query=all_notes)
                    reindex_time = (datetime.now() - reindex_start).total_seconds()
                    return f"Nota capturada en {daily_file}. Reindexado en {reindex_time:.2f}s."
                except Exception as rag_error:
                    reindex_time = (datetime.now() - reindex_start).total_seconds()
                    return f"Nota capturada en {daily_file}. Reindexado parcialmente en {reindex_time:.2f}s (RAG: {rag_error})."
            
            return f"Nota capturada en {daily_file}."
        
        elif action == "search":
            if not query:
                return "Error: parámetro 'query' requerido para búsqueda."
            
            return _search_notes(query)
        
        else:
            return f"Error: acción '{action}' no válida. Usar 'capture' o 'search'."
    
    except Exception as e:
        return f"Error notas_tool: {e}"