import pyttsx3

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "speak",
        "description": "Convierte texto a voz y lo reproduce por altavoces. Usa motor TTS offline del sistema (espeak en Lubuntu).",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Texto a reproducir por voz"},
                "rate": {"type": "integer", "description": "Velocidad de habla en palabras por minuto (default 175)"},
                "volume": {"type": "number", "description": "Volumen de 0.0 a 1.0 (default 1.0)"}
            },
            "required": ["text"]
        }
    }
}

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = pyttsx3.init()
        _engine.setProperty('rate', 175)
        _engine.setProperty('volume', 1.0)
    return _engine


def execute(text: str, rate: int = 175, volume: float = 1.0) -> str:
    try:
        engine = _get_engine()
        engine.setProperty('rate', rate)
        engine.setProperty('volume', max(0.0, min(1.0, volume)))
        engine.say(text)
        engine.runAndWait()
        return f"Reproducido por voz: {text[:100]}{'...' if len(text) > 100 else ''}"
    except Exception as e:
        return f"Error TTS: {e}"
