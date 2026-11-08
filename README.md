# Ollama GUI - Lubuntu Edition

GUI nativa para Lubuntu (LXQt / Qt6) que reemplaza el CLI amontonado.

## Features

### Interfaz
- **Sidebar** con modelos, nuevo chat, estado
- **Chat central** con burbujas, markdown real, scroll suave
- **Drag & Drop** de imágenes para vision
- Tema oscuro optimizado para Lubuntu

### Detección automática
- 🧠 **Think**: Detecta `<think>` de deepseek-r1/qwen3, muestra bloque colapsable con spinner
- 🔧 **Tools**: Auto-detecta cuando necesita web search, clima, hora, etc.
- 👁 **Vision**: Si arrastras imagen y usas llava/gemma3, la envía a Ollama

### Sistema de Plugins
Todo está en `tools/`:
- `web_search.py` - DuckDuckGo sin API key
- `weather_tool.py` - Clima via wttr.in
- `time_tool.py` - Fecha/hora
- `calculator_tool.py` - Calculadora segura
- `file_reader_tool.py` - Lee archivos locales
- `system_tool.py` - Info del sistema Lubuntu

**Añadir nueva función:**
1. Click en "＋ Crear Nuevo Tool" en la sidebar
2. O copia `tools/_template_new_tool.py` a `tools/mi_tool.py`
3. Edita `TOOL_DEFINITION` y `execute()`
4. Reinicia app - se auto-detecta

### Instalación Lubuntu

```bash
# Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
ollama pull llama3.1
ollama pull llava:7b  # para vision
ollama pull deepseek-r1:7b  # para think

# App
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

### Compilar ejecutable

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

### Ideas para añadir funciones (te dejo lista)

- `email_tool.py` - leer Gmail via API
- `calendar_tool.py` - ver calendario
- `youtube_tool.py` - buscar transcripts de YouTube
- `code_runner.py` - ejecutar Python y devolver output
- `rag_tool.py` - buscar en PDFs locales con embeddings
- `tts_tool.py` - texto a voz con Piper (offline para Lubuntu)
- `stt_tool.py` - voz a texto con Whisper.cpp
- `home_assistant_tool.py` - controlar luces IoT
- `git_tool.py` - estado de repos git
- `docker_tool.py` - listar contenedores

Dime cuál quieres y te la implemento.
