#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
osint_tech_fingerprint.py — Fingerprinting pasivo de tecnologías web.

Detecta servidor web, CDN, CMS, frameworks JS y analytics analizando
headers HTTP y HTML. 100% stdlib, sin API keys, sin escaneo activo.

Variables de entorno: ninguna.
Prueba por terminal:
    python tools/osint_tech_fingerprint.py https://example.com
"""

from __future__ import annotations
from html.parser import HTMLParser

import re
import sys
import time
import urllib.error
import urllib.request

_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
TIMEOUT = 12
MAX_BODY = 600_000

TOOL_NAME = "fingerprint_url"

class TechParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.metas = []
        self.links = []
        self.in_script = False
        self.in_style = False
        self.detected_cms = set()
        self.detected_frameworks = set()
        self.detected_analytics = set()
        self.detected_cdn = set()
        self.detected_languages = set()
        self.detected_servers = set()

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.in_script = True
        elif tag == "style":
            self.in_style = True
        elif tag == "meta":
            attrs_dict = dict(attrs)
            self.metas.append(attrs_dict)
        elif tag == "link":
            attrs_dict = dict(attrs)
            self.links.append(attrs_dict)

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False
        elif tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_script and data:
            self.scripts.append(data)

    def _get_meta_content(self, name):
        for meta in self.metas:
            if meta.get("name", "").lower() == name.lower() or meta.get("property", "").lower() == name.lower():
                return meta.get("content", "")
        return ""

    def _get_link_href(self, rel):
        for link in self.links:
            if link.get("rel", "").lower() == rel.lower():
                return link.get("href", "")
        return ""


def _get_random_user_agent():
    import random
    return random.choice(_UA)


def _make_request(url):
    headers = HEADERS.copy()
    headers["User-Agent"] = _get_random_user_agent()

    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            content_type = resp.headers.get("Content-Type", "").lower()
            content = resp.read().decode("utf-8", errors="replace")
            if "text/html" in content_type:
                return content, resp.headers, None
            else:
                return None, resp.headers, f"Content-Type no HTML: {content_type}"
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return None, None, "Demasiadas solicitudes. Espera un momento e intenta de nuevo."
        elif e.code == 403:
            return None, None, "Acceso prohibido (403). El sitio puede bloquear requests automáticos."
        elif e.code == 404:
            return None, None, "Página no encontrada (404)."
        elif e.code == 500:
            return None, None, "Error del servidor (500)."
        else:
            return None, None, f"Error HTTP {e.code}"
    except urllib.error.URLError as e:
        if "timeout" in str(e).lower():
            return None, None, "Tiempo de espera agotado (timeout)."
        else:
            return None, None, f"Error de URL: {e.reason}"
    except Exception as e:
        return None, None, f"Error inesperado: {str(e)}"


def _extract_headers_info(headers):
    info = {
        "server": "",
        "cdn": "",
        "country": "",
        "web_server": "",
        "tech_stack": [],
    }

    server_header = headers.get("Server", "")
    if server_header:
        info["server"] = server_header
        server_lower = server_header.lower()
        if "cloudflare" in server_lower:
            info["cdn"] = "Cloudflare"
            info["web_server"] = server_header
        elif "akamai" in server_lower:
            info["cdn"] = "Akamai"
            info["web_server"] = server_header
        elif "fastly" in server_lower:
            info["cdn"] = "Fastly"
            info["web_server"] = server_header
        elif "nginx" in server_lower:
            info["web_server"] = server_header
        elif "apache" in server_lower:
            info["web_server"] = server_header
        elif "iis" in server_lower:
            info["web_server"] = server_header
        elif "litespeed" in server_lower:
            info["web_server"] = server_header
        else:
            info["web_server"] = server_header

    cf_ray = headers.get("CF-RAY", "")
    cf_cache = headers.get("CF-Cache-Status", "")
    if cf_ray or cf_cache:
        info["cdn"] = "Cloudflare"

    return info


def _analyze_html(content, headers_info):
    parser = TechParser()
    try:
        parser.feed(content)
    except Exception:
        pass

    html_lower = content.lower()

    cms_patterns = {
        "WordPress": [
            r"/wp-content/",
            r"wp-includes/",
            r"wp-admin/",
            r"_wpnonce",
            r"wordpress",
            r"wp-emoji",
            r"wp-json",
            r"wp-singletons",
        ],
        "Drupal": [
            r"sites/default/",
            r"drupal",
            r"js/drupal",
            r"drupal-settings",
        ],
        "Joomla": [
            r"com_content",
            r"templates/default/",
            r"joomla",
            r"media/joomla",
        ],
    }

    framework_patterns = {
        "React": [
            r"reactdom.",
            r"react@",
            r"__react",
            r"data-reactid",
            r"react.js",
        ],
        "Vue": [
            r"vue@",
            r"vue-router",
            r"__vue",
            r"v-bind:",
            r"v-on:",
        ],
        "Angular": [
            r"angularjs",
            r"angular@",
            r"ng-app",
            r"ng-model",
        ],
    }

    analytics_patterns = {
        "Google Analytics": [
            r"gtag\(",
            r"ga\(",
            r"analytics.js",
            r"google-analytics",
        ],
        "Google Analytics 4": [
            r"gtag\("],
        "Facebook Pixel": [
            r"facebook",
            r"fbq\(",
            r"pixel",
        ],
    }

    cdn_patterns = {
        "Cloudflare": [r"cf-ray", r"cloudflare"],
        "Akamai": [r"akamai"],
        "Fastly": [r"fastly"],
        "AWS CDN": [r"cloudfront"],
    }

    lang_patterns = {
        "PHP": [r"x-powered-by.*php", r"\.php"],
        "Python": [r"x-powered-by.*python", r"\.py"],
        "Java": [r"x-powered-by.*java", r"\.java"],
        "Node.js": [r"x-powered-by.*node", r"nodejs"],
        "Ruby": [r"x-powered-by.*ruby", r"\.rb"],
    }

    detected = parser.detected_cms
    detected.update(_detect_by_patterns(html_lower, cms_patterns, parser._get_meta_content))
    detected.update(_detect_by_patterns(html_lower, framework_patterns, parser._get_meta_content))
    detected.update(_detect_by_patterns(html_lower, analytics_patterns, parser._get_meta_content))
    detected.update(_detect_by_patterns(html_lower, cdn_patterns, parser._get_meta_content))
    detected.update(_detect_by_patterns(html_lower, lang_patterns, parser._get_meta_content))

    return detected


def _detect_by_patterns(content, patterns, meta_func):
    detected = set()
    for tech, pattern_list in patterns.items():
        for pattern in pattern_list:
            if re.search(pattern, content, re.IGNORECASE):
                detected.add(tech)
                break
    return detected


def execute(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return "Proporciona una URL valida en el parametro `url`."

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    try:
        domain = urllib.parse.urlparse(url).netloc
        if not domain:
            return f"URL invalida: {url}"

        content, headers, error = _make_request(url)
        if error:
            return f"## Fingerprint de {domain}\n\n**Error**: {error}"

        if not content:
            return f"## Fingerprint de {domain}\n\nNo se pudo obtener contenido HTML."

        headers_info = _extract_headers_info(headers)

        tech_info = _analyze_html(content, headers_info)

        result_lines = [f"## Fingerprint de {domain}", ""]

        result_lines.append("### Servidor")
        result_lines.append(f"- **Web server**: {headers_info['web_server'] or 'Desconocido'}")
        if headers_info['cdn']:
            result_lines.append(f"- **CDN**: {headers_info['cdn']}")
        result_lines.append("")

        result_lines.append("### Tecnologías detectadas")
        cms_found = [t for t in tech_info if t in ["WordPress", "Drupal", "Joomla"]]
        frameworks_found = [t for t in tech_info if t in ["React", "Vue", "Angular"]]
        analytics_found = [t for t in tech_info if t in ["Google Analytics", "Google Analytics 4", "Facebook Pixel"]]
        cdn_found = [t for t in tech_info if t in ["Cloudflare", "Akamai", "Fastly", "AWS CDN"]]
        langs_found = [t for t in tech_info if t in ["PHP", "Python", "Java", "Node.js", "Ruby"]]

        if cms_found:
            result_lines.append(f"- **CMS**: {', '.join(cms_found)}")
        if langs_found:
            result_lines.append(f"- **Lenguaje**: {', '.join(langs_found)}")
        if frameworks_found:
            result_lines.append(f"- **Frameworks**: {', '.join(frameworks_found)}")
        if analytics_found:
            result_lines.append(f"- **Analytics**: {', '.join(analytics_found)}")
        if cdn_found:
            result_lines.append(f"- **CDN**: {', '.join(cdn_found)}")

        if headers_info['cdn'] == 'Cloudflare':
            result_lines.append("\n### Observaciones")
            result_lines.append("- Cloudflare activa (headers cf-ray, cf-cache-status presentes)")

        return "\n".join(result_lines)

    except Exception as e:
        domain = urllib.parse.urlparse(url).netloc
        return f"## Fingerprint de {domain}\n\n**Error inesperado**: {str(e)}"

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "fingerprint_url",
        "description": (
            "USAR CUANDO el usuario pregunta qué tecnologías, CMS, frameworks o servidores usa un sitio web. "
            "Ejemplos: '¿Qué CMS usa github.com?', '¿Qué tecnologías tiene esta web?', "
            "'¿Es WordPress o Drupal este sitio?', '¿Qué servidor web usa example.com?', "
            "'¿Usa React o Vue esta página?', '¿Está detrás de Cloudflare?'. "
            "Detecta: servidores web (Nginx, Apache, IIS), CMS (WordPress, Drupal, Joomla), "
            "frameworks JS (React, Vue, Angular), analytics (Google Analytics, Facebook Pixel), "
            "CDNs (Cloudflare, Akamai, Fastly) y lenguajes de programación. "
            "NO usar para: obtener información WHOIS (usa recon_target), buscar subdominios "
            "(usa list_subdomains), o verificar usuarios (usa hunt_alias)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL del sitio web a analizar, ej: example.com o https://example.com"}
            },
            "required": ["url"]
        }
    }
}

fingerprint_url = execute

if __name__ == "__main__":
    print(execute(url=sys.argv[1] if len(sys.argv) > 1 else "example.com"))
