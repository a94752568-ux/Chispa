# AGENTS.md - Ollama GUI Lubuntu Edition

## Descripción del proyecto

GUI nativa (PySide6 / Qt6, ventana frameless con tema oscuro Fusion) que consume Ollama localmente en un laptop modesto (i3, 16 GB). Incluye:

- Tool use con ~30 plugins de herramientas y pre-router por embeddings (solo se envían las tools relevantes al modelo)
- Agente de escritorio determinista con **gate de mutaciones**: toda tool de escritura requiere autorización explícita del usuario
- Modo thinking (canal nativo de razonamiento) con cronómetro, visión (drag & drop de imágenes), TTS (piper-tts) y STT (dictado)
- Dedup de streaming por identidad de evento (proyecto E3) con flags de debug por variable de entorno
- Memoria persistente del historial (tope de 40 mensajes)

## Estructura del proyecto

```
.
├── main.py                     # MainWindow + main(): solo shell de la app
├── common.py                   # Constantes compartidas: flags dedup (E3), MD_CSS, trace()
├── memoria.py                  # Persistencia del historial (chat_history.json, tope 40)
├── worker.py                   # OllamaWorker (QThread): FASE 1 tool loop, FASE 2 streaming
├── widgets.py                  # ThinkingBlock, ToolBlock, MessageBubble, ChatContainer, TitleBar
├── init.py                     # Carga de tools (fallback / compatibilidad)
├── conftest.py                 # Hace visible la raíz del repo para pytest
├── tests/                      # test_e2_finish_answer, test_e3_dedup, test_router (requiere Ollama)
├── .github/workflows/ci.yml    # CI: py_compile de todos los .py + pytest headless (no bloqueante)
├── requirements.txt
├── build.sh                    # Compilación PyInstaller (incluye tools/ como data)
├── OllamaChat-GUI.spec
└── tools/                      # ~30 plugins + infraestructura
    ├── __init__.py             # load_tools(), MUTACIONES (fuente única de verdad)
    ├── pre_router.py           # Router por categorías con nomic-embed-text
    ├── agent_orchestrator.py   # Orquestador determinista (QThread) con gate de autorización
    ├── chat_fx.py              # fade_in, animate_height, Spinner, PensandoDots
    ├── template_new_tool.py     # Plantilla para crear nuevos tools
    └── ...                     # Tools de lectura, OSINT, escritorio, voz, etc.
```

## Arquitectura

- **main.py** ya no es un monolito: los módulos `common`, `memoria`, `worker` y `widgets` se importan estáticamente (PyInstaller los detecta solo).
- **worker.OllamaWorker** fuerza `dry_run=True` en las tools de MUTACIONES: el modelo no puede escribir en disco en un tool call directo del chat; la única vía de escritura es el plan JSON del orquestador con su diálogo de autorización.
- **worker.OllamaWorker reutiliza la respuesta de FASE 1**: si el modelo no invoca tools y ya redactó la respuesta, se emite directamente (antes se descartaba y FASE 2 la regeneraba completa: doble generación por turno, el mayor cuello de botella en CPU). FASE 2 queda solo para streaming con thinking o cuando FASE 1 llegó vacía. FASE 1 además ve solo contexto reciente (system + últimos 12 mensajes), se fija num_ctx=8192 en todas las llamadas (la truncación silenciosa de Ollama tira primero el system prompt) y el mensaje assistant con tool_calls se agrega una sola vez por iteración. El pre-router filtra tools también con thinking activado (FASE 1 corre con think=False).
- **El orquestador vive en su propio QThread**: las tools del plan no congelan la GUI.
- **MUTACIONES** se define SOLO en `tools/__init__.py`; si añades una tool de escritura, regístrala ahí o se ejecutará sin pedir permiso.

## Cómo ejecutar (desarrollo)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
ollama serve &
ollama pull llama3.1
python main.py
```

## Cómo compilar ejecutable

```bash
chmod +x build.sh && ./build.sh
# Resultado: ./dist/OllamaChat-GUI
```

## Arquitectura de herramientas (tools)

Cada tool es un `.py` en `tools/` con dos elementos obligatorios:

- `TOOL_DEFINITION`: esquema de función para Ollama
- `execute(**args)`: implementación

El sistema las detecta automáticamente al reiniciar la app (autodiscovery). No es necesario registrar manualmente, salvo las de **escritura**, que además deben añadirse a `MUTACIONES` en `tools/__init__.py`.

Si el modelo invoca una tool inexistente o filtrada por el pre-router, el resultado incluye la lista de tools disponibles en ese turno: el modelo no debe quemar iteraciones reintentando una tool imposible.

## Herramientas disponibles (~30)

| Categoría | Tools |
|-----------|-------|
| Básicas | `web_search` (DuckDuckGo), `get_weather` (wttr.in), `get_current_time`, `calculator` (parser AST), `read_file` (con contención de rutas), `system_info` |
| Voz | `speak` (TTS piper-tts es_MX-claude-high), `listen` (STT speech_recognition) |
| OSINT | email_breach, username, full_recon, ip_domain, tech_fingerprint, cert_transparency (todas con timeout) |
| Escritorio (**MUTACIONES**) | `write_desktop`, `organize_files` (dry_run + blacklist), `db_writer`, `move_file` |
| Otras | notas, RAG, calendario, git, contenedores, system_monitor |

Para listar las cargadas en vivo: `python3 -c "from tools import load_tools; d, e = load_tools(); print(sorted(e.keys()))"`

## Pruebas y CI

```bash
pytest tests/ --ignore=tests/test_router.py   # e2 (finishAnswer) + e3 (dedup)
QT_QPA_PLATFORM=offscreen pytest ...           # headless
```

- `tests/test_router.py` requiere Ollama local corriendo (12/12 casos).
- GitHub Actions corre en cada push a main: **py_compile** de todos los .py (bloqueante) y **pytest headless** (`continue-on-error` hasta estabilizarlo en el runner).
- CI falla en el paso de tests en el runner de GitHub: falla preexistente del entorno headless, NO del código (verificado comparando commits pre y post refactor). Localmente con display deberían pasar.

## Notas de seguridad

- `calculator`: parser `ast`, **no usa eval()**
- `read_file`: lectura restringida al directorio del proyecto (bloquea `../`)
- Gate de mutaciones: preview en dry_run antes de autorizar; el worker fuerza dry_run en tool calls directos
- `stt_tool` requiere `portaudio19-dev` + pyaudio

## Variables de entorno

| Variable | Efecto |
|----------|--------|
| `OLLAMA_GUI_DEDUP=0` | Desactiva el dedup de streaming (E3) |
| `OLLAMA_GUI_DEBUG_DEDUP=1` | Logs detallados del dedup |
| `OLLAMA_GUI_DEDUP_LOG=/ruta` | Escribe log del dedup a archivo |

## Flujo de trabajo del repo

Commits directos a `main` con mensajes detallados en español. Si editas desde fuera (API/GUI web), recuerda hacer `git pull` en la laptop antes de seguir trabajando.
