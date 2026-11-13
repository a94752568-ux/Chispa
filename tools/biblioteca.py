#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
biblioteca.py - Biblioteca de libros PDF de referencia para Chispa.

Alberto agrega libros PDF (sociologia, programacion, lo que quiera) y Chispa
puede BUSCAR semanticamente dentro de ellos (bge-m3, 100% local) para
explicar temas citando libro y pagina. Complementa al modo maestro (/maestro).

Acciones (parametro "accion"):
- estado:   cuantos libros, paginas, fragmentos indexados, tamano.
- agregar:  extrae el texto de un PDF (ruta local) por paginas y lo guarda
            en fragmentos. Requiere pypdf (pip install pypdf).
- indexar:  vectoriza los fragmentos aun sin indice con bge-m3 (Ollama local).
- listar:   libros REALES de la biblioteca (NO inventar titulos).
- buscar:   busqueda SEMANTICA en los libros: devuelve libro, pagina y fragmento.
- leer:     texto de una pagina concreta de un libro.

Almacenamiento: ~/.local/share/Chispa/biblioteca/
- libros.json         metadatos (titulo, ruta original, paginas, chunks).
- <slug>.jsonl.gz     fragmentos de texto por libro ({"p": pagina, "x": texto}).
- embeddings.jsonl.gz indice semantico {"libro","pag","x","v","m"}.

Sin dependencias nuevas obligatorias: pypdf para extraer PDF (avisar comando
exacto si falta) y ollama (ya usado por la app) para embeddings.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from tools.http_session import http_get  # sesion compartida (no usada aun, por consistencia)
from tools.wiki_offline import _embed_lote, _coseno, _EMBED_MODEL  # reutiliza bge-m3

BIB_DIR = Path(os.environ.get("BIBLIOTECA_DIR", str(Path.home() / ".local/share/Chispa/biblioteca")))
LIBROS = BIB_DIR / "libros.json"
IDX = BIB_DIR / "embeddings.jsonl.gz"

_CHUNK = 1200      # caracteres por fragmento
_SOLAPE = 150      # solape entre fragmentos de la misma pagina
_BUSCAR_MAX = 3
_FRAG_MAX = 1100   # recorte del fragmento devuelto (bajo TOOL_RESULT_MAX=3500)
_LEER_MAX = 3000
_SIMILAR_MIN = 0.30

_LAST_DIAG = ""

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "biblioteca",
        "description": (
            "Biblioteca PERSONAL de libros PDF de referencia (sociologia, programacion, etc.) "
            "indexados localmente. USAR CUANDO el usuario pregunte un tema academico o de "
            "programacion que pueda estar en sus libros, pida explicar un concepto 'segun mis "
            "libros', o use el modo maestro (/maestro). Acciones: estado, agregar (ruta de un "
            "PDF, requiere pypdf), indexar (vectoriza con bge-m3), listar (titulos REALES; "
            "NUNCA inventes libros), buscar (busqueda semantica: devuelve libro, pagina y "
            "fragmento; cita SIEMPRE el libro y la pagina), leer (pagina concreta). Todo "
            "OFFLINE. NO sirve para archivos sueltos (usa rag_search/read_file) ni enciclopedia "
            "general (usa wiki_offline)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "accion": {"type": "string", "enum": ["estado", "agregar", "indexar", "listar", "buscar", "leer"],
                            "description": "Que hacer. Defecto: buscar"},
                "consulta": {"type": "string", "description": "Concepto o tema a buscar (accion=buscar)"},
                "ruta": {"type": "string", "description": "Ruta local del PDF (accion=agregar), ej: ~/Libros/libro.pdf"},
                "titulo": {"type": "string", "description": "Titulo del libro (accion=leer); usa listar para verlos"},
                "pagina": {"type": "integer", "description": "Numero de pagina (accion=leer)"},
                "max_resultados": {"type": "integer", "description": "Resultados de buscar (defecto 3, max 5)"},
            },
            "required": [],
        },
    },
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _slug(titulo: str) -> str:
    s = _norm(titulo or "libro")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s or "libro")[:60]


def _cargar_libros() -> list:
    if not LIBROS.exists():
        return []
    try:
        return json.loads(LIBROS.read_text(encoding="utf-8"))
    except Exception:
        return []


def _guardar_libros(libros: list):
    BIB_DIR.mkdir(parents=True, exist_ok=True)
    LIBROS.write_text(json.dumps(libros, ensure_ascii=False, indent=2), encoding="utf-8")


def _archivo_libro(slug: str) -> Path:
    return BIB_DIR / (slug + ".jsonl.gz")


def _iterar_fragmentos(slug: str):
    f = _archivo_libro(slug)
    if not f.exists():
        return
    with gzip.open(f, "rt", encoding="utf-8") as fh:
        for linea in fh:
            try:
                d = json.loads(linea)
                if d.get("x"):
                    yield int(d.get("p", 0)), d["x"]
            except Exception:
                continue


def _accion_estado() -> str:
    libros = _cargar_libros()
    if not libros:
        return ("📭 Biblioteca vacia. Agrega un PDF con accion=agregar y ruta "
                "(ej: ruta=~/Libros/mi_libro.pdf). Requiere pypdf: pip install pypdf")
    n_chunks = sum(l.get("chunks", 0) for l in libros)
    indexados = 0
    if IDX.exists():
        try:
            with gzip.open(IDX, "rt", encoding="utf-8") as fh:
                for linea in fh:
                    try:
                        d = json.loads(linea)
                        if d.get("v") and d.get("m", "") == _EMBED_MODEL:
                            indexados += 1
                    except Exception:
                        continue
        except Exception:
            pass
    lineas = [f"📚 Biblioteca: {len(libros)} libro(s), {n_chunks} fragmentos, {indexados} vectorizados con {_EMBED_MODEL}."]
    for l in libros:
        estado = "✅ indexado" if l.get("chunks", 0) <= _contar_indexados(l.get("slug", "")) else "⏳ sin indexar (accion=indexar)"
        lineas.append(f"  - {l.get('titulo', '?')} ({l.get('paginas', '?')} pag, {l.get('chunks', 0)} frag) {estado}")
    return "\n".join(lineas)


def _contar_indexados(slug: str) -> int:
    n = 0
    if not IDX.exists():
        return 0
    try:
        with gzip.open(IDX, "rt", encoding="utf-8") as fh:
            for linea in fh:
                try:
                    d = json.loads(linea)
                    if d.get("libro") == slug and d.get("v") and d.get("m", "") == _EMBED_MODEL:
                        n += 1
                except Exception:
                    continue
    except Exception:
        pass
    return n


def _accion_agregar(ruta: str) -> str:
    ruta = (ruta or "").strip()
    if not ruta:
        return "⚠️ Indica la ruta del PDF (ej: ruta=~/Libros/mi_libro.pdf)."
    ruta = os.path.expanduser(ruta)
    if not os.path.isfile(ruta):
        return f"⚠️ No existe el archivo: {ruta}"
    if not ruta.lower().endswith(".pdf"):
        return "⚠️ Solo acepto PDFs por ahora."
    try:
        from pypdf import PdfReader
    except Exception:
        return ("⚠️ Falta pypdf para extraer texto de PDFs. Instalalo en el venv de Chispa: "
                "pip install pypdf")
    try:
        reader = PdfReader(ruta)
    except Exception as e:
        return f"⚠️ No pude abrir el PDF ({e}). ¿Esta protegido con contrasena o danado?"
    titulo = Path(ruta).stem.replace("_", " ").strip() or "Libro sin titulo"
    libros = _cargar_libros()
    slug = _slug(titulo)
    # anti-duplicado: mismo slug reemplaza la version anterior
    libros = [l for l in libros if l.get("slug") != slug]
    BIB_DIR.mkdir(parents=True, exist_ok=True)
    paginas_ok = 0
    chunks = 0
    tmp = _archivo_libro(slug).with_suffix(".tmp")
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as out:
            for i, pag in enumerate(reader.pages, start=1):
                try:
                    texto = pag.extract_text() or ""
                except Exception:
                    texto = ""
                texto = re.sub(r"[ \t]+", " ", texto).strip()
                if len(texto) < 80:
                    continue  # pagina vacia o escaneada sin OCR
                paginas_ok += 1
                paso = _CHUNK - _SOLAPE
                for ini in range(0, len(texto), paso):
                    frag = texto[ini:ini + _CHUNK]
                    if len(frag) < 100:
                        break
                    out.write(json.dumps({"p": i, "x": frag}, ensure_ascii=False) + "\n")
                    chunks += 1
        tmp.replace(_archivo_libro(slug))
    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return f"⚠️ Error extrayendo el texto: {e}"
    if chunks == 0:
        _archivo_libro(slug).unlink(missing_ok=True)
        return ("⚠️ El PDF no tiene texto extraible (parece escaneado sin OCR). "
                "Necesitaria OCR, que no esta implementado aun.")
    libros.append({"slug": slug, "titulo": titulo, "ruta": ruta, "paginas": len(reader.pages),
                   "paginas_texto": paginas_ok, "chunks": chunks,
                   "agregado": datetime.now().isoformat(timespec="seconds")})
    _guardar_libros(libros)
    return (f"✅ Agregado '{titulo}': {paginas_ok} paginas con texto, {chunks} fragmentos. "
            "Ahora ejecuta accion=indexar para poder buscar semanticamente.")


def _accion_indexar() -> str:
    libros = _cargar_libros()
    if not libros:
        return "📭 Biblioteca vacia (accion=agregar primero)."
    previos = {}
    if IDX.exists():
        try:
            with gzip.open(IDX, "rt", encoding="utf-8") as fh:
                for linea in fh:
                    try:
                        d = json.loads(linea)
                        # solo se conservan vectores del modelo actual de libros existentes
                        if d.get("libro") and d.get("v") and d.get("m", "") == _EMBED_MODEL:
                            previos[(d["libro"], d.get("pag", 0), d.get("x", "")[:80])] = d
                    except Exception:
                        continue
        except Exception:
            previos = {}
    slugs_validos = {l["slug"] for l in libros}
    previos = {k: v for k, v in previos.items() if k[0] in slugs_validos}
    pendientes = []
    for l in libros:
        for pag, texto in _iterar_fragmentos(l["slug"]):
            k = (l["slug"], pag, texto[:80])
            if k not in previos:
                pendientes.append((l["slug"], pag, texto))
    escritos = len(previos)
    tmp = IDX.with_suffix(".tmp")
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as out:
            for d in previos.values():
                out.write(json.dumps(d, ensure_ascii=False) + "\n")
            for i in range(0, len(pendientes), 16):
                lote = pendientes[i:i + 16]
                textos = [f"{slug.replace('-', ' ')}, pag {pag}. {texto[:800]}" for slug, pag, texto in lote]
                embs = _embed_lote_ollama(textos)
                if embs is None:
                    return ("⚠️ Ollama no respondio generando embeddings. ¿Esta corriendo con el "
                            "modelo " + _EMBED_MODEL + "? (ollama pull " + _EMBED_MODEL + ")")
                for (slug, pag, texto), v in zip(lote, embs):
                    if v:
                        out.write(json.dumps({"libro": slug, "pag": pag, "x": texto[:_FRAG_MAX],
                                              "v": v, "m": _EMBED_MODEL}, ensure_ascii=False) + "\n")
                        escritos += 1
        tmp.replace(IDX)
    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return f"⚠️ Error indexando: {e}"
    return (f"🧠 Biblioteca indexada: {escritos} fragmentos vectorizados con {_EMBED_MODEL}. "
            "Ya puedes usar accion=buscar.")


def _embed_lote_ollama(textos: list):
    """Wrapper local sobre _embed_lote (importada de wiki_offline)."""
    try:
        import ollama as _ollama_mod
        cliente = _ollama_mod.Client()
    except Exception:
        return None
    return _embed_lote(cliente, textos)


def _accion_listar() -> str:
    libros = _cargar_libros()
    if not libros:
        return "📭 Biblioteca vacia (accion=agregar con la ruta de un PDF)."
    lineas = [f"📚 Biblioteca: {len(libros)} libro(s). Titulos REALES (NO inventes otros):"]
    for l in libros:
        lineas.append(f"  - {l.get('titulo', '?')} — {l.get('paginas', '?')} paginas, {l.get('chunks', 0)} fragmentos")
    return "\n".join(lineas)


def _accion_buscar(consulta: str, max_resultados) -> str:
    consulta = (consulta or "").strip()
    if not consulta:
        return "⚠️ Indica que buscar (consulta), ej: consulta='que es la anomia'."
    libros = _cargar_libros()
    if not libros:
        return "📭 Biblioteca vacia. Agrega PDFs con accion=agregar."
    total_chunks = sum(l.get("chunks", 0) for l in libros)
    indexados = sum(_contar_indexados(l["slug"]) for l in libros)
    if indexados == 0:
        return "🧠 Los libros aun no estan indexados. Ejecuta accion=indexar (una vez, local)."
    if indexados < total_chunks:
        aviso = f" (indice parcial: {indexados}/{total_chunks}; ejecuta accion=indexar para completar)"
    else:
        aviso = ""
    embs = _embed_lote_ollama([consulta])
    if not embs or not embs[0]:
        return "⚠️ Ollama no disponible para la busqueda semantica (¿ollama serve apagado?)."
    qv = embs[0]
    try:
        max_resultados = max(1, min(int(max_resultados or _BUSCAR_MAX), 5))
    except Exception:
        max_resultados = _BUSCAR_MAX
    mejores = []  # (sim, slug, pag, texto)
    titulos = {l["slug"]: l.get("titulo", l["slug"]) for l in libros}
    try:
        with gzip.open(IDX, "rt", encoding="utf-8") as fh:
            for linea in fh:
                try:
                    d = json.loads(linea)
                    if not (d.get("v") and d.get("m", "") == _EMBED_MODEL):
                        continue
                    sim = _coseno(qv, d["v"])
                    if sim >= _SIMILAR_MIN:
                        mejores.append((sim, d.get("libro", "?"), int(d.get("pag", 0)), d.get("x", "")))
                except Exception:
                    continue
    except Exception as e:
        return f"⚠️ Indice de embeddings danado ({e}). Ejecuta accion=indexar."
    if not mejores:
        return (f"🔎 Sin resultados en la biblioteca para '{consulta}'{aviso}. "
                "Prueba otras palabras o verifica que el tema este en tus libros (accion=listar).")
    mejores.sort(key=lambda m: m[0], reverse=True)
    partes = [f"📖 Resultados en tu biblioteca para '{consulta}'{aviso}:"]
    for i, (sim, slug, pag, texto) in enumerate(mejores[:max_resultados], 1):
        partes.append(f"\n{i}. **{titulos.get(slug, slug)}** — pagina {pag} (relevancia {sim:.2f})\n{texto[:_FRAG_MAX].strip()}")
    return "\n".join(partes)


def _accion_leer(titulo: str, pagina) -> str:
    titulo = (titulo or "").strip()
    libros = _cargar_libros()
    if not libros:
        return "📭 Biblioteca vacia (accion=agregar)."
    objetivo = _norm(titulo)
    libro = None
    if objetivo:
        for l in libros:
            if objetivo in _norm(l.get("titulo", "")):
                libro = l
                break
    else:
        libro = libros[0]
    if libro is None:
        return f"⚠️ No hay un libro que coincida con '{titulo}'. Usa accion=listar para ver los titulos reales."
    try:
        pagina = int(pagina or 1)
    except Exception:
        pagina = 1
    textos = [x for p, x in _iterar_fragmentos(libro["slug"]) if p == pagina]
    if not textos:
        return (f"⚠️ La pagina {pagina} de '{libro['titulo']}' no tiene texto indexado "
                f"(paginas con texto: {libro.get('paginas_texto', '?')}). Puede ser escaneada sin OCR.")
    cuerpo = "\n\n".join(textos)[:_LEER_MAX]
    cola = "\n[… pagina recortada]" if len("\n\n".join(textos)) > _LEER_MAX else ""
    return f"📖 **{libro['titulo']}** — pagina {pagina}\n\n{cuerpo}{cola}"


def execute(accion: str = "buscar", consulta: str = "", ruta: str = "", titulo: str = "",
            pagina=None, max_resultados=_BUSCAR_MAX, **kwargs) -> str:
    try:
        accion = str(accion or kwargs.get("action", "") or "buscar").strip().lower()
        consulta = str(consulta or kwargs.get("query", "") or kwargs.get("tema", "") or "")
        ruta = str(ruta or kwargs.get("path", "") or kwargs.get("archivo", "") or kwargs.get("pdf", "") or "")
        titulo = str(titulo or kwargs.get("libro", "") or "")
        if accion == "estado":
            return _accion_estado()
        if accion == "agregar":
            return _accion_agregar(ruta)
        if accion == "indexar":
            return _accion_indexar()
        if accion == "listar":
            return _accion_listar()
        if accion == "leer":
            return _accion_leer(titulo, pagina)
        if accion == "buscar":
            return _accion_buscar(consulta, max_resultados)
        return ("⚠️ Accion desconocida: " + accion + ". Usa: estado, agregar, indexar, listar, buscar, leer.")
    except Exception as e:
        return f"Error en biblioteca: {e}"


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if args and args[0] == "agregar":
        print(execute(accion="agregar", ruta=args[1] if len(args) > 1 else ""))
    elif args:
        print(execute(accion=args[0], consulta=" ".join(args[1:])))
    else:
        print(execute(accion="estado"))
