#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
http_session.py - Sesion HTTP compartida de Chispa con cookies del navegador.

Objetivo: que las peticiones web de las tools (busqueda, clima, mini-wiki,
OSINT) no sean rechazadas por anti-bots. Dos defensas:

1. Cabeceras de un navegador Chrome real (User-Agent, Accept, Accept-Language).
2. Cookies del navegador de Alberto cargadas de un archivo LOCAL, fuera del
   repo (NUNCA se versiona ni se imprime en resultados de tools).

Fuentes de cookies, en orden:
- $CHISPA_COOKIES: ruta a un cookies.txt en formato Netscape.
- ~/.local/share/Chispa/cookies.txt (mismo formato).
- (opcional) paquete browser_cookie3 si esta instalado: lee las cookies de
  Chrome directamente (pip install browser-cookie3).

Como exportar las cookies de Chrome (una vez):
  1. Instalar la extension "Get cookies.txt LOCALLY" en Chrome.
  2. Abrirla y exportar las cookies (modo Netscape).
  3. Guardar el archivo como ~/.local/share/Chispa/cookies.txt
  4. chmod 600 ~/.local/share/Chispa/cookies.txt (que solo tu lo lea)

Sin cookies configuradas, la sesion funciona igual (solo cabeceras de
navegador), asi que ninguna tool se rompe.
"""
from __future__ import annotations

import os
from http.cookiejar import MozillaCookieJar
from pathlib import Path

import requests

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
_HEADERS = {
    "User-Agent": _UA,
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.5",
}

# Rutas candidatas del archivo de cookies (formato Netscape)
_COOKIE_RUTAS = [
    os.environ.get("CHISPA_COOKIES", ""),
    str(Path.home() / ".local/share/Chispa/cookies.txt"),
]

_session = None
_fuente_cookies = ""


def fuente_cookies() -> str:
    """De donde salieron las cookies ('' = sin cookies). Nunca imprime valores."""
    get_session()
    return _fuente_cookies


def get_session() -> requests.Session:
    """Sesion requests compartida: cabeceras de Chrome + cookies del navegador.
    Se construye UNA vez por proceso y se reutiliza (las cookies de respuesta
    se van actualizando solas, como un navegador)."""
    global _session, _fuente_cookies
    if _session is not None:
        return _session

    s = requests.Session()
    s.headers.update(_HEADERS)

    # 1) Archivo cookies.txt (formato Netscape)
    for ruta in _COOKIE_RUTAS:
        if not ruta:
            continue
        p = Path(os.path.expanduser(ruta))
        if not p.exists():
            continue
        try:
            jar = MozillaCookieJar(str(p))
            jar.load(ignore_discard=True, ignore_expires=True)
            s.cookies.update(jar)
            _fuente_cookies = f"archivo ({p.name})"
        except Exception:
            _fuente_cookies = ""
        break

    # 2) Fallback opcional: leer Chrome directo (si el paquete esta instalado)
    if not _fuente_cookies:
        try:
            import browser_cookie3  # type: ignore
            s.cookies.update(browser_cookie3.chrome())
            _fuente_cookies = "browser_cookie3 (Chrome)"
        except Exception:
            pass

    _session = s
    return s


def http_get(url: str, timeout: int = 15, **kwargs):
    """GET con la sesion compartida (cabeceras de Chrome + cookies).
    kwargs extra (params, headers, ...) se pasan tal cual a requests."""
    return get_session().get(url, timeout=timeout, **kwargs)


if __name__ == "__main__":
    s = get_session()
    print("Sesion lista. Cookies desde:", _fuente_cookies or "(ninguna, solo cabeceras de navegador)")
    print("User-Agent:", s.headers.get("User-Agent", "?")[:60] + "...")
