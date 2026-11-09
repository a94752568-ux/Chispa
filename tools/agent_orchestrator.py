#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agent_orchestrator.py — Capataz determinista. Ejecuta el plan JSON del 4B paso a paso.

Regla de oro: las tools de LECTURA se ejecutan solas; las de MUTACIÓN se PAUSAN
hasta que el usuario autorice (señal `necesita_aprobacion`). El 4B no puede
saltarse el gate ni por alucinación ni por prompt injection.

Integración GUI (PySide6): conecta la señal `necesita_aprobacion` a un QDialog con
el preview del paso y botones [Autorizar / Cancelar]; al autorizar llama `resume(True)`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

# Fuente única de verdad: tools/__init__.py define MUTACIONES.
# El fallback cubre contextos sin paquete (ejecución directa del archivo / PyInstaller).
try:
    from tools import MUTACIONES
except ImportError:
    MUTACIONES = {"write_desktop", "organize_files", "db_writer", "move_file"}


class Orchestrator(QObject):
    paso_completado = Signal(int, str, str)        # idx, tool, resultado
    necesita_aprobacion = Signal(int, dict, str)   # idx, paso, preview
    terminado = Signal(str)                        # informe final
    error = Signal(int, str)                       # idx, motivo

    def __init__(self, tools_map: dict[str, Any]):
        """tools_map: {nombre_tool: callable_execute} cargado desde tools/."""
        super().__init__()
        self.tools = tools_map
        self._resultados: list[str] = []
        self._plan: list[dict] = []
        self._idx = 0
        self._pendiente: dict | None = None

    # ---------- entrada: el plan JSON del modelo ----------
    def ejecutar(self, plan_json: str | dict) -> None:
        try:
            plan = json.loads(plan_json) if isinstance(plan_json, str) else plan_json
        except json.JSONDecodeError as e:
            self.terminado.emit(f"🚫 Plan inválido (JSON): {e}")
            return
        if not isinstance(plan, (dict, list)):
            self.terminado.emit(f"🚫 Plan inválido: se esperaba objeto o lista, llegó {type(plan).__name__}.")
            return
        pasos = (plan.get("pasos") or plan) if isinstance(plan, dict) else plan
        if not isinstance(pasos, list) or not pasos:
            self.terminado.emit("🚫 El plan no contiene pasos ejecutables.")
            return
        self._plan, self._resultados, self._idx = pasos, [], 0
        self._avanzar()

    # ---------- motor ----------
    def _sustituye(self, args: dict) -> dict:
        """Reemplaza {paso_N} / {resumen_del_paso_N} por el resultado real del paso N-1."""
        out: dict = {}
        for k, v in args.items():
            if isinstance(v, str):
                for m in re.finditer(r"\{(?:resumen_del_)?paso_(\d+)\}", v):
                    n = int(m.group(1)) - 1
                    if 0 <= n < len(self._resultados):
                        v = v.replace(m.group(0), self._resultados[n])
                out[k] = v
            else:
                out[k] = v
        return out

    def _avanzar(self) -> None:
        while self._idx < len(self._plan):
            paso = self._plan[self._idx]
            if not isinstance(paso, dict):
                self.error.emit(self._idx, f"Paso inválido: se esperaba un objeto, llegó {type(paso).__name__}")
                return
            tool = paso.get("tool")
            raw_args = paso.get("args", {}) or {}
            if not isinstance(raw_args, dict):
                self.error.emit(self._idx, f"Paso {tool}: 'args' debe ser un objeto, llegó {type(raw_args).__name__}")
                return
            args = self._sustituye(raw_args)
            if tool in MUTACIONES:
                preview = self._preview(tool, args)
                self.necesita_aprobacion.emit(self._idx, paso, preview)
                return  # PAUSA: espera resume()
            try:
                res = self.tools[tool](**args)
            except KeyError:
                self.error.emit(self._idx, f"Tool desconocida: {tool}")
                return
            except Exception as e:
                self.error.emit(self._idx, f"{tool} falló: {type(e).__name__}: {e}")
                return
            self._resultados.append(res if isinstance(res, str) else str(res))
            self.paso_completado.emit(self._idx, tool, res if isinstance(res, str) else str(res))
            self._idx += 1
        self._fin()

    def _preview(self, tool: str, args: dict) -> str:
        """Ejecuta la tool en modo dry_run para mostrar QUÉ haría, sin mutar."""
        try:
            a = dict(args)
            a["dry_run"] = True
            return self.tools[tool](**a)
        except Exception as e:
            return f"(no se pudo generar preview: {e})"

    # ---------- gate de autorización ----------
    def resume(self, autorizado: bool) -> None:
        # Determinar el paso actual (pendiente o el que toca por índice)
        if self._pendiente is not None:
            paso = self._pendiente
        elif self._idx < len(self._plan):
            paso = self._plan[self._idx]
        else:
            paso = None

        if paso is not None and isinstance(paso, dict) and paso.get("tool") in MUTACIONES:
            self._pendiente = paso

        if not autorizado:
            self._resultados.append("⏹ Paso cancelado por el usuario.")
            self._pendiente = None
            self._idx += 1
            self._avanzar()
            return

        paso = self._pendiente or (self._plan[self._idx] if self._idx < len(self._plan) else None)
        if paso is None:
            self._fin()
            return
        if not isinstance(paso, dict):
            self.error.emit(self._idx, f"Paso inválido: se esperaba un objeto, llegó {type(paso).__name__}")
            return

        tool = paso.get("tool")
        raw_args = paso.get("args", {}) or {}
        if not isinstance(raw_args, dict):
            self.error.emit(self._idx, f"Paso {tool}: 'args' debe ser un objeto, llegó {type(raw_args).__name__}")
            return
        args = self._sustituye(raw_args)
        args["dry_run"] = False  # el orquestador ya validó: escribe de verdad
        try:
            res = self.tools[tool](**args)
        except Exception as e:
            self.error.emit(self._idx, f"{tool} falló al ejecutar: {e}")
            return
        self._resultados.append(res if isinstance(res, str) else str(res))
        self.paso_completado.emit(self._idx, tool, res if isinstance(res, str) else str(res))
        self._pendiente = None
        self._idx += 1
        self._avanzar()

    def _fin(self) -> None:
        informe = "\n\n".join(
            f"[{i + 1}] {p.get('tool')}\n{r}"
            for i, (p, r) in enumerate(zip(self._plan, self._resultados))
        )
        self.terminado.emit(f"✅ Plan completado ({len(self._resultados)} pasos):\n\n{informe}")
