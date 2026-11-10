#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""memoria.py — Persistencia multi-conversación en chats.json.

Modelo: {"chats": [{"id", "title", "updated", "messages"}]}.
El historial legacy (chat_history.json) se migra como primera conversación
la primera vez que se abre la app; el archivo legacy se conserva como respaldo.
Tope por conversación: MAX_MEMORY_MESSAGES, igual que el contexto al modelo.
"""
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

MEMORY_DIR = Path.home() / ".local" / "share" / "Chispa"
# Renombrado de la app (OllamaChat-GUI → Chispa): si existe la carpeta
# vieja y la nueva no, se migra entera (chats.json incluido) sin pérdida.
_LEGACY_DIR = Path.home() / ".local" / "share" / "OllamaChat-GUI"
if _LEGACY_DIR.exists() and not MEMORY_DIR.exists():
    import shutil as _shutil
    _shutil.move(str(_LEGACY_DIR), str(MEMORY_DIR))
CHATS_FILE = MEMORY_DIR / "chats.json"
LEGACY_FILE = MEMORY_DIR / "chat_history.json"
MAX_MEMORY_MESSAGES = 40


def _ensure_memory_dir():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _cargar_db() -> dict:
    """Carga chats.json; si no existe, migra el historial legacy si lo hay."""
    try:
        if CHATS_FILE.exists():
            with open(CHATS_FILE, "r", encoding="utf-8") as f:
                db = json.load(f)
            if isinstance(db, dict) and isinstance(db.get("chats"), list):
                return db
    except Exception as e:
        print(f"⚠ No se pudo cargar chats.json: {e}")
    # Migración legacy: chat_history.json (lista plana) → primera conversación
    try:
        if LEGACY_FILE.exists():
            with open(LEGACY_FILE, "r", encoding="utf-8") as f:
                legacy = json.load(f)
            if isinstance(legacy, list) and legacy:
                db = {"chats": [{
                    "id": uuid4().hex[:12],
                    "title": auto_titulo_de(legacy),
                    "updated": datetime.now().isoformat(timespec="seconds"),
                    "messages": legacy[-MAX_MEMORY_MESSAGES:],
                }]}
                _guardar_db(db)
                print("Memoria legacy migrada a chats.json (respaldo conservado)")
                return db
    except Exception as e:
        print(f"⚠ No se pudo migrar chat_history.json legacy: {e}")
    return {"chats": []}


def _guardar_db(db: dict) -> None:
    try:
        _ensure_memory_dir()
        with open(CHATS_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠ No se pudo guardar chats.json: {e}")


def titulo(texto: str) -> str:
    """Título corto a partir del texto del primer mensaje."""
    t = (texto or "").strip()
    if not t:
        return "Nuevo chat"
    linea = t.splitlines()[0].strip()
    if not linea:
        return "Nuevo chat"
    return linea[:42] + ("…" if len(linea) > 42 else "")


def auto_titulo_de(messages: list) -> str:
    """Título automático: primer mensaje de usuario de la conversación."""
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "user" and (m.get("content") or "").strip():
            return titulo(m["content"])
    return "Nuevo chat"


def listar_chats() -> list:
    """Metadatos de todas las conversaciones, la más reciente primero."""
    db = _cargar_db()
    chats = [c for c in db["chats"] if isinstance(c, dict)]
    chats.sort(key=lambda c: c.get("updated", ""), reverse=True)
    return [
        {"id": c.get("id"), "title": c.get("title", "Nuevo chat"), "updated": c.get("updated", "")}
        for c in chats
    ]


def crear_chat(title: str = "Nuevo chat") -> str:
    db = _cargar_db()
    cid = uuid4().hex[:12]
    db["chats"].append({
        "id": cid,
        "title": title,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "messages": [],
    })
    _guardar_db(db)
    return cid


def cargar_chat(cid: str) -> list:
    """Historial de una conversación (recortado al tope); vacío si no existe."""
    db = _cargar_db()
    for c in db["chats"]:
        if isinstance(c, dict) and c.get("id") == cid:
            msgs = c.get("messages") or []
            return msgs[-MAX_MEMORY_MESSAGES:] if isinstance(msgs, list) else []
    return []


def guardar_chat(cid: str, title: str, messages: list) -> None:
    """Actualiza (o crea) una conversación con tope de mensajes."""
    db = _cargar_db()
    now = datetime.now().isoformat(timespec="seconds")
    for c in db["chats"]:
        if isinstance(c, dict) and c.get("id") == cid:
            c["title"] = title
            c["messages"] = messages[-MAX_MEMORY_MESSAGES:]
            c["updated"] = now
            _guardar_db(db)
            return
    db["chats"].append({
        "id": cid,
        "title": title,
        "updated": now,
        "messages": messages[-MAX_MEMORY_MESSAGES:],
    })
    _guardar_db(db)


def eliminar_chat(cid: str) -> None:
    db = _cargar_db()
    db["chats"] = [c for c in db["chats"] if not (isinstance(c, dict) and c.get("id") == cid)]
    _guardar_db(db)


def cargar() -> list:
    """Compatibilidad legacy: historial de la conversación más reciente."""
    chats = listar_chats()
    if chats:
        return cargar_chat(chats[0]["id"])
    return []
