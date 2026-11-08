import re
import requests
import urllib.parse

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Busca informacion actualizada en internet. USALO cuando necesites noticias, precios, clima, documentacion, eventos recientes, personas, o datos que cambian. No inventes.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Consulta clara y especifica"},
                "num_results": {"type": "integer", "description": "Numero de resultados (default 5)"}
            },
            "required": ["query"]
        }
    }
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": "https://duckduckgo.com/",
}


def _clean_html(text: str) -> str:
    text = re.sub(r'<script.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#39;', "'", text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _parse_duckduckgo_html(html: str, num_results: int) -> list:
    """Intenta extraer resultados del HTML de DuckDuckGo usando varios patrones."""
    results = []

    # Patrón 1: resultado clásico de lite.duckduckgo.com
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

    # Patrón 2: resultado general con clase result__a
    pattern2 = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )
    snippets = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="[^"]+"[^>]*>.*?</a>\s*'
        r'(?:.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>)?',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    for i, m in enumerate(pattern2.finditer(html)):
        href = m.group(1)
        title = _clean_html(m.group(2))
        snippet = _clean_html(snippets[i]) if i < len(snippets) else ""
        if title and href and href.startswith("http"):
            results.append((title, snippet, href))
        if len(results) >= num_results:
            break

    return results


def _fetch_duckduckgo(query: str, num_results: int) -> str:
    encoded = urllib.parse.quote(query)

    urls = [
        f"https://html.duckduckgo.com/html/?q={encoded}",
        f"https://lite.duckduckgo.com/lite/?q={encoded}",
        f"https://duckduckgo.com/html/?q={encoded}",
    ]

    for url in urls:
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=12)
            if resp.status_code != 200:
                continue
            results = _parse_duckduckgo_html(resp.text, num_results)
            if results:
                formatted = []
                for title, snippet, href in results:
                    src = f"Fuente: {href}"
                    if snippet:
                        formatted.append(f"**{title}**\n{snippet}\n{src}")
                    else:
                        formatted.append(f"**{title}**\n{src}")
                return "\n\n---\n\n".join(formatted)
        except Exception:
            continue

    return None


def execute(query: str, num_results: int = 5) -> str:
    # Intenta DDGS primero
    try:
        DDGS = None
        try:
            from ddgs import DDGS  # tipo: ignore
        except Exception:
            from duckduckgo_search import DDGS  # tipo: ignore
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=num_results):
                title = r.get('title', '')
                body = r.get('body', '')
                href = r.get('href', '')
                if title or body:
                    results.append((title, body, href))
        if results:
            formatted = []
            for title, body, href in results:
                src = f"Fuente: {href}"
                if body:
                    formatted.append(f"**{title}**\n{body}\n{src}")
                else:
                    formatted.append(f"**{title}**\n{src}")
            return "\n\n---\n\n".join(formatted)
    except Exception as ddgs_err:
        # DDGSException: "No results found" -> buscar no tuvo resultados
        # Otras excepciones -> error de red, intentar scraping
        pass

    # Fallback: scraping directo de DuckDuckGo HTML
    scraped = _fetch_duckduckgo(query, num_results)
    if scraped:
        return scraped

    # Ambos fallaron: buscar realmente está vacío o error de red
    return f"Busqueda '{query}' sin resultados disponibles en este momento. Intenta de nuevo o reformula la consulta."
