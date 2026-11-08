TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "listen",
        "description": "Escucha audio del micrófono y lo convierte a texto (dictado por voz). Requiere micrófono y librerías de audio del sistema.",
        "parameters": {
            "type": "object",
            "properties": {
                "timeout": {"type": "integer", "description": "Tiempo máximo de espera en segundos (default 5)"},
                "phrase_timeout": {"type": "integer", "description": "Tiempo de silencio para finalizar la frase en segundos (default 3)"}
            },
            "required": []
        }
    }
}

_recognizer = None


def _get_recognizer():
    global _recognizer
    if _recognizer is None:
        import speech_recognition as sr
        _recognizer = sr.Recognizer()
    return _recognizer


def execute(timeout: int = 5, phrase_timeout: int = 3) -> str:
    try:
        import speech_recognition as sr
    except ImportError:
        return "Error STT: speech_recognition no instalado. Ejecuta: pip install speechrecognition"

    try:
        mic = sr.Microphone()
    except Exception as e:
        return (f"Error STT: no se pudo acceder al micrófono ({e}).\n"
                f"En Lubuntu instala: sudo apt install portaudio19-dev python3-pyaudio\n"
                f"Luego: pip install pyaudio")

    recognizer = _get_recognizer()

    try:
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_timeout)
        text = recognizer.recognize_google(audio, language="es-ES")
        return text
    except sr.WaitTimeoutError:
        return "Error STT: no se detectó voz en el tiempo esperado"
    except sr.UnknownValueError:
        return "Error STT: no se pudo entender el audio"
    except sr.RequestError as e:
        return f"Error STT: servicio de reconocimiento no disponible ({e})"
    except Exception as e:
        return f"Error STT: {e}"
