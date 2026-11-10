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
import sys
import tempfile
from pathlib import Path

VOICE_DIR = Path.home() / ".local" / "share" / "piper"
VOICE_MODEL = "es_MX-claude-high.onnx"
VOICE_PATH = VOICE_DIR / VOICE_MODEL

_DOWNLOAD_CMD = (
    "python -m piper.download_voices es_MX-claude-high "
    f"--data-dir {VOICE_DIR}"
)


def _piper_available() -> bool:
    try:
        import piper  # noqa: F401
        return True
    except Exception:
        return False


def health_check() -> str | None:
    """Chequeo rápido sin audio. Devuelve el problema legible o None si el TTS está listo."""
    if not _piper_available():
        return "piper-tts no está instalado.\n\nInstálalo con:\npip install piper-tts"
    if not VOICE_PATH.exists():
        return (
            "Falta el modelo de voz español:\n"
            f"{VOICE_PATH}\n\n"
            "Descárgalo con:\n"
            f"{_DOWNLOAD_CMD}\n\n"
            "O manualmente (el .onnx Y su .onnx.json) desde:\n"
            "https://huggingface.co/rhasspy/piper-voices — es/es_MX/claude/high"
        )
    return None


def _play_wav(wav_path: str) -> bool:
    """Reproduce el wav con el primer reproductor disponible que funcione.
    Solo regresa True si el reproductor terminó con exit code 0
    (antes: un paplay roto contaba como 'reproducido')."""
    players = (
        ["paplay", str(wav_path)],
        ["mpv", "--no-cache", "--no-terminal", str(wav_path)],
        ["ffplay", "-nodisp", "-autoexit", str(wav_path)],
        ["pw-cat", str(wav_path)],
    )
    for cmd in players:
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode == 0:
                return True
        except Exception:
            continue
    return False


def execute(text: str, rate: int = 175, volume: float = 1.0) -> str:
    problema = health_check()
    if problema:
        return f"TTS no disponible: {problema}"

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        try:
            # API Python de piper-tts (>= 1.2): síntesis a archivo wav
            from piper import PiperVoice
            voice = PiperVoice.load(str(VOICE_PATH))
            with open(wav_path, "wb") as wav_file:
                voice.synthesize_wav(text, wav_file)
        except Exception:
            # Fallback CLI: el MISMO intérprete que corre la GUI (venv incluido;
            # antes se llamaba 'python' del PATH y podía caer fuera del venv)
            result = subprocess.run(
                [sys.executable, "-m", "piper", "-m", str(VOICE_PATH), "-f", wav_path],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=120,
            )
            if result.returncode != 0:
                return f"Error TTS (piper CLI): {result.stderr.decode(errors='replace')[:300]}"

        if not _play_wav(wav_path):
            return (
                "Error TTS: ningún reproductor funcionó. Prueba:\n"
                "sudo apt install pulseaudio-utils  # instala paplay"
            )
        return f"Reproducido por voz: {text[:100]}{'...' if len(text) > 100 else ''}"
    except subprocess.TimeoutExpired:
        return "Error TTS: la síntesis tardó más de 120s (texto muy largo)"
    except Exception as e:
        return f"Error TTS: {e}"
    finally:
        try:
            os.unlink(wav_path)
        except Exception:
            pass
