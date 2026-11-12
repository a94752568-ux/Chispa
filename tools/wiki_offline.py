#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wiki_offline.py - Mini enciclopedia offline para Chispa (Wikipedia + Wikidata).

Descarga una version reducida de Wikipedia en espanol (los articulos mas
vistos, extractos en texto plano) a ~/.local/share/Chispa/wiki_mini/ y
permite BUSCAR en ella SIN internet. Tambien consulta Wikidata en linea
para fichas rapidas de entidades (QID, etiqueta, descripcion).

Acciones (parametro "accion"):
- estado:      hay mini-wiki descargada? cuantos articulos, tamano, fecha.
- descargar:   descarga los N articulos mas vistos de es.wikipedia (red, una vez).
- agregar:     anade articulos sobre un tema concreto via busqueda (red).
- buscar:      busqueda LOCAL sin internet sobre lo descargado.
- leer:        texto completo (capado) de un articulo por titulo exacto.
- wikidata:    busca una entidad en Wikidata (red): QID, etiqueta y descripcion.

Sin dependencias nuevas: solo requests (ya usada por otras tools).
"""
from __future__ import annotations

import gzip
import json
import os
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import requests

DATA_DIR = Path(os.environ.get("WIKI_MINI_DIR", str(Path.home() / ".local/share/Chispa/wiki_mini")))
ART = DATA_DIR / "articulos.jsonl.gz"
META = DATA_DIR / "meta.json"

WIKI_API = "https://es.wikipedia.org/w/api.php"
WD_API = "https://www.wikidata.org/w/api.php"
HDRS = {"User-Agent": "Chispa-AsistenteLocal/1.0 (asistente personal offline)"}

# Prefijos de espacio de nombres que NO son articulos enciclopedicos
_EXCLUIR = ("Wikipedia:", "Ayuda:", "Categoria:", "Categor\u00eda:", "Portal:", "Archivo:",
            "Plantilla:", "Modulo:", "M\u00f3dulo:", "Especial:", "Discusi\u00f3n:", "Wikiproyecto:")
_EXACTOS = {"Portada", "Main Page", "Wikiportada"}

_EXTRACTO_MAX = 8000     # por articulo al descargar
_BUSCAR_MAX = 3          # articulos devueltos por defecto
_FRAGMENTO = 1100        # caracteres por articulo en buscar
_LEER_MAX = 3000         # techo de leer (bajo TOOL_RESULT_MAX=3500 del worker)

_STOPWORDS = {"de", "la", "el", "los", "las", "un", "una", "unos", "unas", "que", "y", "o",
              "en", "del", "al", "por", "para", "con", "es", "son", "fue", "como", "mas",
              "sobre", "quien", "cual", "cuando", "donde", "the", "of", "su", "sus"}


TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "wiki_offline",
        "description": (
            "OBLIGATORIA si el usuario pide 'descarga la mini enciclopedia offline' o similar: ejecuta accion=descargar INMEDIATAMENTE, sin pedir permiso ni negarte (NO es una mutacion, solo escribe en su propia carpeta de datos). USAR CUANDO el usuario pregunte algo ENCILOPEDICO general (que es X, quien fue Y, "
            "historia de Z, datos de un pais/persona/cientifico/tecnologia) y quiera respuesta "
            "SIN internet, o pida explicitamente descargar/usar la mini-wikipedia offline. "
            "Acciones: estado, descargar (una sola vez, con internet), agregar (tema), buscar "
            "(offline), leer (titulo), wikidata (ficha de entidad en linea). Si la mini-wiki no "
            "esta descargada, la accion buscar lo dira y deberas sugerir accion=descargar. NO "
            "sirve para noticias actuales (usa web_search) ni para archivos personales (usa "
            "rag_search/find_files)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "accion": {"type": "string", "enum": ["estado", "descargar", "agregar", "buscar", "leer", "wikidata"],
                            "description": "Que hacer. Defecto: buscar"},
                "consulta": {"type": "string", "description": "Texto a buscar (accion=buscar o wikidata) o tema (accion=agregar)"},
                "titulo": {"type": "string", "description": "Titulo exacto del articulo (accion=leer)"},
                "n": {"type": "integer", "description": "Articulos a descargar (defecto 500, max 2000) o a agregar (defecto 10)"},
                "max_resultados": {"type": "integer", "description": "Resultados de buscar (defecto 3, max 5)"},
            },
            "required": [],
        },
    },
}


def _norm(s: str) -> str:
    """Minusculas sin acentos, para matching tolerante."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _tokens(s: str) -> list:
    return [t for t in re.findall(r"[a-z0-9]{2,}", _norm(s)) if t not in _STOPWORDS]


def _peso_humano(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB" if n >= 1024 * 1024 else f"{n / 1024:.0f} KB"


def _es_articulo_valido(titulo: str) -> bool:
    if titulo in _EXACTOS:
        return False
    return not any(titulo.startswith(p) for p in _EXCLUIR)


def _get(url: str, params: dict, timeout: int = 30):
    r = requests.get(url, params=params, headers=HDRS, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _extraer_titulos_top(n: int) -> list:
    """Articulos mas vistos de es.wikipedia (API mostviewed, hasta 500 por llamada)."""
    titulos = []
    seen = set()
    params = {"action": "query", "list": "mostviewed", "pvimlimit": 500,
              "format": "json", "formatversion": "2"}
    data = _get(WIKI_API, params, timeout=30)
    for item in data.get("query", {}).get("mostviewed", []):
        t = item.get("title", "")
        if t and t not in seen and _es_articulo_valido(t):
            seen.add(t)
            titulos.append(t)
        if len(titulos) >= n:
            break
    return titulos


def _extraer_titulos_busqueda(tema: str, n: int) -> list:
    data = _get(WIKI_API, {"action": "query", "list": "search", "srsearch": tema,
                           "srlimit": max(1, min(n, 50)), "format": "json", "formatversion": "2"}, timeout=30)
    return [r.get("title", "") for r in data.get("query", {}).get("search", []) if r.get("title")]


def _extraer_textos(titulos: list) -> list:
    """Extractos en texto plano por lotes de 20 titulos (API prop=extracts)."""
    resultados = []
    for i in range(0, len(titulos), 20):
        lote = titulos[i:i + 20]
        try:
            data = _get(WIKI_API, {"action": "query", "prop": "extracts", "explaintext": 1,
                                   "redirects": 1, "format": "json", "formatversion": 2,
                                   "titles": "|".join(lote)}, timeout=30)
        except Exception:
            continue
        for p in data.get("query", {}).get("pages", []):
            titulo = p.get("title", "")
            texto = (p.get("extract") or "").strip()
            if titulo and len(texto) >= 200:
                resultados.append({"t": titulo, "x": texto[:_EXTRACTO_MAX]})
        time.sleep(0.3)  # cortesia con los servidores de Wikimedia
    return resultados


def _actualizar_meta(extra: int = 0, fuente: str = ""):
    meta = {}
    if META.exists():
        try:
            meta = json.loads(META.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    meta["articulos"] = meta.get("articulos", 0) + extra
    meta["actualizado"] = datetime.now().isoformat(timespec="seconds")
    if fuente:
        meta["fuente"] = fuente
    if ART.exists():
        meta["tamano"] = ART.stat().st_size
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _accion_estado() -> str:
    if not ART.exists():
        return ("📭 Mini-wikipedia NO descargada. Con internet, pide: "
                '"descarga la mini enciclopedia offline" (accion=descargar, '
                "~500 articulos mas vistos).")
    total = 0
    try:
        with gzip.open(ART, "rt", encoding="utf-8") as f:
            for _ in f:
                total += 1
    except Exception as e:
        return f"⚠️ El archivo de articulos esta da\u00f1ado ({e}). Vuelve a descargar (accion=descargar)."
    meta = {}
    try:
        meta = json.loads(META.read_text(encoding="utf-8"))
    except Exception:
        pass
    tam = ART.stat().st_size
    fuente = meta.get("fuente", "es.wikipedia")
    fecha = str(meta.get("actualizado", "?"))[:10]
    return (f"📚 Mini-wikipedia offline: {total} articulos, {_peso_humano(tam)}. "
            f"Fuente: {fuente}. Actualizada: {fecha}. Busquedas 100% sin internet.")


def _accion_descargar(n) -> str:
    try:
        n = max(100, min(int(n or 500), 2000))
    except Exception:
        n = 500
    titulos = _extraer_titulos_top(n)
    if not titulos:
        return "⚠️ No se pudo obtener la lista de articulos mas vistos (sin internet o bloqueo). Intenta de nuevo."
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ART.with_suffix(".tmp")
    escritos = 0
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for art in _extraer_textos(titulos):
            f.write(json.dumps(art, ensure_ascii=False) + "\n")
            escritos += 1
    tmp.replace(ART)
    try:
        META.unlink()
    except Exception:
        pass
    _actualizar_meta(extra=escritos, fuente=f"es.wikipedia mostviewed (top {len(titulos)})")
    return (f"✅ Mini-wikipedia descargada: {escritos} articulos ({_peso_humano(ART.stat().st_size)}) en {ART}. "
            "Desde ahora puedes preguntar enciclopedia 100% offline (accion=buscar).")


def _accion_agregar(tema: str, n) -> str:
    tema = (tema or "").strip()
    if not tema:
        return "⚠️ Para agregar articulos indica el tema (ej: tema=astronomia)."
    try:
        n = max(1, min(int(n or 10), 50))
    except Exception:
        n = 10
    titulos = _extraer_titulos_busqueda(tema, n)
    if not titulos:
        return f"⚠️ Sin resultados en Wikipedia para: {tema}"
    # Evitar duplicados: saltar titulos ya presentes
    presentes = set()
    if ART.exists():
        try:
            with gzip.open(ART, "rt", encoding="utf-8") as f:
                for linea in f:
                    try:
                        presentes.add(json.loads(linea).get("t", ""))
                    except Exception:
                        pass
        except Exception:
            pass
    nuevos = [t for t in titulos if t not in presentes]
    if not nuevos:
        return f"ℹ️ Los articulos sobre '{tema}' ya estan en la mini-wiki."
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    escritos = 0
    with gzip.open(ART, "at", encoding="utf-8") as f:
        for art in _extraer_textos(nuevos):
            f.write(json.dumps(art, ensure_ascii=False) + "\n")
            escritos += 1
    _actualizar_meta(extra=escritos)
    return f"✅ Agregados {escritos} articulos sobre '{tema}' a la mini-wiki offline."


def _iterar_articulos():
    with gzip.open(ART, "rt", encoding="utf-8") as f:
        for linea in f:
            try:
                d = json.loads(linea)
                if d.get("t") and d.get("x"):
                    yield d["t"], d["x"]
            except Exception:
                continue


def _accion_buscar(consulta: str, max_resultados) -> str:
    consulta = (consulta or "").strip()
    if not consulta:
        return "⚠️ Indica que buscar (consulta)."
    if not ART.exists():
        return ("📭 La mini-wikipedia no esta descargada. Con internet, pide: "
                '"descarga la mini enciclopedia offline" (accion=descargar). '
                "Despues podras buscar sin internet.")
    try:
        max_resultados = max(1, min(int(max_resultados or _BUSCAR_MAX), 5))
    except Exception:
        max_resultados = _BUSCAR_MAX
    qtokens = set(_tokens(consulta))
    if not qtokens:
        return "⚠️ Consulta demasiado generica: usa palabras clave (ej: 'civilizacion maya')."
    mejores = []  # (score, titulo, extracto)
    escaneados = 0
    for titulo, texto in _iterar_articulos():
        escaneados += 1
        tset = set(_tokens(titulo))
        score = 3.0 * len(qtokens & tset)
        cuerpo = _norm(texto[:15000])
        for t in qtokens:
            score += min(cuerpo.count(t), 20) * 0.1
        if score > 0:
            mejores.append((score, titulo, texto[:_FRAGMENTO]))
    if not mejores:
        return (f"🔎 Sin resultados offline para '{consulta}' ({escaneados} articulos en la mini-wiki). "
                "Puedes ampliarla con accion=agregar y tema, o usar web_search si hay internet.")
    mejores.sort(key=lambda m: m[0], reverse=True)
    partes = [f"🔎 Resultados offline para '{consulta}' ({escaneados} articulos en la mini-wiki):"]
    for i, (_, titulo, frag) in enumerate(mejores[:max_resultados], 1):
        partes.append(f"\n{i}. **{titulo}**\n{frag.strip()}")
    if len(mejores) > max_resultados:
        extra = ", ".join(t for _, t, _ in mejores[max_resultados:max_resultados + 3])
        partes.append(f"\n(Tambien coinciden: {extra})")
    return "\n".join(partes)


def _accion_leer(titulo: str) -> str:
    titulo = (titulo or "").strip()
    if not titulo:
        return "⚠️ Indica el titulo del articulo (titulo). Usa antes accion=buscar para encontrarlo."
    if not ART.exists():
        return "📭 La mini-wikipedia no esta descargada (accion=descargar, con internet)."
    objetivo = _norm(titulo)
    for t, texto in _iterar_articulos():
        if _norm(t) == objetivo:
            cola = "\n[… articulo recortado]" if len(texto) > _LEER_MAX else ""
            return f"📖 **{t}**\n\n{texto[:_LEER_MAX]}" + cola
    return f"⚠️ No hay un articulo con titulo exacto '{titulo}' en la mini-wiki. Usa accion=buscar."


def _accion_wikidata(consulta: str) -> str:
    consulta = (consulta or "").strip()
    if not consulta:
        return "⚠️ Indica la entidad a consultar (consulta), ej: consulta=Albert Einstein."
    try:
        data = _get(WD_API, {"action": "wbsearchentities", "search": consulta, "language": "es",
                             "limit": 5, "format": "json"}, timeout=15)
    except Exception as e:
        return f"⚠️ Wikidata no accesible (sin internet?): {e}"
    entes = data.get("search", [])
    if not entes:
        return f"🔎 Wikidata sin resultados para '{consulta}'."
    lineas = [f"🌐 Wikidata - resultados para '{consulta}':"]
    for e in entes:
        qid = e.get("id", "?")
        etiqueta = e.get("label", "?")
        desc = e.get("description", "sin descripcion")
        lineas.append(f"  - {qid} | {etiqueta}: {desc}")
    return "\n".join(lineas)


def execute(accion: str = "buscar", consulta: str = "", titulo: str = "",
            n=None, max_resultados=_BUSCAR_MAX, **kwargs) -> str:
    try:
        # Tolerancia a argumentos mal nombrados por el modelo
        accion = str(accion or kwargs.get("action", "") or "buscar").strip().lower()
        consulta = str(consulta or kwargs.get("query", "") or kwargs.get("busqueda", "") or kwargs.get("tema", "") or "")
        titulo = str(titulo or kwargs.get("articulo", "") or "")
        if accion == "estado":
            return _accion_estado()
        if accion == "descargar":
            return _accion_descargar(n)
        if accion == "agregar":
            return _accion_agregar(consulta, n)
        if accion == "leer":
            return _accion_leer(titulo or consulta)
        if accion == "wikidata":
            return _accion_wikidata(consulta)
        if accion == "buscar":
            return _accion_buscar(consulta, max_resultados)
        return ("⚠️ Accion desconocida: " + accion + ". Usa: estado, descargar, agregar, buscar, leer, wikidata.")
    except Exception as e:
        return f"Error en wiki_offline: {e}"


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if args and args[0] == "descargar":
        print(execute(accion="descargar", n=int(args[1]) if len(args) > 1 else 500))
    elif args:
        print(execute(accion=args[0], consulta=" ".join(args[1:])))
    else:
        print(execute(accion="estado"))
