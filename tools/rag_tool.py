import os
import sqlite3
import hashlib
from pathlib import Path
from typing import List, Dict, Any
import json

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "rag_search",
        "description": "Búsqueda semántica en documentos locales (PDFs/MD/TXT) con embeddings. Usar solo por CLI: indexa folder primero, luego busca.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texto de búsqueda semántica"},
                "path": {"type": "string", "description": "Ruta al folder con documentos a indexar (opcional, usa indexado previo)"}
            },
            "required": ["query"]
        }
    }
}
def _ensure_index_dir() -> Path:
    """Retorna la carpeta del índice RAG: ~/.local/share/ollama-chat-gui/"""
    home = Path.home()
    index_dir = home / ".local" / "share" / "ollama-chat-gui"
    index_dir.mkdir(parents=True, exist_ok=True)
    return index_dir
def _get_db_path(index_dir: Path) -> Path:
    """Retorna la ruta a la base de datos SQLite del índice."""
    return index_dir / "rag_index.db"
def _create_tables(conn: sqlite3.Connection):
    """Crea las tablas para el índice RAG si no existen."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE,
            filename TEXT,
            content TEXT,
            hash TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER,
            chunk_index INTEGER,
            content TEXT,
            embedding BLOB,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS index_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
def _read_text_from_file(path: Path) -> str:
    """Lee texto plano de un archivo PDF, MD o TXT."""
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            import pypdf
            with open(path, "rb") as f:
                reader = pypdf.PdfReader(f)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() or ""
                return text
        elif ext in [".md", ".txt"]:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            return ""
    except Exception:
        return ""
def _chunk_text(text: str, chunk_size: int = 900, overlap: int = 180) -> List[str]:
    """Divide texto en chunks con solape especificado."""
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunk = text[start:end]
        
        if chunk.strip():
            chunks.append(chunk.strip())
        
        if end == text_length:
            break
            
        start = max(start, end - overlap)
    
    return chunks
def _generate_embedding(text: str) -> List[float]:
    """Genera embedding usando la API de Ollama con nomic-embed-text."""
    try:
        import ollama
        response = ollama.embeddings(
            model="nomic-embed-text",
            prompt=text
        )
        return response.get("embedding", [])
    except Exception:
        return []
def execute(query: str, path: str = None) -> str:
    """Ejecuta búsqueda RAG. Si path se da, indexa el folder primero.
    
    Para usar: "indexa /ruta/a/docs" -> indexa el folder con archivos PDF/MD/TXT
    Para buscar: "qué dice sobre X" -> busca en índice existente (similaridad >0.30)
    """
    index_dir = _ensure_index_dir()
    db_path = _get_db_path(index_dir)
    
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        
        if path:
            # Indexar folder
            index_dir_path = Path(path)
            if not index_dir_path.exists():
                return f"Error: carpeta '{path}' no existe"
            
            _create_tables(conn)
            
            # Encontrar todos los archivos PDF/MD/TXT
            files = []
            for ext in [".pdf", ".md", ".txt"]:
                files.extend(index_dir_path.glob(f"**/*.{ext}"))
            
            if not files:
                return f"Error: no se encontraron archivos PDF/MD/TXT en '{path}'"
            
            # Indexar cada archivo
            indexed_count = 0
            for file_path in files:
                file_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
                
                cursor = conn.execute(
                    "SELECT id FROM documents WHERE path = ? AND hash = ?",
                    (str(file_path), file_hash)
                )
                
                if cursor.fetchone():
                    continue
                
                content = _read_text_from_file(file_path)
                if not content.strip():
                    continue
                
                cursor = conn.execute(
                    "INSERT INTO documents (path, filename, content, hash) VALUES (?, ?, ?, ?)",
                    (str(file_path), file_path.name, content, file_hash)
                )
                doc_id = cursor.lastrowid
                
                chunks = _chunk_text(content)
                for i, chunk_content in enumerate(chunks):
                    embedding = _generate_embedding(chunk_content)
                    if embedding:
                        cursor = conn.execute(
                            "INSERT INTO chunks (doc_id, chunk_index, content, embedding) VALUES (?, ?, ?, ?)",
                            (doc_id, i, chunk_content, json.dumps(embedding))
                        )
                
                indexed_count += 1
            
            conn.commit()
            conn.close()
            
            return f"Indexado {indexed_count} documento(s) en '{path}'. Total chunks: {len(list(conn.execute('SELECT COUNT(*) FROM chunks'))[0])}"
        
        else:
            # Solo búsqueda
            query_embedding = _generate_embedding(query)
            if not query_embedding:
                return "Error: no se pudo generar embedding para la búsqueda"
            
            cursor = conn.execute("""
                SELECT c.content, c.chunk_index, d.path, d.filename,
                       json_array_length(embedding) as emb_len,
                       json_each(embedding)
                FROM chunks c
                JOIN documents d ON c.doc_id = d.id
                ORDER BY c.id
            """)
            
            all_chunks = cursor.fetchall()
            
            if not all_chunks:
                return "Error: índice RAG vacío. Indexa un folder primero."
            
            # Calcular similitud coseno con query (embeddings simplificados para demo)
            results = []
            for row in all_chunks:
                chunk_content = row["content"]
                chunk_embedding = json.loads(row["embedding"]) if row["embedding"] else []
                
                if chunk_embedding and len(chunk_embedding) == len(query_embedding):
                    # Similitud coseno simplificada (correr en producción)
                    dot_product = sum(a * b for a, b in zip(chunk_embedding, query_embedding))
                    norm_a = sum(a * a for a in chunk_embedding) ** 0.5
                    norm_b = sum(b * b for b in query_embedding) ** 0.5
                    
                    if norm_a > 0 and norm_b > 0:
                        similarity = dot_product / (norm_a * norm_b)
                        if similarity > 0.30:
                            results.append({
                                "content": chunk_content,
                                "similarity": similarity,
                                "path": row["path"],
                                "filename": row["filename"]
                            })
            
            conn.close()
            
            if not results:
                return "No se encontraron fragmentos relevantes (similitud >0.30)."
            
            # Ordenar por similitud descendente y mostrar resultados
            results.sort(key=lambda x: x["similarity"], reverse=True)
            
            output = f"Encontrados {len(results)} fragmentos relevantes:\n\n"
            
            for i, result in enumerate(results[:10], 1):
                output += f"{i}. [{result['filename']}] Similitud: {result['similarity']:.3f}\n"
                output += f"   {result['content'][:200]}...\n"
                output += f"   Fuente: {result['path']}\n\n"
            
            return output
            
    except Exception as e:
        return f"Error RAG: {e}"