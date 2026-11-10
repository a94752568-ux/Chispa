#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""worker.py — OllamaWorker: QThread que dialoga con Ollama.

FASE 1: tool loop con think=False. FASE 2: respuesta final streameada.
Fuerza dry_run=True en las tools de MUTACIONES: el modelo no puede
escribir en disco sin pasar por el orquestador y su gate de autorización.

Optimización de latencia: si FASE 1 termina SIN tool calls y el modelo ya
redactó la respuesta, se reutiliza tal cual (antes se descartaba y FASE 2
la regeneraba desde cero: doble generación completa por turno en CPU).
FASE 2 solo corre si hay thinking que streamear o si FASE 1 llegó vacía.

FASE 1 además ve solo contexto reciente (system + últimos N mensajes):
el prefill del historial completo es el costo dominante en CPU y rara vez
hace falta contexto antiguo para decidir tool calls. FASE 2 sí ve todo.
"""
import json
import re
from typing import Dict, List

from PySide6.QtCore import QThread, Signal

try:
    import ollama
except Exception:
    ollama = None

# Gate de mutaciones: fuente única de verdad en tools/__init__.py
# (fallback para contextos sin paquete, p. ej. ejecución directa).
try:
    from tools import MUTACIONES
except ImportError:
    MUTACIONES = {"write_desktop", "organize_files", "db_writer", "move_file"}

# Bloques legacy de thinking: el cierre puede llegar como "</thinking>>"
# o como "</thinking>" (un solo '>'); tolerar ambos para que el stream no
# se quede colgado esperando un cierre que nunca llega.
_THINK_CLOSE_RE = re.compile(r"</thinking>>?")
_THINK_BLOCK_RE = re.compile(r"<<thinking>>(.*?)</thinking>>?", re.DOTALL)

# num_ctx explícito: si el prompt supera el contexto default de Ollama, la
# truncación es SILENTE y desde el principio — lo primero en caer es el
# system prompt. 8192 cubre historial completo + tools sin agotar la RAM
# del i3 con modelos ≤8B.
NUM_CTX = 8192

# Mensajes recientes (además de los system) que ve FASE 1 para decidir tools.
FASE1_HISTORY_LIMIT = 12

# ================= WORKER =================
class OllamaWorker(QThread):
    chunk_received = Signal(str)  # delta answer
    thinking_chunk = Signal(str)  # thinking delta
    tool_call_detected = Signal(str, dict)  # name, args
    tool_result_ready = Signal(str, str)  # name, result
    thinking_started = Signal()
    thinking_finished = Signal(str)
    final_answer = Signal(str, str)  # answer, thinking
    error_occurred = Signal(str)
    status_update = Signal(str)

    def __init__(self, model: str, history: List[Dict], tools_def: List[Dict], executors: Dict, enable_tools: bool = True, enable_think: bool = True):
        super().__init__()
        self.model = model
        self.history = history.copy()
        self.tools_def = tools_def if enable_tools else []
        self.executors = executors
        self.enable_tools = enable_tools
        self.enable_think = enable_think
        self._stop = False

    def stop(self):
        self._stop = True

    def _fase1_messages(self, tool_convo: List[Dict]) -> List[Dict]:
        """FASE 1 solo decide tool calls: le basta el contexto reciente.

        Conserva TODOS los system prompts + los últimos FASE1_HISTORY_LIMIT
        mensajes + la conversación de tools de este turno. FASE 2 ve el
        historial completo.
        """
        system = [m for m in self.history if m.get("role") == "system"]
        resto = [m for m in self.history if m.get("role") != "system"]
        return system + resto[-FASE1_HISTORY_LIMIT:] + tool_convo

    def run(self):
        if ollama is None:
            self.error_occurred.emit("ollama no instalado. pip install ollama")
            return

        client = ollama.Client()
        try:
            # FASE 1: Tools loop (hasta 3 iteraciones)
            # tool_convo: mensajes assistant+tool de este turno; se suma al
            # historial recortado de FASE 1 y al completo de FASE 2.
            tool_convo: List[Dict] = []
            tool_iterations = 0
            last_tool_result = ""

            while self.enable_tools and tool_iterations < 3 and not self._stop:
                self.status_update.emit(f"Analizando si necesita herramientas... (iter {tool_iterations+1})")
                fase1_messages = self._fase1_messages(tool_convo)
                try:
                    # FASE 1 SIN reasoning: pensar no ayuda a decidir tool calls
                    # y multiplica la latencia de cada iteración (generaciones
                    # completas sin streaming). El thinking queda solo para la
                    # respuesta final streameada (FASE 2).
                    resp = client.chat(model=self.model, messages=fase1_messages, tools=self.tools_def, stream=False, think=False, options={"num_ctx": NUM_CTX})
                except Exception as e:
                    # Ollama devolvió 500 (ej: tool calls malformados del modelo).
                    # Reintentar SIN tools para que el usuario obtenga respuesta.
                    self.status_update.emit(f"Herramientas no disponibles, respondiendo directo: {str(e)[:60]}")
                    try:
                        resp = client.chat(model=self.model, messages=self.history + tool_convo, tools=[], stream=False, think=False, options={"num_ctx": NUM_CTX})
                        msg = resp.get('message', {})
                        final_ans = msg.get('content', '')
                        self.final_answer.emit(final_ans, msg.get('thinking', ''))
                    except Exception as e2:
                        self.error_occurred.emit(f"Ollama error: {e2}")
                    return
                msg = resp.get('message', {})
                tool_calls = msg.get('tool_calls', [])

                if tool_calls:
                    # El mensaje assistant con tool_calls va UNA vez por
                    # iteración: antes se duplicaba con cada tool call del lote.
                    tool_convo.append(msg)
                    for tc in tool_calls:
                        if self._stop:
                            break
                        func = tc.get('function', {})
                        name = func.get('name','')
                        args = func.get('arguments', {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {"query": args}

                        self.tool_call_detected.emit(name, args)

                        executor = self.executors.get(name)
                        if executor:
                            try:
                                # Gate de mutación: en tool calls directos del chat,
                                # las tools de escritura NUNCA se ejecutan de verdad.
                                # Solo el orquestador, con autorización explícita del
                                # usuario, puede mandar dry_run=False.
                                if name in MUTACIONES:
                                    args = dict(args)
                                    args["dry_run"] = True
                                result = executor(**args) if args else executor()
                                if name in MUTACIONES:
                                    result += (
                                        "\n\n⚠️ SIMULACIÓN (dry_run): NO se escribió nada en disco. "
                                        "No vuelvas a invocar esta herramienta en este turno. Explica al "
                                        "usuario que el cambio es simulado y que, si quiere aplicarlo de "
                                        "verdad, responde con un plan JSON con la clave \"pasos\" (ej: "
                                        '{"pasos": [{"tool": "write_desktop", "args": {...}}]}): el '
                                        "orquestador pedirá su autorización antes de ejecutarlo."
                                    )
                            except Exception as e:
                                result = f"Error ejecutando {name}: {e}"
                        else:
                            # Tool inexistente o filtrada por el pre-router: decirle
                            # al modelo qué SÍ tiene disponible en este turno, para
                            # que no queme iteraciones reintentando lo imposible.
                            disponibles = ", ".join(sorted(self.executors.keys())) or "ninguna"
                            result = (
                                f"Tool {name} no encontrada. No existe o no está "
                                f"disponible en este turno. Disponibles: {disponibles}. "
                                "Responde al usuario sin esta tool."
                            )

                        self.tool_result_ready.emit(name, result)
                        tool_convo.append({"role": "tool", "content": str(result)})
                        last_tool_result = str(result)

                    tool_iterations += 1
                    continue
                else:
                    # Sin tool calls: si FASE 1 ya redactó la respuesta, reutilizarla.
                    # Antes se descartaba y FASE 2 la regeneraba completa: doble
                    # generación por turno (el mayor cuello de botella en CPU).
                    # FASE 2 solo si hay thinking que streamear (FASE 1 corre con
                    # think=False y no lo produce) o si la respuesta llegó vacía.
                    direct_answer = (msg.get('content') or '').strip()
                    if direct_answer and not self.enable_think:
                        self.status_update.emit("Respuesta lista")
                        self.final_answer.emit(direct_answer, "")
                        return
                    break

            if self._stop:
                # Detenido durante la fase de tools: no abrir un stream nuevo.
                self.final_answer.emit("", "")
                return

            # FASE 2: Streaming final con deteccion de think
            self.status_update.emit("Generando respuesta...")
            raw_accum = ""
            thinking_content = ""
            answer_content = ""
            has_think = False
            think_closed = False

            # FASE 2 ve el historial COMPLETO + la conversación de tools
            stream = client.chat(model=self.model, messages=self.history + tool_convo, stream=True, think=self.enable_think, options={"num_ctx": NUM_CTX})

            for chunk in stream:
                if self._stop:
                    break
                if chunk.get('done'):
                    break

                thinking_delta = chunk.get('message', {}).get('thinking', '')
                if thinking_delta and not has_think:
                    has_think = True
                    self.thinking_started.emit()
                if thinking_delta and has_think and not think_closed:
                    self.thinking_chunk.emit(thinking_delta[:2000])
                    continue

                delta = chunk.get('message', {}).get('content', '')
                if not delta:
                    continue

                raw_accum += delta

                if "<<thinking>>" in raw_accum and not has_think:
                    has_think = True
                    self.thinking_started.emit()

                if has_think and not think_closed:
                    # Aceptar "</thinking>>" y "</thinking>": varios modelos
                    # cierran con un solo '>' y el stream quedaba colgado.
                    if _THINK_CLOSE_RE.search(raw_accum):
                        think_closed = True
                        m = _THINK_BLOCK_RE.search(raw_accum)
                        if m:
                            thinking_content = m.group(1).strip()
                            answer_content = _THINK_BLOCK_RE.sub("", raw_accum)
                            self.thinking_finished.emit(thinking_content)
                            if answer_content.strip():
                                self.chunk_received.emit(answer_content)
                        else:
                            parts = _THINK_CLOSE_RE.split(raw_accum, 1)
                            thinking_content = parts[0].replace("<<thinking>>", "").strip()
                            self.thinking_finished.emit(thinking_content)
                            answer_content = parts[1] if len(parts) > 1 else ""
                            if answer_content.strip():
                                self.chunk_received.emit(answer_content)

                        # IMPORTANTE: después de procesar thinking y emitir answer_content,
                        # saltar la emisión posterior de delta para evitar duplicación
                        continue
                    else:
                        think_part = raw_accum.split("<<thinking>>")[-1]
                        self.thinking_chunk.emit(think_part[:2000])
                else:
                    if not has_think:
                        answer_content += delta
                    # Emitir el delta también tras un bloque legacy ya cerrado:
                    # antes todo lo streameado después del cierre se perdía y la
                    # respuesta solo aparecía completa al final.
                    self.chunk_received.emit(delta)

            if has_think:
                # Mismo cierre tolerante del streaming: con "</thinking>" (un solo
                # '>') los regex anteriores no matcheaban y la respuesta final
                # incluía el bloque de thinking en crudo.
                m = re.search(r"<<thinking>>.*?</thinking>>?(.*)", raw_accum, re.DOTALL)
                final_ans = m.group(1).strip() if m else _THINK_BLOCK_RE.sub("", raw_accum).strip()
                if not final_ans:
                    final_ans = answer_content.strip()
            else:
                final_ans = raw_accum.strip()

            if not final_ans and last_tool_result:
                final_ans = last_tool_result

            self.final_answer.emit(final_ans, thinking_content)

        except Exception as e:
            self.error_occurred.emit(str(e))
