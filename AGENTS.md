# AGENTS.md - Ollama GUI Lubuntu Edition

## Descripción del proyecto

GUI nativa para Lubuntu (LXQt / Qt6) que consume Ollama para ejecutar modelos de lenguaje localmente. Incluye sistema de plugins, detección de pensamiento ("think"), visión (drag & drop de imágenes), búsqueda web, TTS (texto a voz) y STT (dictado por voz).

## Estructura del proyecto

```
.
├── main.py                 # Aplicación principal (PySide6)
├── init.py                 # Carga de tools (fallback / compatibilidad)
├── README.md               # Documentación de usuario
├── requirements.txt        # Dependencias Python
├── build.sh                # Script de compilación con PyInstaller
├── OllamaChat-GUI.spec     # Especificación de PyInstaller
├── tools/                  # Plugins de herramientas
│   ├── __init__.py         # load_tools() y discovery
│   ├── search.py           # web_search (DuckDuckGo)
│   ├── weather_tool.py     # get_weather (wttr.in)
│   ├── time_tool.py        # get_current_time
│   ├── calculator_tool.py  # calculator (parser AST seguro)
│   ├── file_reader_tool.py # read_file (con protección contra path traversal)
│   ├── system_tool.py      # system_info (psutil)
│   ├── tts_tool.py         # speak (pyttsx3)
│   ├── stt_tool.py         # listen (speech_recognition)
│   └── template_new_tool.py # Plantilla para crear nuevos tools
├── venv/                   # Entorno virtual (no versionar)
├── build/                  # Artefactos de PyInstaller
├── dist/                   # Ejecutable compilado
└── __pycache__/            # Cache de Python (no versionar)
```

## Cómo ejecutar (desarrollo)

```bash
# 1. Crear entorno virtual
python3 -m venv venv
source venv/bin/activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Iniciar Ollama (terminal separada)
ollama serve &
ollama pull llama3.1

# 4. Ejecutar la app
python main.py
```

## Cómo compilar ejecutable

```bash
chmod +x build.sh
./build.sh
# Resultado: ./dist/OllamaChat-GUI
```

## Arquitectura de herramientas (tools)

Cada tool es un archivo `.py` en `tools/` con dos elementos obligatorios:
- `TOOL_DEFINITION`: diccionario con el esquema de función para Ollama
- `execute(**args)`: función que implementa la lógica

Ejemplo mínimo:
```python
TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "mi_tool",
        "description": "Descripción de la herramienta",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
}

def execute() -> str:
    return "Resultado del tool"
```

El sistema las detecta automáticamente al reiniciar la app. No es necesario registrar manualmente.

## Herramientas disponibles

| Tool | Nombre en Ollama | Descripción |
|------|-----------------|-------------|
| `search.py` | `web_search` | Búsqueda en internet (DuckDuckGo) |
| `weather_tool.py` | `get_weather` | Clima actual (wttr.in) |
| `time_tool.py` | `get_current_time` | Fecha y hora local y UTC |
| `calculator_tool.py` | `calculator` | Expresiones matemáticas (parser AST) |
| `file_reader_tool.py` | `read_file` | Lectura de archivos dentro del proyecto |
| `system_tool.py` | `system_info` | Info del sistema Lubuntu |
| `tts_tool.py` | `speak` | Texto a voz (pyttsx3) |
| `stt_tool.py` | `listen` | Voz a texto (speech_recognition) |

## Notas de seguridad

- `calculator_tool.py`: usa parser `ast`, **no usa `eval()`**
- `file_reader_tool.py`: restringe lectura a dentro del directorio del proyecto (bloquea `../`)
- `stt_tool.py`: requiere `portaudio19-dev` y `pyaudio` en el sistema

## Comandos útiles

```bash
# Ver tools cargados
python3 -c "from tools import load_tools; d, e = load_tools(); print(list(e.keys()))"

# Ejecutar tests rápidos de herramientas
python3 -c "from tools import load_tools; d, e = load_tools(); print(e['calculator'](expression='2+3*4'))"

# Verificar sintaxis
python3 -m py_compile main.py tools/*.py
```

## Variables de entorno relevantes

Ninguna requerida. Ollama se conecta a `localhost:11434` por defecto.

## Problemas conocidos

- STT requiere `portaudio19-dev` + `pyaudio` (da error claro si faltan)
- TTS usa `espeak` en Lubuntu (pyttsx3 lo detecta automáticamente)
- Ventana sin bordes (`FramelessWindowHint`): arrastrar desde la barra de título personalizada
