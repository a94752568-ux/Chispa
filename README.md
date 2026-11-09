# Ollama GUI - Lubuntu Edition

GUI nativa para Lubuntu (LXQt / Qt6) que consume Ollama para ejecutar modelos de lenguaje localmente. Incluye sistema de plugins, detección de pensamiento ("think"), visión (drag & drop de imágenes), búsqueda web, TTS neuronal (piper-tts), STT (dictado por voz), memoria persistente y agente de escritorio con gate de autorización estructural.

## Arquitectura actual (Rama B)

### Pre-router por embeddings (Rama B - Fase 1)

En lugar de enviar los 25 schemas de tools en cada request (≈3,200 tokens fijos), el pre-router clasifica el mensaje del usuario con `nomic-embed-text` en 4 categorías operativas y envía solo los schemas relevantes + herramientas básicas:

- **Datos**: búsqueda en RAG, notas, archivos, web
- **Sistema**: git, contenedores, tiempo, monitor, calendario
- **OSINT**: correo, usuario, subdominios, cabeceras, reconocimiento
- **Análisis**: OCR, sentimiento, EXIF, metadatos

Resultado: ~600-1,600 tokens por request en vez de ~3,200 (reducción del 50-80%).

### Agente de escritorio con autorización estructural

El orquestador (`agent_orchestrator.py`) ejecuta planes JSON del modelo paso a paso. Las herramientas de **lectura** se ejecutan solas; las de **mutación** se pausan y requieren autorización explícita en la GUI antes de escribir en disco. El modelo no puede saltarse el gate ni por alucinación ni por prompt injection.

## Features

### Interfaz
- Sidebar con modelos, nuevo chat, estado
- Chat central con burbujas, markdown real, scroll suave
- Drag & Drop de imágenes para vision
- Tema oscuro optimizado para Lubuntu
- Memoria persistente del chat en `~/.local/share/OllamaChat-GUI/chat_history.json`

### Detección automática
- 🧠 **Think**: Detecta `think` de deepseek-r1/qwen3, muestra bloque colapsable con spinner (desactivado por defecto por latencia)
- 🔧 **Tools**: Auto-detecta cuando necesita web search, clima, hora, etc. (vía pre-router por embeddings)
- 👁 **Vision**: Si arrastras imagen y usas llava/gemma3, la envía a Ollama

### TTS (texto a voz)
- **piper-tts** con modelo neuronal `es_MX-claude-high` bajo `~/.local/share/piper/`
- Botón 🔊 en cada respuesta para leer en voz alta
- Fallback gracioso si falta piper-tts o el modelo de voz

### STT (dictado por voz)
- `speech_recognition` con micrófono del sistema

### Sistema de Plugins (lectura)
Todo está en `tools/`:
- `web_search.py` - DuckDuckGo sin API key
- `weather_tool.py` - Clima via wttr.in
- `time_tool.py` - Fecha/hora
- `calculator_tool.py` - Calculadora segura (parser AST, sin eval)
- `file_reader_tool.py` - Lee archivos locales (protegido contra path traversal)
- `system_tool.py` - Info del sistema Lubuntu
- `system_monitor.py` - Monitor de RAM/CPU/disco
- `calendar_tool.py` - Calendario
- `rag_tool.py` - Búsqueda en RAG
- `notes_tool.py` - Notas
- `ocr_tool.py` - OCR de imágenes
- `sentiment_tool.py` - Análisis de sentimiento
- `metadata_tool.py` - Metadatos EXIF
- `stt_tool.py` - Voz a texto
- `containers_tool.py` - Contenedores
- `git_tool.py` - Estado git

### Herramientas de escritura (mutación - requieren autorización)
- `desktop_writer.py` - Guarda/crea archivos en `/home/aegis2` (blacklist: `.ssh`, `.gnupg`, `venv`, `node_modules`, etc.)
- `organize_files.py` - Organiza carpeta por tipo de archivo (Imágenes, Documentos, Audio, Video, Código…)

## Instalación Lubuntu

```bash
# Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
ollama pull llama3.1        # modelo por defecto (rápido)
ollama pull qwen3.5:4b      # opcional, más lento
ollama pull llava:7b        # para vision
ollama pull deepseek-r1:7b  # para think
ollama pull nomic-embed-text # para pre-router de tools

# TTS neuronal (opcional, para voz en español)
pip install piper-tts
mkdir -p ~/.local/share/piper
python -m piper.download_voices es_MX-claude-high --data-dir ~/.local/share/piper

# App
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

### Variables de entorno opcionales
- `OSINT_API_KEY_HIBP` - Clave de HaveIBeenPwned para `check_exposure`
- `WRITER_ROOT` - Raíz para `write_desktop` (default: `$HOME`)
- `ORGANIZE_ROOT` - Raíz para `organize_files` (default: `$HOME`)

## Añadir nueva función (plugin de lectura)

1. Click en "＋ Crear Nuevo Tool" en la sidebar
2. O copia `tools/template_new_tool.py` a `tools/mi_tool.py`
3. Edita `TOOL_DEFINITION` y `execute()`
4. Reinicia app - se auto-detecta

## Añadir herramienta de escritura (mutación)

1. Crea la tool en `tools/` con `TOOL_DEFINITION` y `execute()`
2. **Registra el nombre en `MUTACIONES`** de `tools/agent_orchestrator.py` o el orquestador la tratará como lectura y la ejecutará sin pedir permiso
3. El orquestador aplicará `dry_run=true` para preview y pausará esperando autorización en la GUI

## Compilar ejecutable

```bash
chmod +x build.sh
./build.sh
./dist/OllamaChat-GUI
```

Instalar en menú:
```bash
sudo mv dist/OllamaChat-GUI /usr/local/bin/
cp ollama-chat.desktop ~/.local/share/applications/
```

## Seguridad

- El gate de autorización es **estructural**: el orquestador clasifica cada paso como lectura o mutación y pausa ante cualquier mutación hasta que el usuario autorice
- `write_desktop` y `organize_files` tienen blacklist dura de rutas peligrosas (`.ssh`, `.gnupg`, `venv`, etc.) aunque estén dentro de la raíz permitida
- El modelo (4B) solo propone planes JSON; nunca escribe archivos directamente
