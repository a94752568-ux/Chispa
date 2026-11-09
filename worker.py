#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""worker.py — OllamaWorker: QThread que dialoga con Ollama.

FASE 1: tool loop con think=False. FASE 2: respuesta final streameada.
Fuerza dry_run=True en las tools de MUTACIONES: el modelo no puede
escribir en disco sin pasar por el orquestador y su gate de autorización.
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

    def run(self):
        if ollama is None:
            self.error_occurred.emit("ollama no instalado. pip install ollama")
            return

        client = ollama.Client()
        try:
            # FASE 1: Tools loop (hasta 3 iteraciones)
            current_history = self.history.copy()
            tool_iterations = 0

            while self.enable_tools and tool_iterations < 3 and not self._stop:
                self.status_update.emit(f"Analizando si necesita herramientas... (iter {tool_iterations+1})")
                try:
                    # FASE 1 SIN reasoning: pensar no ayuda a decidir tool calls
                    # y multiplica la latencia de cada iteración (generaciones
                    # completas sin streaming). El thinking queda solo para la
                    # respuesta final streameada (FASE 2).
                    resp = client.chat(model=self.model, messages=current_history, tools=self.tools_def, stream=False, think=False)
                except Exception as e:
                    # Ollama devolvió 500 (ej: tool calls malformados del modelo).
                    # Reintentar SIN tools para que el usuario obtenga respuesta.
                    self.status_update.emit(f"Herramientas no disponibles, respondiendo directo: {str(e)[:60]}")
                    try:
                        resp = client.chat(model=self.model, messages=current_history, tools=[], stream=False, think=False)
                        msg = resp.get('message', {})
                        final_ans = msg.get('content', '')
                        self.final_answer.emit(final_ans, msg.get('thinking', ''))
                    except Exception as e2:
                        self.error_occurred.emit(f"Ollama error: {e2}")
                    return
                msg = resp.get('message', {})
                tool_calls = msg.get('tool_calls', [])

                if tool_calls:
                    for tc in tool_calls:
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
                            result = f"Tool {name} no encontrado"

                        self.tool_result_ready.emit(name, result)

                        current_history.append(msg)
                        current_history.append({"role": "tool", "content": str(result)})

                    tool_iterations += 1
                    continue
                else:
                    break

            # FASE 2: Streaming final con deteccion de think
            self.status_update.emit("Generando respuesta...")
            raw_accum = ""
            self._emitted_len = 0  # origen: solo emitimos lo nuevo desde la última emisión
            thinking_content = ""
            answer_content = ""
            has_think = False
            think_closed = False
            last_tool_result = ""

            for m in reversed(current_history):
                if m.get("role") == "tool":
                    last_tool_result = str(m.get("content", ""))
                    break

            stream = client.chat(model=self.model, messages=current_history, stream=True, think=self.enable_think)

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
                    if "</thinking>>" in raw_accum:
                        think_closed = True
                        m = re.search(r"<<thinking>>(.*?)</thinking>>", raw_accum, re.DOTALL)
                        if m:
                            thinking_content = m.group(1).strip()
                            answer_content = re.sub(r"<<thinking>>.*?</thinking>>", "", raw_accum, flags=re.DOTALL)
                            self.thinking_finished.emit(thinking_content)
                            if answer_content.strip():
                                self.chunk_received.emit(answer_content)
                        else:
                            parts = raw_accum.split("</thinking>>", 1)
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
                        self.chunk_received.emit(delta)
                        answer_content += delta

            if has_think:
                m = re.search(r"<<thinking>>.*?</thinking>>(.*)", raw_accum, re.DOTALL)
                final_ans = m.group(1).strip() if m else re.sub(r"<<thinking>>.*?</thinking>>", "", raw_accum, flags=re.DOTALL).strip()
                if not final_ans:
                    final_ans = answer_content.strip()
            else:
                final_ans = raw_accum.strip()

            if not final_ans and last_tool_result:
                final_ans = last_tool_result

            self.final_answer.emit(final_ans, thinking_content)

        except Exception as e:
            self.error_occurred.emit(str(e))

