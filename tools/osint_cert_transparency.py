#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
osint_cert_transparency.py — Enumeración pasiva de subdominios vía crt.sh.

Consulta los certificados SSL/TLS emitidos históricamente para un dominio
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request

_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
INTENTOS = 2
TIMEOUT_PETICION = 9
MAX_MOSTRADOS = 40

SENSIBLES = {
    "dev": "entorno de desarrollo", "staging": "pre-producción", "test": "pruebas",
    "qa": "control de calidad", "admin": "administración", "panel": "panel de control",
    "mail": "correo", "smtp": "correo saliente", "ftp": "transferencia de archivos",
    "git": "repositorios de código", "vpn": "acceso remoto", "api": "API pública/privada",
    "db": "base de datos", "backup": "copias de seguridad", "internal": "infraestructura interna",
}

TOOL_NAME = "list_subdomains"
TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "list_subdomains",
        "description": (
            "USAR CUANDO el usuario quiere enumerar o listar subdominios de un dominio. "
            "Ejemplos: '¿Qué subdominios tiene mozilla.org?', 'Lista todos los subdominios de google.com', "
            "¿Existen subdominios dev/staging/api en example.com?', 'Enumera subdominios vía Certificate Transparency'. "
            "Consulta crt.sh para obtener todos los certificados SSL/TLS emitidos históricamente para el dominio, "
            "extrae nombres comunes (CN) y nombres alternativos (SAN), deduplica y filtra wildcards. "
            "NO usar para: WHOIS/DNS (usa recon_target), detectar tecnologías (usa fingerprint_url) "
            "o escanear puertos (no está implementado por ser activo)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Dominio raíz sin 'www.' ni protocolo (ej: 'example.com')",
                }
            },
            "required": ["domain"],
        },
    },
}


def _norm_domain(d: str) -> str:
    d = re.sub(r"^https?://", "", d.strip().lower()).split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    if not d or "." not in d:
        raise ValueError(f"Dominio no válido: {d}")
    return d


def _fetch(domain: str):
    url = f"https://crt.sh/?q=%25{domain}&output=json"
    ultimo_error = ""
    for intento in range(1, INTENTOS + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT_PETICION) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            ultimo_error = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            ultimo_error = str(getattr(e, "reason", e))
        except json.JSONDecodeError:
            ultimo_error = "respuesta no-JSON de crt.sh"
        if intento < INTENTOS:
            time.sleep(2 * intento)
    raise RuntimeError(
        f"crt.sh no disponible tras {INTENTOS} intentos ({ultimo_error}). "
        f"Suele ser rate-limiting temporal: reintenta en unos minutos."
    )


def _subdomains(domain: str) -> str:
    domain = _norm_domain(domain)
    t0 = time.time()
    data = _fetch(domain)
    nombres, wildcards = set(), set()
    for entry in data:
        for linea in (entry.get("name_value") or "").splitlines():
            linea = linea.strip().lower()
            if not linea:
                continue
            if linea.startswith("*."):
                wildcards.add(linea[2:])
            elif linea == domain or linea.endswith("." + domain):
                nombres.add(linea)
    subs = sorted(nombres)
    dt = time.time() - t0

    out = [f"## Subdominios de {domain} (Certificate Transparency)", ""]
    out.append(f"- **Certificados históricos**: {len(data)}")
    out.append(f"- **Subdominios únicos**: {len(subs)}")
    wc = ", ".join(sorted(wildcards)[:5]) if wildcards else ""
    out.append(f"- **Wildcards**: {len(wildcards)}" + (f" ({wc})" if wc else ""))
    out.append(f"- **Consulta**: {dt:.2f}s")
    out.append("")
    if not subs:
        out.append("Sin certificados públicos: dominio sin historial TLS visible o inexistente.")
        return "\n".join(out)

    out.append("### Subdominios detectados")
    for i, s in enumerate(subs[:MAX_MOSTRADOS], 1):
        out.append(f"{i}. `{s}`")
    if len(subs) > MAX_MOSTRADOS:
        out.append(f"… y {len(subs) - MAX_MOSTRADOS} más.")

    hallazgos = [f"- `{s}` → posible {SENSIBLES[s.split('.')[0]]}"
                 for s in subs if s.split(".")[0] in SENSIBLES]
    out.append("")
    out.append("### Observaciones")
    out.extend(hallazgos[:8] if hallazgos else ["- Sin subdominios sensibles evidentes."])
    return "\n".join(out)


def execute(*args, **kwargs) -> str:
    """Contrato del plugin: acepta execute(dict) o execute(domain=...)."""
    params = {}
    for a in args:
        if isinstance(a, dict):
            params.update(a)
        elif isinstance(a, str) and "domain" not in params:
            params["domain"] = a
    params.update({k: v for k, v in kwargs.items() if v is not None})
    domain = str(params.get("domain") or params.get("target") or "").strip()
    if not domain:
        return "⚠️ list_subdomains necesita el parámetro 'domain'."
    try:
        return _subdomains(domain)
    except RuntimeError as e:
        return f"⚠️ {e}"
    except Exception as e:
        return f"⚠️ Error en list_subdomains: {type(e).__name__}: {e}"


list_subdomains = execute

if __name__ == "__main__":
    print(execute(domain=sys.argv[1] if len(sys.argv) > 1 else "example.com"))
