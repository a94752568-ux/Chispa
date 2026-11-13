import re
import urllib.parse
import html as _html

from tools.http_session import http_get  # cabeceras de Chrome + cookies del usuario

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Busca informacion actualizada en internet: noticias, precios, documentacion, eventos recientes, personas o datos que cambian. USALO en cuanto el usuario pida algo actual. Para NOTICIAS usa consultas cortas tipo 'noticias Mexico hoy' (2-4 palabras clave, SIN 'fecha actual' ni relleno). No inventes resultados.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Consulta corta y concreta (2-5 palabras clave)"},
                "num_results": {"type": "integer", "description": "Numero de resultados (default 5)"}
            },
            "required": ["query"]
        }
    }
}

# Deteccion de consultas de noticias: usan backend de Bing News
_NOTICIAS_RE = re.compile(r"noticia|news|titulares|ultima hora|actualidad|ultimas|de hoy|que paso", re.IGNORECASE)

_NUM_CTX_TIP = ("2-4 palabras clave, sin 'fecha actual' ni palabras de relleno")


def _clean_html(text: str) -> str:
    text = re.sub(r'<script.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _limpiar_rss(texto: str) -> str:
    """Limpia un campo de RSS: CDATA, etiquetas HTML y entidades."""
    texto = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', texto, flags=re.DOTALL)
    texto = _clean_html(texto)
    return _html.unescape(texto)


def _parse_rss(xml: str, num_results: int) -> list:
    """Extrae items (titulo, descripcion, enlace) de un RSS 2.0."""
    items = []
    for m in re.finditer(r'<item>(.*?)</item>', xml, re.DOTALL | re.IGNORECASE):
        bloque = m.group(1)
        t = re.search(r'<title>(.*?)</title>', bloque, re.DOTALL | re.IGNORECASE)
        l = re.search(r'<link>(.*?)</link>', bloque, re.DOTALL | re.IGNORECASE)
        d = re.search(r'<description>(.*?)</description>', bloque, re.DOTALL | re.IGNORECASE)
        titulo = _limpiar_rss(t.group(1)) if t else ""
        enlace = _limpiar_rss(l.group(1)) if l else ""
        desc = _limpiar_rss(d.group(1)) if d else ""
        if titulo:
            items.append((titulo, desc, enlace))
        if len(items) >= num_results:
            break
    return items


def _formatar(resultados: list) -> str:
    formatted = []
    for title, body, href in resultados:
        src = f"Fuente: {href}" if href else ""
        if body:
            formatted.append(f"**{title}**\n{body}\n{src}".rstrip())
        else:
            formatted.append(f"**{title}**\n{src}".rstrip())
    return "\n\n---\n\n".join(formatted)


def _fetch_bing_rss(query: str, num_results: int, news: bool = False):
    """Bing RSS: backend MUY estable sin bloqueos anti-bot. news=True usa
    Bing News (titulares con fecha); news=False busca web general."""
    q = urllib.parse.quote(query)
    url = (f"https://www.bing.com/news/search?q={q}&format=RSS" if news
           else f"https://www.bing.com/search?q={q}&format=rss")
    try:
        resp = http_get(url, timeout=12)
        if resp.status_code != 200:
            return None
        items = _parse_rss(resp.text, num_results)
        return _formatar(items) if items else None
    except Exception:
        return None


def _ddgs_buscar(query: str, num_results: int, news: bool = False):
    """Libreria ddgs/duckduckgo_search si esta instalada; soporta backend news."""
    try:
        try:
            from ddgs import DDGS  # tipo: ignore
        except Exception:
            from duckduckgo_search import DDGS  # tipo: ignore
        resultados = []
        with DDGS() as ddgs:
            if news and hasattr(ddgs, "news"):
                it = ddgs.news(query, max_results=num_results)
            else:
                it = ddgs.text(query, max_results=num_results)
            for r in it:
                title = r.get('title', '')
                body = r.get('body', '')
                href = r.get('href') or r.get('url') or r.get('link') or ''
                if title or body:
                    resultados.append((title, body, href))
        return _formatar(resultados) if resultados else None
    except Exception:
        return None


def _parse_duckduckgo_html(html: str, num_results: int) -> list:
    """Extrae resultados del HTML de DuckDuckGo con varios patrones."""
    results = []
    pattern1 = re.compile(
        r'<a[^>]+rel="nofollow"[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*'
        r'(?:.*?<td class="result-snippet">(.*?)</td>)?',
        re.DOTALL | re.IGNORECASE,
    )
    for m in pattern1.finditer(html):
        href = m.group(1)
        title = _clean_html(m.group(2))
        snippet = _clean_html(m.group(3) or "")
        if title and href and href.startswith("http"):
            results.append((title, snippet, href))
        if len(results) >= num_results:
            break
    if results:
        return results

    pattern2 = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )
    for m in pattern2.finditer(html):
        href = m.group(1)
        title = _clean_html(m.group(2))
        if title and href and href.startswith("http"):
            results.append((title, "", href))
        if len(results) >= num_results:
            break
    return results


def _fetch_duckduckgo(query: str, num_results: int):
    encoded = urllib.parse.quote(query)
    urls = [
        f"https://html.duckduckgo.com/html/?q={encoded}",
        f"https://lite.duckduckgo.com/lite/?q={encoded}",
        f"https://duckduckgo.com/html/?q={encoded}",
    ]
    for url in urls:
        try:
            resp = http_get(url, timeout=12)
            if resp.status_code != 200:
                continue
            results = _parse_duckduckgo_html(resp.text, num_results)
            if results:
                return _formatar(results)
        except Exception:
            continue
    return None


def execute(query: str, num_results: int = 5) -> str:
    query = (query or "").strip()
    num_results = max(1, min(int(num_results or 5), 10))
    news = bool(_NOTICIAS_RE.search(query))

    # Cascada de backends: ddgs -> Bing RSS (news o web) -> scraping DDG
    r = _ddgs_buscar(query, num_results, news=news)
    if r:
        return r
    r = _fetch_bing_rss(query, num_results, news=news)
    if r:
        return r
    r = _fetch_duckduckgo(query, num_results)
    if r:
        return r
    if news:
        # La consulta parecia de noticias pero Bing News no dio nada: web general
        r = _fetch_bing_rss(query, num_results, news=False)
        if r:
            return r

    return (f"Busqueda '{query}' sin resultados en este momento. NO inventes "
            f"informacion: informalo al usuario y ofrecele repetir la busqueda "
            f"con una consulta mas corta y simple ({_NUM_CTX_TIP}).")
