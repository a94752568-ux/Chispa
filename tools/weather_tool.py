import requests
TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "USAR CUANDO el usuario pregunte por el clima o la temperatura de una ciudad. Ejemplos: '¿Qué clima hace en La Paz?', 'clima de Ciudad de México', 'temperatura en Madrid'. En city incluye ciudad y país separados por coma para evitar ambigüedades (ej: 'La Paz, Mexico' — solo 'La Paz' puede ser Bolivia). Devuelve temperatura, descripción, humedad y viento.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "Ciudad, ej: La Paz, Mexico"}
            },
            "required": ["city"]
        }
    }
}
def execute(city: str = "La Paz") -> str:
    try:
        # wttr.in formato simple
        resp = requests.get(f"https://wttr.in/{city}?format=j1", timeout=10)
        data = resp.json()
        current = data.get('current_condition',[{}])[0]
        temp = current.get('temp_C','?')
        desc = current.get('weatherDesc',[{}])[0].get('value','')
        humidity = current.get('humidity','?')
        wind = current.get('windspeedKmph','?')
        return f"Clima en {city}: {temp}°C, {desc}, Humedad {humidity}%, Viento {wind} km/h"
    except Exception as e:
        return f"Error clima: {e}. Intenta con wttr.in/{city}?format=%25C+%25t"
