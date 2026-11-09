#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""memoria.py — Persistencia del historial de chat en chat_history.json.

Tope del historial persistido y del contexto enviado al modelo:
evita que chat_history.json y cada request crezcan sin límite.
"""
import json
from pathlib import Path

MEMORY_DIR = Path.home() / ".local" / "share" / "OllamaChat-GUI"
MEMORY_FILE = MEMORY_DIR / "chat_history.json"
MAX_MEMORY_MESSAGES = 40


def _ensure_memory_dir():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def cargar() -> list:
    """Devuelve el historial persistido (recortado al tope); lista vacía si falla o no existe."""
    try:
        if MEMORY_FILE.exists():
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data[-MAX_MEMORY_MESSAGES:]
    except Exception as e:
        print(f"⚠ No se pudo cargar la memoria persistente: {e}")
    return []


def guardar(chat_history: list) -> None:
    """Persiste el historial recortado al tope."""
    try:
        _ensure_memory_dir()
        historial = chat_history[-MAX_MEMORY_MESSAGES:]
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(historial, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠ No se pudo guardar la memoria persistente: {e}")
