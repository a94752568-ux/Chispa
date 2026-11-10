"""
Pre-router por embeddings (Rama B - Fase 1).

Clasifica el mensaje del usuario en una de 4 categorías operativas y devuelve
solo los schemas de herramientas relevantes + herramientas básicas.

Reduce el contexto de ~3,200 tokens fijos a ~600-800 tokens por request.
"""

from __future__ import annotations

import math
import re
from typing import Dict, List, Optional

from tools import load_tools

EMBED_MODEL = "nomic-embed-text"

ANCHORS: Dict[str, str] = {
    "datos": "¿buscar en datos? Búsqueda en RAG, notas, archivos y web.",
    "sistema": "¿información de sistema? Git, contenedores, tiempo, monitor, calendario.",
    "osint": "¿datos externos? OSINT, correo, usuario, subdominios, cabeceras, fingerprint, reconocimiento.",
    "analisis": "¿análisis de contenido? OCR, sentimiento, EXIF, metadatos.",
}

BASIC_TOOL_NAMES = {"web_search", "get_current_time", "calculator"}

# Boost determinista por keywords: suma puntuación a la categoría coincidente
# (no reemplaza, así que multi-intención no se rompe)
_BOOSTS = [
    (re.compile(r"https?://|\b\d{1,3}(?:\.\d{1,3}){3}\b|\b[a-z0-9-]+\.[a-z]{2,}(?:\.[a-z]{2,})?\b|\b(?:dominio|subdominio\w*|whois|brecha|alias)\b", re.I), "osint"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b", re.I), "osint"),                 # correo electrónico
    (re.compile(r"\b(?:tecnolog\w*|fingerprint|huella|detectar tecnologia)\b", re.I), "osint"),
    (re.compile(r"\b(?:mi repo|git|commit\w*|rama|cpu|ram|disco|nvme|waydroid|contenedor)\b", re.I), "sistema"),
    (re.compile(r"\b(?:recuerda|anot[eé]|mis notas|mi manual|mis documentos|mi pdf|agenda)\b", re.I), "datos"),
    (re.compile(r"\b(?:organiza\w*|ordena\w*|clasifica\w*|mueve\w*|renombra\w*|borra\w*|elimina\w*|papelera)\b", re.I), "sistema"),
    (re.compile(r"\b(?:lista\w*|qu[eé]\s+hay\s+en|contenido\s+de\s+(?:la\s+)?carpeta|mu[eé]strame\s+(?:los|las)\s+(?:archivos|carpetas))\b", re.I), "datos"),
    (re.compile(r"\b(?:foto|imagen|metadato|exif|escanead|ocr|sentimiento|donde tome)\b", re.I), "analisis"),
]

_MARGIN_THRESHOLD = 0.05

# Umbral mínimo de similitud: por debajo, no se envían herramientas de dominio
_CONFIDENCE_THRESHOLD = 0.25

# Gate de saludos y meta-preguntas cortas: no arrastran tools de dominio
_SALUDO = re.compile(
    r"^\s*(hola|hey|buen[oa]s?\s*(d[ií]as|tardes|noches)|qu[eé]\s*tal|"
    r"hi|hello|gracias|por\s*favor|ok|vale|dale)\s*[!.,?]?\s*$",
    re.I,
)

# Meta-preguntas sobre la app misma: si el usuario pregunta por las
# herramientas/capacidades o quién es, el router envía TODAS las tools
# para que el modelo enumere capacidades reales en vez de inventarlas.
_META = re.compile(
    r"\b(?:herramientas|tools|plugins|capacidades)\b|"
    r"qu[eé]\s+(?:puedes|sabes)\s+hacer|qui[eé]n\s+eres",
    re.I,
)

# Overrides deterministas por nombre de tool: corrigen clasificaciones de
# schemas que el cosíneo con anclas resuelve mal, sin depender del embedding.
_CATEGORY_OVERRIDES: Dict[str, str] = {
    # OSINT (fuerzo, aunque el schema se acerque a otras categorías)
    "check_exposure": "osint",
    "hunt_alias": "osint",
    "fingerprint_url": "osint",
    "list_subdomains": "osint",
    "full_recon": "osint",
    "recon_target": "osint",
    "analyze_security": "osint",
    # Sistema
    "system_monitor": "sistema",
    "system_info": "sistema",
    "get_current_time": "sistema",
    "get_weather": "sistema",
    "calendar_tool": "sistema",
    "containers_status": "sistema",
    "git_status": "sistema",
    # Datos / conocimiento
    "rag_search": "datos",
    "notes_tool": "datos",
    "read_file": "datos",
    # Análisis de contenido
    "ocr_tool": "analisis",
    "sentiment_tool": "analisis",
    "metadata_tool": "analisis",
    "organize_files": "sistema",
    "move_file": "sistema",
    "delete_file": "sistema",
    "find_files": "datos",
    "list_dir": "datos",
}


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class ToolRouter:
    """Clasifica mensajes y filtra tools por categoría usando embeddings."""

    def __init__(self, embed_model: str = EMBED_MODEL):
        self.embed_model = embed_model
        self.definitions: List[dict] = []
        self.executors: Dict = {}
        self.tool_category: Dict[str, str] = {}
        self.anchor_embeddings: Dict[str, List[float]] = {}
        self._client = None
        self._ready = False

        self.definitions, self.executors = load_tools()
        self._init_client()
        if self._client is not None:
            self._build_index()

    def _init_client(self):
        try:
            import ollama
            self._client = ollama.Client()
        except Exception:
            self._client = None

    def _embed(self, texts: List[str]) -> List[List[float]]:
        if self._client is None:
            return [[0.0] * 768 for _ in texts]
        try:
            resp = self._client.embed(model=self.embed_model, inputs=texts)
            embs = resp.get("embeddings", [])
            if embs:
                return embs
        except Exception:
            pass
        try:
            embs = []
            for t in texts:
                r = self._client.embeddings(model=self.embed_model, prompt=t)
                embs.append(r.get("embedding", []))
            return embs
        except Exception:
            return [[0.0] * 768 for _ in texts]

    def _build_index(self):
        names = list(ANCHORS.keys())
        texts = [ANCHORS[n] for n in names]
        embs = self._embed(texts)
        self.anchor_embeddings = dict(zip(names, embs))

        schema_texts = []
        for d in self.definitions:
            fn = d.get("function", {})
            schema_texts.append(fn.get("name", "") + " " + fn.get("description", ""))

        schema_embs = self._embed(schema_texts)

        for i, d in enumerate(self.definitions):
            name = d.get("function", {}).get("name", f"tool_{i}")
            best_cat, best_score = None, -1.0
            for cat, a_emb in self.anchor_embeddings.items():
                score = _cosine(schema_embs[i], a_emb)
                if score > best_score:
                    best_score = score
                    best_cat = cat
            self.tool_category[name] = best_cat or "datos"

        # Aplicar overrides deterministas por nombre de tool
        for name, cat in _CATEGORY_OVERRIDES.items():
            if name in self.tool_category:
                self.tool_category[name] = cat

        self._ready = True

    def route(self, user_message: str) -> List[dict]:
        if not self._ready or self._client is None:
            return self.definitions

        # Meta-pregunta sobre la app: todas las herramientas visibles
        if _META.search(user_message):
            print("[router] meta-pregunta sobre la app -> todas las herramientas")
            return self.definitions

        msg_emb = self._embed([user_message])[0]

        sims: Dict[str, float] = {}
        for cat, a_emb in self.anchor_embeddings.items():
            sims[cat] = _cosine(msg_emb, a_emb)

        # Boost determinista por keywords
        for patron, cat in _BOOSTS:
            if patron.search(user_message):
                sims[cat] += 0.15

        # Gate de saludos: no arrastrar herramientas de dominio para saludos cortos,
        # pero dejar las básicas para que el modelo pueda responder directo si lo necesita
        if _SALUDO.match(user_message):
            print(f"[router] saludo detectado -> solo herramientas básicas")
            return [d for d in self.definitions
                    if d.get("function", {}).get("name") in BASIC_TOOL_NAMES]

        # Umbral de confianza: si la mejor ancla está por debajo, solo herramientas básicas
        orden = sorted(sims, key=sims.get, reverse=True)
        if sims[orden[0]] < _CONFIDENCE_THRESHOLD:
            print(f"[router] baja confianza ({sims[orden[0]]:.3f}) -> solo herramientas básicas")
            return [d for d in self.definitions
                    if d.get("function", {}).get("name") in BASIC_TOOL_NAMES]

        # Top-2 por margen: si el gap es estrecho, enviar ambas categorías
        if len(orden) >= 2 and sims[orden[0]] - sims[orden[1]] < _MARGIN_THRESHOLD:
            cats = orden[:2]
        else:
            cats = orden[:1]

        winning_cat = cats[0]
        print(f"[router] {winning_cat} {sims[winning_cat]:.3f} vs {orden[1]} {sims[orden[1]]:.3f} -> cats={cats}")

        selected = set(BASIC_TOOL_NAMES)
        for name, cat in self.tool_category.items():
            if cat in cats:
                selected.add(name)

        filtered_defs = [d for d in self.definitions if d.get("function", {}).get("name") in selected]
        return filtered_defs
