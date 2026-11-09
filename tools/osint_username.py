"""
OSINT pasivo: busqueda de alias / nombre de usuario en plataformas publicas.

Variables de entorno:
    Ninguna obligatoria (consultas HTTP ligeras a paginas publicas).

Uso por terminal (pruebas unitarias):
    python tools/osint_username.py fulanodetexto
    python tools/osint_username.py juanperez1985
"""

import re
import concurrent.futures
import urllib.request
import urllib.error

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]
TIMEOUT = 10

PLATAFORMAS = [
    ("GitHub", "https://github.com/{}"),
    ("GitLab", "https://gitlab.com/{}"),
    ("Reddit", "https://www.reddit.com/user/{}"),
    ("Keybase", "https://keybase.io/{}"),
    ("Instagram", "https://www.instagram.com/{}"),
    ("TikTok", "https://www.tiktok.com/@{}"),
    ("Pinterest", "https://www.pinterest.com/{}/"),
    ("X / Twitter", "https://x.com/{}"),
    ("HackerNews", "https://news.ycombinator.com/user?id={}"),
    ("DeviantArt", "https://www.deviantart.com/{}"),
]

PATRONES_NO_EXISTE = [
    re.compile(r"Page Not Found", re.I),
    re.compile(r"usuario no encontrado", re.I),
    re.compile(r"user not found", re.I),
    re.compile(r"no existe", re.I),
    re.compile(r"this account doesn.t exist", re.I),
    re.compile(r"sorry, this page isn.t available", re.I),
    re.compile(r"the page you are looking for", re.I),
]


def _http_get(url):
    for ua in USER_AGENTS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                code = resp.getcode()
                body = resp.read(200000).decode("utf-8", errors="replace")
                return code, body, None
        except urllib.error.HTTPError as e:
            if e.code in (429, 403):
                return e.code, "", f"servicio bloqueando la IP residencial (HTTP {e.code}). Usa un proxy o intenta mas tarde."
            if e.code == 404:
                return 404, "", None
            return e.code, "", f"error HTTP {e.code}"
        except Exception:
            continue
    return 0, "", "error de red"


TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "hunt_alias",
        "description": "USAR CUANDO el usuario quiere saber si un nombre de usuario o alias existe en redes sociales. Ejemplos: '¿Existe el usuario johndoe en GitHub?', 'Busca este alias en redes sociales', '¿torvalds tiene cuenta en Reddit?', '¿Este username está en múltiples plataformas?'. Busca en 10 plataformas: GitHub, GitLab, Reddit, Keybase, Instagram, TikTok, Pinterest, X/Twitter, HackerNews, DeviantArt. NO usar para: buscar correos electrónicos, investigar dominios, o detectar tecnologías web.",
        "parameters": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Alias o nombre de usuario a buscar, ej: fulanodetexto"}
            },
            "required": ["username"],
        },
    },
}


def _check_platform(args):
    nombre, url_tpl = args
    url = url_tpl.format(args[1] if len(args) > 1 else "")
    # args[1] es el username; reconstruimos limpio
    return _check_single(nombre, url_tpl, args[1])


def _check_single(nombre, url_tpl, username):
    url = url_tpl.format(username)
    code, body, err = _http_get(url)
    if err:
        estado, detalle = "Bloqueado", err
    elif code == 404:
        estado, detalle = "No encontrado", None
    elif code in (429, 403):
        estado, detalle = "Bloqueado", f"HTTP {code}"
    elif code >= 400:
        estado, detalle = "No encontrado", f"HTTP {code}"
    else:
        falso_positivo = any(pat.search(body) for pat in PATRONES_NO_EXISTE)
        if falso_positivo:
            estado, detalle = "No encontrado", None
        else:
            estado, detalle = "Posiblemente encontrado", None
    return nombre, url, estado, detalle


def execute(username: str) -> str:
    username = (username or "").strip()
    if not username:
        return "Proporciona un alias valido en el parametro `username`."

    lineas = [f"# Busqueda de alias: `{username}`", ""]

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futuros = [(p, u) for p, u in PLATAFORMAS]
        resultados = list(executor.map(lambda args: _check_single(args[0], args[1], username), futuros))

    lineas.append("| Plataforma | Estado | URL |")
    lineas.append("|------------|--------|-----|")
    for nombre, url, estado, detalle in resultados:
        badge = {
            "Posiblemente encontrado": "SI",
            "No encontrado": "NO",
            "Bloqueado": "BLOQUEADO",
            "Error": "ERROR",
        }.get(estado, estado)
        lineas.append(f"| {nombre} | {badge} | {url} |")

    lineas.append("")
    encontrados = [r for r in resultados if r[2] == "Posiblemente encontrado"]
    if encontrados:
        lineas.append("## Alias posiblemente existentes:")
        for nombre, url, _, _ in encontrados:
            lineas.append(f"- [{nombre}]({url})")
    else:
        lineas.append("## No se encontraron coincidencias claras en las plataformas consultadas.")

    bloqueados = [r for r in resultados if r[2] == "Bloqueado"]
    if bloqueados:
        lineas.append("")
        lineas.append("## Aviso: algunas plataformas bloquean la IP residencial")
        for nombre, _, _, detalle in bloqueados:
            lineas.append(f"- {nombre}: {detalle}")

    lineas.append("")
    lineas.append("*Consulta pasiva: peticiones GET ligeras sin autenticacion ni interaccion con el objetivo.*")

    return "\n".join(lineas)


# Alias semántico para compatibilidad con scripts de prueba y llamadas directas
hunt_alias = execute


if __name__ == "__main__":
    import sys
    u = sys.argv[1] if len(sys.argv) > 1 else "fulanodetexto"
    print(execute(u))
