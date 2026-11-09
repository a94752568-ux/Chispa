"""
OSINT pasivo: reconocimiento de IP y dominio.

Variables de entorno:
    Ninguna obligatoria (DNS-over-HTTPS de Google y ip-api.com no requieren clave).

Uso por terminal (pruebas unitarias):
    python tools/osint_ip_domain.py example.com
    python tools/osint_ip_domain.py 8.8.8.8
"""

import socket
import json
import re
import urllib.request
import urllib.error
from urllib.parse import quote

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]
TIMEOUT = 10


def _http_get_json(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENTS[0]})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body), None
    except urllib.error.HTTPError as e:
        if e.code in (429, 403):
            return None, f"servicio bloqueando la IP residencial (HTTP {e.code}). Intenta mas tarde o usa un proxy."
        return None, f"error HTTP {e.code}"
    except Exception as e:
        return None, str(e)


def _resolve_a(target):
    try:
        return socket.gethostbyname(target), None
    except socket.gaierror as e:
        return None, str(e)


def _doh(name, rtype):
    url = f"https://dns.google/resolve?name={quote(name)}&type={rtype}"
    data, err = _http_get_json(url)
    if err:
        return [], err
    records = []
    for ans in (data or {}).get("Answer", []) or []:
        records.append(ans.get("data", ""))
    return records, None


_WHOIS_SERVERS = {
    "com": "whois.verisign-grs.com",
    "net": "whois.verisign-grs.com",
    "org": "whois.pir.org",
    "edu": "whois.educause.edu",
    "gov": "whois.nic.gov",
    "es": "whois.nic.es",
    "uk": "whois.nic.uk",
    "de": "whois.denic.de",
    "fr": "whois.nic.fr",
    "it": "whois.nic.it",
    "nl": "whois.domain-registry.nl",
    "br": "whois.registro.br",
    "ar": "whois.nic.ar",
    "mx": "whois.mx",
    "cl": "whois.nic.cl",
    "co": "whois.nic.co",
    "pe": "whois.nic.pe",
}


def _whois_server_for(target):
    partes = target.rsplit(".", 1)
    if len(partes) == 2:
        tld = partes[1].lower()
        return _WHOIS_SERVERS.get(tld, "whois.iana.org")
    return "whois.iana.org"


def _query_whois_server(server, target, timeout=TIMEOUT):
    try:
        with socket.create_connection((server, 43), timeout=timeout) as s:
            s.sendall((target + "\r\n").encode())
            data = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
                if len(data) > 65536:
                    break
        return data.decode("utf-8", errors="replace"), None
    except Exception as e:
        return "", str(e)


def _parse_whois_fields(text):
    campos = {}
    patrones = {
        "registrar": r"(?i)^\s*registrar\s*:\s*(.+)$",
        "creation": r"(?i)^\s*(creation|created|registered on|registration date|creation date)\s*:\s*(.+)$",
        "updated": r"(?i)^\s*(updated|last updated|modified|registry expiry date|updated date)\s*:\s*(.+)$",
        "expires": r"(?i)^\s*(expires|expire|registry expiry date|expiration date|paid-till|expires on)\s*:\s*(.+)$",
        "registrant": r"(?i)^\s*(registrant|registrant name|registrant organization|owner|organization|org)\s*:\s*(.+)$",
        "country": r"(?i)^\s*(country|registrant country)\s*:\s*(.+)$",
        "nserver": r"(?i)^\s*(nserver|name server|nameserver)\s*:\s*(.+)$",
        "tech": r"(?i)^\s*(tech|technical contact)\s*:\s*(.+)$",
        "abuse": r"(?i)^\s*(abuse|abuse contact)\s*:\s*(.+)$",
    }
    for linea in text.splitlines():
        for clave, pat in patrones.items():
            m = re.match(pat, linea.strip())
            if m:
                valor = m.group(2) if m.lastindex >= 2 else m.group(1)
                if clave not in campos:
                    campos[clave] = []
                campos[clave].append(valor.strip())
    return campos


def _whois(target):
    server = _whois_server_for(target)
    text, err = _query_whois_server(server, target)
    if err or not text:
        # fallback a IANA si el servidor directo falla
        text2, err2 = _query_whois_server("whois.iana.org", target)
        if text2 and not err:
            m = re.search(r"(?i)refer:\s*(\S+)", text2)
            if m:
                text, err = _query_whois_server(m.group(1), target)
        elif not text:
            return {}, err or "WHOIS vacio"
    if err:
        return {}, err
    return _parse_whois_fields(text), None


TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "recon_target",
        "description": "USAR CUANDO el usuario pregunta sobre un dominio, direccion IP o infraestructura de red. Ejemplos: '¿Quien es el dueño de protonmail.com?', 'Haz un reconocimiento del dominio example.com', 'Dame info de la IP 8.8.8.8', '¿Cual es el proveedor de hosting de este dominio?'. Devuelve registros DNS (A, MX, TXT), WHOIS (registrante, fecha de expiración, servidores de nombre) y geolocalización de la IP (pais, ISP, ciudad, coordenadas). Todo de forma pasiva, sin escaneo de puertos ni fuerza bruta.",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Dominio (ej: example.com) o direccion IP (ej: 8.8.8.8) a investigar"}
            },
            "required": ["target"],
        },
    },
}



def execute(target: str) -> str:
    target = (target or "").strip()
    if not target:
        return "Proporciona un dominio o IP valida en el parametro `target`."

    es_ip = bool(re.match(r"^\d{1,3}(\.\d{1,3}){3}$", target))

    lineas = [f"# Reconocimiento pasivo: `{target}`", ""]

    lineas.append("## DNS")
    if not es_ip:
        a, err_a = _resolve_a(target)
        lineas.append(f"- **A:** {a if a else 'No resuelto'}" + (f" ({err_a})" if err_a else ""))
        mx, err_mx = _doh(target, "MX")
        lineas.append(f"- **MX:** {', '.join(mx) if mx else 'No disponibles'}" + (f" ({err_mx})" if err_mx else ""))
        txt, err_txt = _doh(target, "TXT")
        lineas.append(f"- **TXT:** {', '.join(txt) if txt else 'No disponibles'}" + (f" ({err_txt})" if err_txt else ""))
    else:
        lineas.append("- **A:** (target es IP, se omite resolucion de nombre)")
    lineas.append("")

    lineas.append("## Geolocalizacion IP")
    ip_obj = target if es_ip else None
    if not es_ip:
        ip_res, err_ip = _resolve_a(target)
        ip_obj = ip_res
        if err_ip:
            lineas.append(f"- No se pudo resolver la IP: {err_ip}")
    if ip_obj:
        data, err = _http_get_json(f"http://ip-api.com/json/{quote(ip_obj)}?fields=status,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query")
        if err:
            lineas.append(f"- {err}")
        elif data and data.get("status") == "success":
            lineas.append(
                f"- **IP:** {data.get('query')}\n"
                f"- **Pais:** {data.get('country')} ({data.get('countryCode')})\n"
                f"- **Region:** {data.get('regionName')} ({data.get('region')})\n"
                f"- **Ciudad:** {data.get('city')} {data.get('zip') or ''}\n"
                f"- **ISP:** {data.get('isp')} / {data.get('org')}\n"
                f"- **AS:** {data.get('as')}\n"
                f"- **Coords:** {data.get('lat')}, {data.get('lon')}\n"
                f"- **Zona horaria:** {data.get('timezone')}"
            )
        else:
            lineas.append("- No se obtuvo informacion de geolocalizacion.")
    lineas.append("")

    lineas.append("## WHOIS (basico)")
    campos, err_w = _whois(target)
    if err_w:
        lineas.append(f"- No se pudo consultar WHOIS: {err_w}")
    elif campos:
        lineas.append("```")
        if "registrar" in campos:
            lineas.append(f"Registrador: {campos['registrar'][0]}")
        if "registrant" in campos:
            lineas.append(f"Registrante: {campos['registrant'][0]}")
        if "organization" in campos and "registrant" not in campos:
            lineas.append(f"Organizacion: {campos['organization'][0]}")
        if "country" in campos:
            lineas.append(f"Pais: {campos['country'][0]}")
        if "creation" in campos:
            lineas.append(f"Creacion: {campos['creation'][0]}")
        if "expires" in campos:
            lineas.append(f"Expiración: {campos['expires'][0]}")
        if "updated" in campos:
            lineas.append(f"Actualización: {campos['updated'][0]}")
        if "nserver" in campos:
            lineas.append("Nameservers:")
            for ns in campos["nserver"][:5]:
                lineas.append(f"  - {ns}")
        lineas.append("```")
    else:
        lineas.append("- WHOIS vacio o no disponible.")
    lineas.append("")
    lineas.append("*Nota: consulta pasiva sin escaneo de puertos ni fuerza bruta.*")

    return "\n".join(lineas)


# Alias semántico para compatibilidad con scripts de prueba y llamadas directas
recon_target = execute


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "example.com"
    print(execute(t))
