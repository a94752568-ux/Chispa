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
import time
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

# Techo duro de resultados: num_ctx=8192 y un full_recon puede devolver
# 10KB+. Sin techo, el prompt trunca EN SILENCIO (lo primero en caer es el
# system prompt) y cada iteración de FASE 1 + FASE 2 paga el prefill extra
# (tool_convo viaja también a FASE 2). Se conserva el inicio (lo relevante)
# y un colín del final (las conclusiones suelen ir al final).
TOOL_RESULT_MAX = 3500   # techo total por resultado de tool
_TOOL_HEAD = 2600        # caracteres iniciales que se conservan
_TOOL_TAIL = 600         # colín final

# Política de uso de tools que viaja como system al final de FASE 1:
# profesionaliza la conducta del modelo (menos llamadas vacías, argumentos
# exactos, cierre claro tras obtener resultados).
TOOL_POLICY = (
    "Política de herramientas: invoca una herramienta SOLO si es imprescindible "
    "para responder (datos externos, cálculos, estado del sistema o archivos); "
    "en chateo casual no llames ninguna. Copia los nombres de los argumentos "
    "EXACTOS de la definición de la herramienta. Cuando tengas los resultados, "
    "responde al usuario directamente SIN más llamadas a herramientas. No "
    "repite una llamada idéntica en el mismo turno. "
    "SI UNA HERRAMIENTA FALLA o devuelve 'sin resultados': reintenta UNA vez "
    "con una consulta MÁS CORTA y simple (2-4 palabras clave, sin 'fecha "
    "actual' ni relleno); si vuelve a fallar, díselo claro al usuario y ofrece "
    "alternativas reales (ej. la mini-wiki offline). NUNCA inventes datos para "
    "tapar el fallo y NUNCA cambies de tema ni te presentes de nuevo: responde "
    "SIEMPRE a lo que el usuario pidió."
)


def _cap_result(result: str) -> str:
    """Recorta un resultado de tool a TOOL_RESULT_MAX conservando inicio y fin."""
    result = str(result)
    if len(result) <= TOOL_RESULT_MAX:
        return result
    aviso = (
        f"\n\n[… resultado truncado: {len(result)} caracteres en total; "
        f"se muestran los primeros {_TOOL_HEAD} y los últimos {_TOOL_TAIL} …]\n\n"
    )
    return result[:_TOOL_HEAD] + aviso + result[-_TOOL_TAIL:]

# ================= WORKER =================
class OllamaWorker(QThread):
    chunk_received = Signal(str)  # delta answer
    thinking_chunk = Signal(str)  # thinking delta
    tool_call_detected = Signal(str, dict)  # name, args
    tool_result_ready = Signal(str, str)  # name, result
    thinking_started = Signal()
    thinking_finished = Signal(str)
    final_answer = Signal(str, str)  # answer, thinking
    stats_ready = Signal(dict)  # telemetria del turno: tok/s, TTFT, tokens in/out
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
        self._call_cache: Dict = {}  # dedup de llamadas (name, args) -> resultado

    def stop(self):
        self._stop = True

    def _emitir_stats(self, data: Dict, tools: int = 0, ttft_wall=None):
        """Extrae las metricas REALES de Ollama (eval_count / durations, viajan
        en la respuesta final y en el ultimo chunk del stream) y las emite
        como dict para el panel de telemetria de la GUI."""
        try:
            ev = data.get('eval_count') or 0
            ev_d = (data.get('eval_duration') or 0) / 1e9
            pe = data.get('prompt_eval_count') or 0
            pe_d = (data.get('prompt_eval_duration') or 0) / 1e9
            stats = {
                "tok_out": int(ev),
                "tok_in": int(pe),
                "tps": round(ev / ev_d, 2) if ev_d > 0 else None,
                # TTFT medido en pared (incluye cola del server); fallback: prefill
                "ttft": round(ttft_wall, 2) if ttft_wall else (round(pe_d, 2) if pe_d > 0 else None),
                "total_s": round((data.get('total_duration') or 0) / 1e9, 2),
                "tools": int(tools),
            }
            self.stats_ready.emit(stats)
        except Exception:
            pass

    def _fase1_messages(self, tool_convo: List[Dict]) -> List[Dict]:
        """FASE 1 solo decide tool calls: le basta el contexto reciente.

        Conserva TODOS los system prompts + los últimos FASE1_HISTORY_LIMIT
        mensajes + la conversación de tools de este turno. FASE 2 ve el
        historial completo. La política de tools viaja AL FINAL: recency
        máxima justo antes de que el modelo decida la siguiente llamada.
        """
        system = [m for m in self.history if m.get("role") == "system"]
        resto = [m for m in self.history if m.get("role") != "system"]
        return (
            system + resto[-FASE1_HISTORY_LIMIT:] + tool_convo
            + [{"role": "system", "content": TOOL_POLICY}]
        )

    def _expected_params(self, name: str) -> str:
        """Firma esperada de una tool a partir de su definición: permite que
        el modelo corrija argumentos mal nombrados en la siguiente iteración
        (antes un TypeError genérico quemaba el turno sin orientación)."""
        for d in self.tools_def:
            fn = d.get("function", {})
            if fn.get("name") == name:
                params = fn.get("parameters", {})
                props = params.get("properties", {})
                req = set(params.get("required", []))
                if not props:
                    return "sin parámetros"
                return ", ".join(
                    f"{k} ({'requerido' if k in req else 'opcional'})" for k in props
                )
        return "desconocidos (tool no en las definiciones del turno)"

    def run(self):
        if ollama is None:
            self.error_occurred.emit("ollama no instalado. pip install ollama")
            return

        client = ollama.Client()
        self._call_cache = {}  # dedup de llamadas fresco por turno
        try:
            # FASE 1: Tools loop (hasta 3 iteraciones)
            # tool_convo: mensajes assistant+tool de este turno; se suma al
            # historial recortado de FASE 1 y al completo de FASE 2.
            tool_convo: List[Dict] = []
            tool_iterations = 0
            tools_usadas = 0
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

                        tools_usadas += 1
                        self.tool_call_detected.emit(name, args)

                        executor = self.executors.get(name)
                        # Dedup por turno: una llamada idéntica (misma tool,
                        # mismos args) NO se ejecuta dos veces — solo hay 3
                        # iteraciones y repetirlas las quemaba en vacío.
                        call_key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
                        if call_key in self._call_cache:
                            result = self._call_cache[call_key] + (
                                "\n\n⚠️ Ya obtuviste este mismo resultado en este turno "
                                "(misma herramienta y argumentos). NO repitas la llamada: "
                                "úsalo y responde al usuario."
                            )
                        elif executor:
                            try:
                                # Gate de mutación: en tool calls directos del chat,
                                # las tools de escritura NUNCA se ejecutan de verdad.
                                # Solo el orquestador, con autorización explícita del
                                # usuario, puede mandar dry_run=False.
                                if name in MUTACIONES:
                                    args = dict(args)
                                    args["dry_run"] = True
                                result = executor(**args) if args else executor()
                                # Techo de resultado: protege num_ctx (un resultado
                                # de 10KB+ trunca el prompt en silencio) y el
                                # prefill de FASE 2 (que también recibe tool_convo).
                                result = _cap_result(result)
                                self._call_cache[call_key] = result
                                if name in MUTACIONES:
                                    result += (
                                        "\n\n⚠️ SIMULACIÓN (dry_run): NO se escribió nada en disco. "
                                        "No vuelvas a invocar esta herramienta en este turno. Explica al "
                                        "usuario que el cambio es simulado y que, si quiere aplicarlo de "
                                        "verdad, responde con un plan JSON con la clave \"pasos\" (ej: "
                                        '{"pasos": [{"tool": "write_desktop", "args": {...}}]}): el '
                                        "orquestador pedirá su autorización antes de ejecutarlo."
                                    )
                            except TypeError as e:
                                # Args mal nombrados: devolver la firma esperada
                                # para que el modelo se autocorrija en la
                                # siguiente iteración en vez de adivinar.
                                result = (
                                    f"Error de argumentos en {name}: {e}. "
                                    f"Parámetros esperados: {self._expected_params(name)}. "
                                    "Corrige los nombres de los argumentos copiándolos "
                                    "de la definición de la herramienta."
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
                        self._emitir_stats(resp, tools=tools_usadas)
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

            t_stream = time.monotonic()
            primer_token = None   # TTFT en pared
            datos_finales = None  # ultimo chunk (done=True): metricas de Ollama

            for chunk in stream:
                if self._stop:
                    break
                if chunk.get('done'):
                    datos_finales = chunk
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
                if primer_token is None:
                    primer_token = time.monotonic() - t_stream

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

            if datos_finales is not None or primer_token is not None:
                self._emitir_stats(datos_finales or {}, tools=tools_usadas, ttft_wall=primer_token)

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
