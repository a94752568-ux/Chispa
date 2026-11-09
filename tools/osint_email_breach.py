"""
OSINT pasivo: verificacion de exposicion de correo en filtraciones publicas.

Variables de entorno:
    OSINT_API_KEY_HIBP   Clave de API de HaveIBeenPwned (v3). Obligatoria.
                         Exportala antes de usar: export OSINT_API_KEY_HIBP="tu_clave"

Uso por terminal (pruebas unitarias):
    python tools/osint_email_breach.py usuario@ejemplo.com
"""

import os
import json
import urllib.request
import urllib.error
from urllib.parse import quote

USER_AGENT = "OSINT-Plugin/1.0"
TIMEOUT = 10

API_KEY_ENV = "OSINT_API_KEY_HIBP"
API_BASE = "https://haveibeenpwned.com/api/v3"


def _http_get(url, headers=None):
    h = {"User-Agent": USER_AGENT, "Accept": "application/vnd.haveibeenpwned.v3+json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.getcode(), body, None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        if e.code in (429, 403):
            return e.code, body, f"servicio bloqueando la IP residencial (HTTP {e.code}). Usa un proxy o intenta mas tarde."
        return e.code, body, f"error HTTP {e.code}"
    except Exception as e:
        return 0, "", str(e)


TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "check_exposure",
        "description": "USAR CUANDO el usuario pregunta si un correo electrónico fue comprometido o apareció en filtraciones de datos. Ejemplos: '¿Este email fue filtrado?', '¿user@gmail.com está en alguna brecha de datos?', 'Revisa si este correo apareció en HaveIBeenPwned', '¿Está comprometida esta dirección?'. Consulta la API de HaveIBeenPwned v3. Requiere variable de entorno OSINT_API_KEY_HIBP. Si no hay API key, devuelve instrucciones claras para configurarla. NO usar para: buscar alias de usuario, investigar dominios, o detectar tecnologías.
        "parameters": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Direccion de correo electronico a investigar, ej: usuario@dominio.com"}
            },
            "required": ["email"],
        },
    },
}


def execute(email: str) -> str:
    email = (email or "").strip()
    if not email or "@" not in email:
        return "Proporciona una direccion de correo electronico valida en el parametro `email`."

    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        return (
            f"# Exposicion de correo: `{email}`\n\n"
            f"Falta la clave de API de HaveIBeenPwned.\n"
            f"Exporta la variable de entorno y vuelve a intentar:\n\n"
            f"```bash\nexport {API_KEY_ENV}=\"tu_clave_de_api\"\npython tools/osint_email_breach.py {email}\n```\n\n"
            f"Obtén una clave gratuita en https://haveibeenpwned.com/API/Key"
        )

    url = f"{API_BASE}/breachedaccount/{quote(email, safe='')}?truncateResponse=false"
    code, body, err = _http_get(url, headers={"hibp-api-key": api_key})

    if err:
        return f"# Exposicion de correo: `{email}`\n\n{err}"

    if code == 404:
        return (
            f"# Exposicion de correo: `{email}`\n\n"
            f"No se encontraron filtraciones publicas asociadas a este correo en HaveIBeenPwned.\n"
        )

    if code == 401:
        return (
            f"# Exposicion de correo: `{email}`\n\n"
            f"Clave de API invalida o sin acceso a HaveIBeenPwned v3. Verifica `{API_KEY_ENV}`."
        )

    if code >= 400:
        return f"# Exposicion de correo: `{email}`\n\nError consultando HaveIBeenPwned (HTTP {code})."

    try:
        brechas = json.loads(body) if body else []
    except json.JSONDecodeError:
        return f"# Exposicion de correo: `{email}`\n\nNo se pudo procesar la respuesta de HaveIBeenPwned."

    if not brechas:
        return (
            f"# Exposicion de correo: `{email}`\n\n"
            f"No se encontraron filtraciones publicas asociadas a este correo en HaveIBeenPwned.\n"
        )

    lineas = [f"# Exposicion de correo: `{email}`", f"## {len(brechas)} filtracion(es) encontrada(s)", ""]
    lineas.append("| Filtracion | Anio | Datos comprometidos |")
    lineas.append("|------------|------|---------------------|")
    for b in brechas:
        nombre = b.get("Name", "Desconocida")
        fecha = b.get("BreachDate", "")
        anio = fecha[:4] if fecha else "N/D"
        clases = b.get("DataClasses", [])
        datos = ", ".join(clases) if clases else "No especificado"
        lineas.append(f"| {nombre} | {anio} | {datos} |")

    lineas.append("")
    lineas.append("*Consulta pasiva a HaveIBeenPwned v3. No interacciona con el objetivo ni expone credenciales.*")

    return "\n".join(lineas)


# Alias semántico para compatibilidad con scripts de prueba y llamadas directas
check_exposure = execute


if __name__ == "__main__":
    import sys
    e = sys.argv[1] if len(sys.argv) > 1 else "usuario@ejemplo.com"
    print(execute(e))
