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
import threading
from pathlib import Path

VOICE_DIR = Path.home() / ".local" / "share" / "piper"
VOICE_MODEL = "es_MX-claude-high.onnx"
VOICE_PATH = VOICE_DIR / VOICE_MODEL

_DOWNLOAD_CMD = (
    "python -m piper.download_voices es_MX-claude-high "
    f"--data-dir {VOICE_DIR}"
)


def _find_voice() -> Path | None:
    """Localiza el modelo de voz sin suponer UNA sola ruta fija.
    piper1-gpl guarda las voces planas en --data-dir, pero si la descarga se
    corrió sin --data-dir los archivos aterrizan en ~/.cache/piper (default
    moderno) o en el directorio desde donde se lanzó el comando. Antes solo
    se miraba VOICE_PATH: la voz 'no existía' aunque sí estuviera descargada.
    Requiere el par .onnx + .onnx.json (la configuración va junto al modelo)."""
    if VOICE_PATH.exists():
        return VOICE_PATH
    bases = [VOICE_DIR, Path.home() / ".cache" / "piper", Path.cwd()]
    for base in bases:
        if not base.exists():
            continue
        for pat in ("es_MX*claude*.onnx", "es_MX*.onnx", "*.onnx"):
            try:
                for p in sorted(base.rglob(pat)):
                    if Path(str(p) + ".json").exists():
                        return p
            except Exception:
                continue
    return None


def _piper_available() -> bool:
    try:
        import piper  # noqa: F401
        return True
    except Exception:
        return False


# ---------------- Control de reproducción (botón de detener) ----------------
_proc_lock = threading.Lock()
_proc = None            # reproductor activo (Popen) o None
_STOP_EVENT = threading.Event()


def stop_speech():
    """Detiene la reproducción en curso matando al reproductor.
    Lo llama la GUI cuando el usuario vuelve a tocar el botón 🔊.
    Si aún se está sintetizando (CPU), el corte surte efecto al pasar a
    reproducir: la síntesis no se puede interrumpir a mitad sin cargarla
    en un subproceso aparte."""
    _STOP_EVENT.set()
    with _proc_lock:
        p = _proc
    if p is not None and p.poll() is None:
        try:
            p.terminate()
            try:
                p.wait(timeout=2)
            except Exception:
                p.kill()
        except Exception:
            pass


def health_check() -> str | None:
    """Chequeo rápido sin audio. Devuelve el problema legible o None si el TTS está listo."""
    if not _piper_available():
        return "piper-tts no está instalado.\n\nInstálalo con:\npip install piper-tts"
    voice = _find_voice()
    if voice is None:
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
    Usa Popen (no run): el proceso queda registrado en _proc para que
    stop_speech() pueda matarlo a mitad del audio. Solo regresa True si el
    reproductor terminó con exit code 0."""
    global _proc
    players = (
        ["paplay", str(wav_path)],
        ["mpv", "--no-cache", "--no-terminal", str(wav_path)],
        ["ffplay", "-nodisp", "-autoexit", str(wav_path)],
        ["pw-cat", str(wav_path)],
    )
    for cmd in players:
        if _STOP_EVENT.is_set():
            return False
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            continue
        with _proc_lock:
            _proc = proc
        try:
            returncode = proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            returncode = -1
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            returncode = -1
        finally:
            with _proc_lock:
                if _proc is proc:
                    _proc = None
        if _STOP_EVENT.is_set():
            return False
        if returncode == 0:
            return True
    return False


def execute(text: str, rate: int = 175, volume: float = 1.0) -> str:
    _STOP_EVENT.clear()
    problema = health_check()
    if problema:
        return f"TTS no disponible: {problema}"

    voice_path = _find_voice()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        try:
            # API Python de piper-tts (>= 1.2): síntesis a archivo wav
            from piper import PiperVoice
            voice = PiperVoice.load(str(voice_path))
            with open(wav_path, "wb") as wav_file:
                voice.synthesize_wav(text, wav_file)
        except Exception:
            # Fallback CLI: el MISMO intérprete que corre la GUI (venv incluido;
            # antes se llamaba 'python' del PATH y podía caer fuera del venv)
            result = subprocess.run(
                [sys.executable, "-m", "piper", "-m", str(voice_path), "-f", wav_path],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=120,
            )
            if result.returncode != 0:
                return f"Error TTS (piper CLI): {result.stderr.decode(errors='replace')[:300]}"

        if _STOP_EVENT.is_set():
            return "Lectura detenida por el usuario"
        if not _play_wav(wav_path):
            if _STOP_EVENT.is_set():
                return "Lectura detenida por el usuario"
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
