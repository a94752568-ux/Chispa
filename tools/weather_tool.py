import re
import requests

# País por defecto del usuario: si el modelo manda la ciudad SIN país, se
# prueba primero con este (evita el clásico "La Paz" -> La Paz, Bolivia
# cuando el usuario está en Baja California Sur). Si esa combinación no
# existe en wttr.in, se reintenta con la ciudad tal cual.
DEFAULT_COUNTRY = "Mexico"

# El modelo a veces mete la frase completa en city ("Clima en La Paz").
# Se limpia el prefijo para quedarnos solo con la ciudad.
_PREFIX_RE = re.compile(
    r"(?i)^(?:[\s¿¡]*(?:qué?|que|dime|muestra|dame|consulta|ver|revisa)\s+)?"
    r"(?:el\s+|la\s+)?"
    r"(?:clima|tiempo|temperatura)\s*"
    r"(?:actual\s+|hace\s+|está\s+|esta\s+)?"
    r"(?:en|de|del|para)\s+"
)


def _sanitize_city(raw: str) -> str:
    """Deja solo el nombre de la ciudad: 'Clima en La Paz' -> 'La Paz'."""
    c = (raw or "").strip()
    c = _PREFIX_RE.sub("", c, count=1)
    c = re.sub(r"(?i)\s+(hoy|ahora|actualidad)$", "", c.strip())
    return c.strip().strip("¿?¡!.…").strip()


TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "USAR CUANDO el usuario pregunte por el clima o la temperatura de una ciudad. Ejemplos: '¿Qué clima hace en La Paz?', 'clima de Ciudad de México', 'temperatura en Madrid'. En city manda SOLO la ciudad (ej: 'La Paz'), nunca la frase completa; si el nombre es ambiguo en el mundo añade el país ('La Paz, Mexico'); sin país, la tool prueba primero con Mexico. Devuelve la ubicación RESUELTA (dila al usuario tal cual), temperatura, descripción, humedad y viento.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "Solo el nombre de la ciudad, sin frases: 'La Paz' o 'Madrid'. Con país si es ambigua: 'La Paz', 'Mexico'"}
            },
            "required": ["city"]
        }
    }
}


def execute(city: str = "La Paz") -> str:
    try:
        city = _sanitize_city(city)
        if not city:
            return "Falta la ciudad. Pásala en el argumento city (ej: 'La Paz')."

        # Sin país explícito se prueba primero con DEFAULT_COUNTRY; si esa
        # ciudad no existe ahí, se reintenta tal cual ('Tokio' -> Tokio, Japón).
        if "," in city:
            queries = [city]
        else:
            queries = [f"{city},{DEFAULT_COUNTRY}", city]

        data = None
        for q in queries:
            try:
                resp = requests.get(f"https://wttr.in/{q}?format=j1", timeout=10)
                if resp.status_code == 200:
                    d = resp.json()
                    if d.get("current_condition"):
                        data = d
                        break
            except Exception:
                continue

        if data is None:
            return (f"Sin datos de clima para '{city}'. Verifica el nombre o "
                    f"añade el país (ej: 'La Paz, Mexico' o 'Madrid, Spain').")

        current = data["current_condition"][0]
        area = (data.get("nearest_area") or [{}])[0]
        lugar = ((area.get("areaName") or [{}])[0]).get("value", "")
        region = ((area.get("region") or [{}])[0]).get("value", "")
        pais = ((area.get("country") or [{}])[0]).get("value", "")
        resuelto = ", ".join(x for x in (lugar, region, pais) if x) or city

        temp = current.get("temp_C", "?")
        desc = ((current.get("weatherDesc") or [{}])[0]).get("value", "")
        humidity = current.get("humidity", "?")
        wind = current.get("windspeedKmph", "?")

        return (f"Clima en {resuelto}: {temp}°C, {desc}, "
                f"Humedad {humidity}%, Viento {wind} km/h. "
                f"La ubicación resuelta es la de arriba: repórtala al usuario tal cual.")
    except Exception as e:
        return f"Error clima: {e}. Intenta con wttr.in/{city}?format=%25C+%25t"
