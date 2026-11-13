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
- buscar:      busqueda LOCAL sin internet sobre lo descargado (palabras clave;
               si no encuentra nada, cae automaticamente a busqueda semantica).
- buscar_semantico: busqueda SEMANTICA local con embeddings (bge-m3 via
               Ollama): entiende el SENTIDO de la consulta, no solo palabras
               exactas. Requiere generar el indice una vez (accion=indexar).
- indexar:     genera/actualiza el indice de embeddings de la mini-wiki
               (local, una vez por descarga; quedan en embeddings.jsonl.gz).
- leer:        texto completo (capado) de un articulo por titulo exacto.
- wikidata:    busca una entidad en Wikidata (red): QID, etiqueta y descripcion.

Sin dependencias nuevas: requests + el paquete ollama (ya usado por el
pre-router de la app). Las peticiones web salen por la sesion compartida
de Chispa (tools/http_session.py): cabeceras de Chrome + cookies del
usuario, para minimizar rechazos anti-bot y 429 de Wikimedia.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from tools.http_session import http_get  # sesion compartida: cabeceras de Chrome + cookies del usuario

DATA_DIR = Path(os.environ.get("WIKI_MINI_DIR", str(Path.home() / ".local/share/Chispa/wiki_mini")))
ART = DATA_DIR / "articulos.jsonl.gz"
META = DATA_DIR / "meta.json"
IDX = DATA_DIR / "embeddings.jsonl.gz"   # indice semantico (titulo + vector)

WIKI_API = "https://es.wikipedia.org/w/api.php"
WD_API = "https://www.wikidata.org/w/api.php"

# Prefijos de espacio de nombres que NO son articulos enciclopedicos
_EXCLUIR = ("Wikipedia:", "Ayuda:", "Categoria:", "Categor\u00eda:", "Portal:", "Archivo:",
            "Plantilla:", "Modulo:", "M\u00f3dulo:", "Especial:", "Discusi\u00f3n:", "Wikiproyecto:")
_EXACTOS = {"Portada", "Main Page", "Wikiportada"}

_EXTRACTO_MAX = 8000     # por articulo al descargar
_BUSCAR_MAX = 3          # articulos devueltos por defecto
_FRAGMENTO = 1100        # caracteres por articulo en buscar
_LEER_MAX = 3000         # techo de leer (bajo TOOL_RESULT_MAX=3500 del worker)
_EMBED_MODEL = "bge-m3"  # embeddings multilingues (1024 dim); requiere: ollama pull bge-m3
_EMBED_CHUNK = 800       # caracteres de cada articulo que se indexan
_EMBED_LOTE = 16         # articulos por llamada de embedding
_SIMILAR_MIN = 0.35      # similitud coseno minima para considerar resultado

_STOPWORDS = {"de", "la", "el", "los", "las", "un", "una", "unos", "unas", "que", "y", "o",
              "en", "del", "al", "por", "para", "con", "es", "son", "fue", "como", "mas",
              "sobre", "quien", "cual", "cuando", "donde", "the", "of", "su", "sus"}

# Diagnostico del ultimo error de red (para mensajes utiles al usuario)
_LAST_DIAG = ""

# Lista semilla de temas esenciales: fallback si las APIs de listas fallan
_SEMILLAS = [
    "España",
    "México",
    "Ciudad de México",
    "Guadalajara",
    "Monterrey",
    "Historia de México",
    "Revolución mexicana",
    "Independencia de México",
    "Civilización maya",
    "Imperio romano",
    "Antiguo Egipto",
    "Grecia antigua",
    "Segunda Guerra Mundial",
    "Primera Guerra Mundial",
    "Guerra Fría",
    "Revolución francesa",
    "Edad Media",
    "Renacimiento",
    "Albert Einstein",
    "Isaac Newton",
    "Charles Darwin",
    "Marie Curie",
    "Nikola Tesla",
    "Galileo Galilei",
    "Leonardo da Vinci",
    "Miguel de Cervantes",
    "William Shakespeare",
    "Gabriel García Márquez",
    "Octavio Paz",
    "Frida Kahlo",
    "Diego Rivera",
    "Sor Juana Inés de la Cruz",
    "Benito Juárez",
    "Porfirio Díaz",
    "Hernán Cortés",
    "Moctezuma II",
    "Física",
    "Química",
    "Biología",
    "Matemática",
    "Astronomía",
    "Filosofía",
    "Psicología",
    "Economía",
    "Sociología",
    "Historia",
    "Geografía",
    "Literatura",
    "Música",
    "Arte",
    "Cine",
    "Fotografía",
    "Internet",
    "Computadora",
    "Inteligencia artificial",
    "Software",
    "Linux",
    "Python",
    "Energía solar",
    "Energía nuclear",
    "Cambio climático",
    "Agua",
    "Atmósfera",
    "Sistema solar",
    "Sol",
    "Tierra",
    "Luna",
    "Marte",
    "Júpiter",
    "Vía Láctea",
    "Universo",
    "Big Bang",
    "Evolución biológica",
    "ADN",
    "Célula",
    "Fotosíntesis",
    "Cerebro",
    "Corazón",
    "Medicina",
    "Vacuna",
    "Antibiótico",
    "Cáncer",
    "Diabetes mellitus",
    "Nutrición",
    "Fútbol",
    "Baloncesto",
    "Béisbol",
    "Juegos Olímpicos",
    "Copa Mundial de Fútbol",
    "Ajedrez",
    "Boxeo",
    "Religión",
    "Cristianismo",
    "Islam",
    "Budismo",
    "Mitología griega",
    "Idioma español",
    "Náhuatl",
    "Lenguas mayenses",
    "América",
    "Europa",
    "Asia",
    "África",
    "Océano Pacífico",
    "Golfo de México",
    "Sierra Madre Occidental",
    "Volcán",
    "Terremoto",
    "Huracán",
    "Biodiversidad",
    "Genética",
    "Teoría de la relatividad",
    "Mecánica cuántica",
    "Tabla periódica de los elementos",
    "Matemáticas",
    "Estadística",
    "Demografía de México",
    "Economía de México",
    "Gastronomía de México",
    "Música regional mexicana",
    "Día de Muertos",
]


TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "wiki_offline",
        "description": "Mini enciclopedia OFFLINE de Wikipedia en espanol + Wikidata online. OBLIGATORIA para preguntas enciclopedicas/biograficas (quien fue X, que es Y): accion=buscar y responde SOLO con lo devuelto; si no esta, admitelo y ofrece accion=agregar o web_search. 'Descarga la mini enciclopedia offline' = accion=descargar SIN pedir permiso. Enumerar titulos = accion=listar (NUNCA inventes). Acciones: estado, descargar, agregar, buscar (local; cae a semantica), buscar_semantico, indexar (bge-m3), leer, listar, wikidata.",
            "parameters": {
            "type": "object",
            "properties": {
                "accion": {"type": "string", "enum": ["estado", "descargar", "agregar", "buscar", "buscar_semantico", "indexar", "leer", "listar", "wikidata"],
                            "description": "Que hacer. Defecto: buscar"},
                "consulta": {"type": "string", "description": "Texto a buscar (accion=buscar, buscar_semantico o wikidata) o tema (accion=agregar)"},
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
    r = http_get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _extraer_titulos_top(n: int) -> list:
    """Articulos mas vistos de es.wikipedia, con 3 fuentes en cascada:
    1) API list=mostviewed; 2) REST pageviews top (ultimos 5 dias);
    3) lista semilla local de temas esenciales. Guarda diagnostico en _LAST_DIAG."""
    global _LAST_DIAG
    titulos = []
    seen = set()

    def _agregar(titulo):
        titulo = (titulo or "").replace("_", " ").strip()
        if titulo and titulo not in seen and _es_articulo_valido(titulo):
            seen.add(titulo)
            titulos.append(titulo)

    # Fuente 1: list=mostviewed (hasta 500 por llamada)
    try:
        data = _get(WIKI_API, {"action": "query", "list": "mostviewed", "pvimlimit": 500,
                               "format": "json", "formatversion": "2"}, timeout=30)
        for item in data.get("query", {}).get("mostviewed", []):
            _agregar(item.get("title", ""))
            if len(titulos) >= n:
                return titulos
        _LAST_DIAG = "mostviewed devolvio 0 articulos"
    except Exception as e:
        _LAST_DIAG = f"mostviewed: {e}"

    # Fuente 2: REST pageviews top de los ultimos 5 dias completos
    hoy = datetime.utcnow().date()
    for delta in range(1, 6):
        d = hoy - timedelta(days=delta)
        try:
            url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
                   f"es.wikipedia/all-access/{d.year}/{d.month:02d}/{d.day:02d}")
            r = http_get(url, timeout=20)
            r.raise_for_status()
            items = r.json().get("items", [])
            for art in (items[0].get("articles", []) if items else []):
                _agregar(art.get("article", ""))
                if len(titulos) >= n:
                    return titulos
        except Exception as e:
            _LAST_DIAG = f"pageviews {d}: {e}"
            continue

    # Fuente 3: lista semilla local (siempre disponible)
    for titulo in _SEMILLAS:
        _agregar(titulo)
        if len(titulos) >= n:
            break
    return titulos


def _extraer_titulos_busqueda(tema: str, n: int) -> list:
    data = _get(WIKI_API, {"action": "query", "list": "search", "srsearch": tema,
                           "srlimit": max(1, min(n, 50)), "format": "json", "formatversion": "2"}, timeout=30)
    return [r.get("title", "") for r in data.get("query", {}).get("search", []) if r.get("title")]


def _get_con_reintentos(params: dict, etiqueta: str, intentos: int = 3):
    """GET a la API de Wikipedia con backoff: ante 429 (Too Many Requests)
    espera y reintenta; ante otro error reintenta con pausa corta.
    Devuelve el dict o None si agotó los intentos."""
    global _LAST_DIAG
    for intento in range(intentos):
        try:
            return _get(WIKI_API, params, timeout=30)
        except Exception as e:
            _LAST_DIAG = f"{etiqueta} (intento {intento + 1}): {e}"
            msg = str(e)
            espera = 8 * (intento + 1) if ("429" in msg or "Too Many" in msg) else 1.5
            time.sleep(espera)
    return None


def _extraer_textos(titulos: list) -> list:
    """Extractos en texto plano. Dos pasadas con ritmo respetuoso:
    1) Lotes de 20 con exlimit=max + exintro (rapido, intro de cada articulo).
    2) Texto COMPLETO individual (exlimit=1) para los primeros 50 titulos.
    Ante 429 (Too Many Requests) espera y reintenta (backoff). Los fallos
    quedan en _LAST_DIAG y la descarga es acumulativa: repetirla completa
    lo que falto.
    NOTA: el exlimit por defecto es 1 — sin 'exlimit=max' cada lote de 20
    devolvia UN solo extracto (causa del bug de '13 articulos')."""
    global _LAST_DIAG
    resultados = {}
    orden = []

    def _guardar(titulo, texto):
        texto = (texto or "").strip()
        if titulo and len(texto) >= 200:
            if titulo not in resultados:
                orden.append(titulo)
            if len(texto) >= len(resultados.get(titulo, "")):
                resultados[titulo] = texto[:_EXTRACTO_MAX]

    # Pasada 1: intros por lotes de 20
    for i in range(0, len(titulos), 20):
        lote = titulos[i:i + 20]
        data = _get_con_reintentos(
            {"action": "query", "prop": "extracts", "explaintext": 1,
             "exintro": 1, "exlimit": "max", "redirects": 1,
             "format": "json", "formatversion": 2, "titles": "|".join(lote)},
            f"extracts lote {i // 20}")
        if data is not None:
            for p in data.get("query", {}).get("pages", []):
                _guardar(p.get("title", ""), p.get("extract") or "")
        time.sleep(1.0)  # ritmo respetuoso: evita 429 de Wikimedia

    # Pasada 2: texto completo individual para los 50 primeros
    for titulo in titulos[:50]:
        if titulo in resultados and len(resultados[titulo]) >= 4000:
            continue  # el intro ya es rico; no gastamos peticion
        data = _get_con_reintentos(
            {"action": "query", "prop": "extracts", "explaintext": 1,
             "exlimit": 1, "redirects": 1, "titles": titulo,
             "format": "json", "formatversion": 2},
            f"extracts completo '{titulo}'")
        if data is not None:
            for p in data.get("query", {}).get("pages", []):
                _guardar(p.get("title", "") or titulo, p.get("extract") or "")
        time.sleep(0.8)

    return [{"t": titulo, "x": resultados[titulo]} for titulo in orden]


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
        return ("⚠️ No se pudo obtener la lista de articulos. Diagnostico: "
                + (_LAST_DIAG or "desconocido") + ". Revisa tu conexion e intenta de nuevo.")
    # Acumulativa: NO borra lo ya descargado, solo anade lo que falta
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
    previos = len(presentes)
    nuevos = [x for x in titulos if x not in presentes]
    if not nuevos:
        return (f"ℹ️ La mini-wiki ya tiene los {previos} articulos mas vistos. "
                "Usa accion=agregar para ampliarla por tema.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    escritos = 0
    with gzip.open(ART, "at", encoding="utf-8") as f:
        for art in _extraer_textos(nuevos):
            f.write(json.dumps(art, ensure_ascii=False) + "\n")
            escritos += 1
    _actualizar_meta(extra=escritos, fuente=f"es.wikipedia top {len(titulos)}")
    faltantes = len(nuevos) - escritos
    aviso = ""
    if faltantes:
        aviso = (f" ⚠️ {faltantes} articulos no se pudieron bajar (diagnostico: {_LAST_DIAG or 'desconocido'}); "
                 "repite 'descarga la mini enciclopedia offline' para completarlos: NO duplica.")
    return (f"✅ Mini-wiki: {escritos} articulos nuevos + {previos} previos = "
            f"{previos + escritos} en total ({_peso_humano(ART.stat().st_size)}).{aviso}")


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
        # Fallback automatico: la busqueda por palabras clave no encontro nada;
        # probamos busqueda semantica (entiende sinonimos y sentido)
        sem = _buscar_semantico_interna(consulta, max_resultados)
        if sem:
            return (f"🔎 Sin coincidencias exactas para '{consulta}'; resultados SEMANTICOS "
                    f"({escaneados} articulos en la mini-wiki):\n" + sem)
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



# ---------------------------------------------------------------------------
# Busqueda semantica local (embeddings via Ollama, bge-m3)
# ---------------------------------------------------------------------------

def _ollama() -> object:
    """Cliente de Ollama local (mismo patron que tools/pre_router.py).
    Devuelve None si el paquete o el servidor no estan disponibles."""
    try:
        import ollama
        return ollama.Client()
    except Exception:
        return None


def _embed_lote(cliente, textos: list):
    """Embeddings de una lista de textos; None si Ollama no esta disponible."""
    if cliente is None:
        return None
    try:
        resp = cliente.embed(model=_EMBED_MODEL, inputs=textos)
        embs = resp.get("embeddings") or []
        if len(embs) == len(textos):
            return embs
    except Exception:
        pass
    try:
        embs = []
        for t in textos:
            r = cliente.embeddings(model=_EMBED_MODEL, prompt=t)
            embs.append(r.get("embedding") or [])
        return embs if len(embs) == len(textos) else None
    except Exception:
        return None


def _coseno(a, b) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _index_contiene(n_titulos: int) -> bool:
    """El indice existe y cubre los articulos actuales CON EL MODELO ACTUAL?
    Los vectores de otro modelo (p.ej. indice viejo de nomic-embed-text) no
    cuentan: compararlos con consultas de otro modelo seria basura."""
    if not IDX.exists():
        return False
    total = 0
    try:
        with gzip.open(IDX, "rt", encoding="utf-8") as f:
            for linea in f:
                try:
                    d = json.loads(linea)
                    if d.get("v") and d.get("m", "nomic-embed-text") == _EMBED_MODEL:
                        total += 1
                except Exception:
                    continue
    except Exception:
        return False
    return total >= n_titulos


def _accion_indexar() -> str:
    """Genera/actualiza el indice semantico: titulo + primeros _EMBED_CHUNK
    caracteres de cada articulo, con bge-m3 via Ollama LOCAL.
    Idempotente: si el indice ya cubre todo, no rehace nada."""
    if not ART.exists():
        return "📭 La mini-wikipedia no esta descargada (accion=descargar, con internet)."
    cliente = _ollama()
    if cliente is None:
        return ("⚠️ La busqueda semantica necesita Ollama con el modelo " + _EMBED_MODEL +
                " (ya lo usa el pre-router de Chispa). Verifica que Ollama este corriendo.")
    articulos = list(_iterar_articulos())
    if not articulos:
        return "⚠️ La mini-wiki no tiene articulos legibles; vuelve a descargar (accion=descargar)."
    if _index_contiene(len(articulos)):
        return (f"ℹ️ El indice semantico ya cubre los {len(articulos)} articulos. "
                "No hace falta reindexar (se regenera solo si descargas/agregas articulos).")
    previos = {}
    if IDX.exists():
        try:
            with gzip.open(IDX, "rt", encoding="utf-8") as f:
                for linea in f:
                    try:
                        d = json.loads(linea)
                        # Solo se reutilizan vectores del MISMO modelo de embeddings
                        if d.get("t") and d.get("v") and d.get("m") == _EMBED_MODEL:
                            previos[d["t"]] = d["v"]
                    except Exception:
                        continue
        except Exception:
            previos = {}
    pendientes = [(t, x) for t, x in articulos if t not in previos]
    escritos = 0
    tmp = IDX.with_suffix(".tmp")
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            for t, v in previos.items():
                f.write(json.dumps({"t": t, "v": v, "m": _EMBED_MODEL}, ensure_ascii=False) + "\n")
                escritos += 1
            for i in range(0, len(pendientes), _EMBED_LOTE):
                lote = pendientes[i:i + _EMBED_LOTE]
                textos = [(t + ". " + x[:_EMBED_CHUNK]) for t, x in lote]
                embs = _embed_lote(cliente, textos)
                if embs is None:
                    return ("⚠️ Ollama no respondio al generar embeddings. ¿Esta corriendo "
                            "con el modelo " + _EMBED_MODEL + "? (ollama pull " + _EMBED_MODEL + ")")
                for (t, _), v in zip(lote, embs):
                    if v:
                        f.write(json.dumps({"t": t, "v": v, "m": _EMBED_MODEL}, ensure_ascii=False) + "\n")
                        escritos += 1
        tmp.replace(IDX)  # escritura atomica
    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return f"⚠️ Error generando el indice semantico: {e}"
    _actualizar_meta()
    try:
        meta = json.loads(META.read_text(encoding="utf-8"))
        meta["indice_semantico"] = escritos
        meta["actualizado"] = datetime.now().isoformat(timespec="seconds")
        META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return (f"🧠 Indice semantico listo: {escritos} articulos vectorizados con "
            f"{_EMBED_MODEL} (100% local). Ya puedes usar accion=buscar_semantico.")


def _buscar_semantico_interna(consulta: str, max_resultados: int):
    """Devuelve el texto de resultados semanticos o None si no hay indice/Ollama
    o ninguna similitud supera _SIMILAR_MIN."""
    if not ART.exists() or not IDX.exists():
        return None
    cliente = _ollama()
    if cliente is None:
        return None
    qemb = _embed_lote(cliente, [consulta])
    if not qemb or not qemb[0]:
        return None
    qv = qemb[0]
    vectores = {}
    try:
        with gzip.open(IDX, "rt", encoding="utf-8") as f:
            for linea in f:
                try:
                    d = json.loads(linea)
                    if d.get("t") and d.get("v") and d.get("m", _EMBED_MODEL) == _EMBED_MODEL:
                        vectores[d["t"]] = d["v"]
                except Exception:
                    continue
    except Exception:
        return None
    if not vectores:
        return None
    mejores = []  # (sim, titulo, extracto)
    for titulo, texto in _iterar_articulos():
        v = vectores.get(titulo)
        if not v:
            continue
        sim = _coseno(qv, v)
        if sim >= _SIMILAR_MIN:
            mejores.append((sim, titulo, texto[:_FRAGMENTO]))
    if not mejores:
        return None
    mejores.sort(key=lambda m: m[0], reverse=True)
    partes = []
    for i, (sim, titulo, frag) in enumerate(mejores[:max_resultados], 1):
        partes.append(f"\n{i}. **{titulo}** (relevancia {sim:.2f})\n{frag.strip()}")
    return "\n".join(partes)


def _accion_buscar_semantico(consulta: str, max_resultados) -> str:
    consulta = (consulta or "").strip()
    if not consulta:
        return "⚠️ Indica que buscar (consulta), ej: consulta='santo que compartio su capa con un pobre'."
    if not ART.exists():
        return ("📭 La mini-wikipedia no esta descargada. Con internet, pide: "
                '"descarga la mini enciclopedia offline" (accion=descargar).')
    try:
        max_resultados = max(1, min(int(max_resultados or _BUSCAR_MAX), 5))
    except Exception:
        max_resultados = _BUSCAR_MAX
    total = sum(1 for _ in _iterar_articulos())
    if not IDX.exists():
        return ("🧠 La busqueda semantica necesita un indice de embeddings que aun no existe. "
                "Ejecuta primero accion=indexar (una vez, local, tarda unos minutos).")
    if not _index_contiene(total):
        return ("🧠 El indice semantico esta desactualizado (articulos nuevos sin vectorizar). "
                "Ejecuta accion=indexar para completarlo.")
    res = _buscar_semantico_interna(consulta, max_resultados)
    if res is None:
        return ("⚠️ La busqueda semantica no esta disponible ahora (¿Ollama apagado?) o ninguna "
                "similitud supero el umbral. Prueba accion=buscar con palabras clave.")
    return f"🧠 Resultados semanticos para '{consulta}':{res}"


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


def _accion_listar(filtro: str = "", max_titulos=40) -> str:
    """Titulos REALES de la mini-wiki: para que el modelo enumere contenidos
    sin inventar. Filtro opcional por substring (sin acentos)."""
    if not ART.exists():
        return "📭 La mini-wikipedia no esta descargada (accion=descargar, con internet)."
    filtro_n = _norm(filtro or "")
    coinciden = []
    total = 0
    for titulo, _ in _iterar_articulos():
        total += 1
        if not filtro_n or filtro_n in _norm(titulo):
            coinciden.append(titulo)
    try:
        max_titulos = max(1, min(int(max_titulos or 40), 100))
    except Exception:
        max_titulos = 40
    muestra = coinciden[:max_titulos]
    lineas = [f"📚 Mini-wiki: {total} articulos en total."]
    if filtro_n:
        lineas.append(f"Filtro '{filtro}': {len(coinciden)} coincidencia(s).")
    lineas.append("Titulos reales (NO inventes otros ni resumas articulos que no hayas leido):")
    lineas += [f"  - {x}" for x in muestra]
    if len(coinciden) > len(muestra):
        lineas.append(f"  … y {len(coinciden) - len(muestra)} mas (pide accion=listar con filtro para acotar).")
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
        if accion == "listar":
            return _accion_listar(str(kwargs.get("filtro", "") or ""), kwargs.get("max_titulos"))
        if accion in ("buscar_semantico", "semantico", "embedding"):
            return _accion_buscar_semantico(consulta, max_resultados)
        if accion == "indexar":
            return _accion_indexar()
        if accion == "buscar":
            return _accion_buscar(consulta, max_resultados)
        return ("⚠️ Accion desconocida: " + accion + ". Usa: estado, descargar, agregar, buscar, "
                "buscar_semantico, indexar, leer, listar, wikidata.")
    except Exception as e:
        return f"Error en wiki_offline: {e}"


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if args and args[0] == "descargar":
        print(execute(accion="descargar", n=int(args[1]) if len(args) > 1 else 500))
    elif args and args[0] == "indexar":
        print(execute(accion="indexar"))
    elif args:
        print(execute(accion=args[0], consulta=" ".join(args[1:])))
    else:
        print(execute(accion="estado"))
