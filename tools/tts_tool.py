TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "speak",
        "description": "Convierte texto a voz neuronal y lo reproduce por altavoces. Usa piper-tts con modelo en español (es_MX-claude-high) bajo ~/.local/share/piper/. Requiere piper-tts instalado y el modelo descargado.",
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

import os
import subprocess
import tempfile
from pathlib import Path

VOICE_DIR = Path.home() / ".local" / "share" / "piper"
VOICE_MODEL = "es_MX-claude-high.onnx"
VOICE_PATH = VOICE_DIR / VOICE_MODEL


def _piper_available() -> bool:
    try:
        import piper  # noqa: F401
        return True
    except Exception:
        return False


def _play_wav(wav_path: str) -> bool:
    for cmd in (["paplay", wav_path], ["mpv", "--no-cache", "--no-terminal", wav_path],
                ["ffplay", "-nodisp", "-autoexit", wav_path], ["pw-cat", wav_path]):
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=30)
            return True
        except Exception:
            continue
    return False


def execute(text: str, rate: int = 175, volume: float = 1.0) -> str:
    if not VOICE_PATH.exists():
        return (
            "TTS no disponible: modelo de voz no encontrado en "
            f"{VOICE_PATH}. Ejecuta:\n"
            "python -m piper.download_voices es_MX-claude-high "
            f"--data-dir {VOICE_DIR}"
        )

    if not _piper_available():
        return "TTS no disponible: piper-tts no está instalado (pip install piper-tts)."

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        import piper
        from piper.audio import AudioPlayer

        voice = piper.Voice.load(str(VOICE_PATH))
        audio = voice.synthesize(text)
        AudioPlayer(audio, sample_rate=voice.config.sample_rate).play()
        return f"Reproducido por voz: {text[:100]}{'...' if len(text) > 100 else ''}"
    except Exception:
        try:
            result = subprocess.run(
                ["python", "-m", "piper", "-m", str(VOICE_PATH), "-f", wav_path],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=60,
            )
            if result.returncode != 0:
                return f"Error TTS (piper): {result.stderr.decode(errors='replace')[:300]}"
            _play_wav(wav_path)
            return f"Reproducido por voz: {text[:100]}{'...' if len(text) > 100 else ''}"
        except Exception as e:
            return f"Error TTS: {e}"
    finally:
        try:
            os.unlink(wav_path)
        except Exception:
            pass
