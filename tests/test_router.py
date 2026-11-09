#!/usr/bin/env python3
"""test_router.py — verifica que el pre-router incluye las tools correctas."""
import json
import sys
from pathlib import Path

# tests/ está un nivel debajo de la raíz: subir para encontrar tools/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.pre_router import ToolRouter

# (mensaje, substrings que DEBEN aparecer en las tools enviadas, substrings PROHIBIDOS)
CASOS = [
    ("¿qué tecnologías usa github.com?",              ["fingerprint"], ["system_monitor"]),
    ("lista los subdominios de mozilla.org",          ["subdomain"],  ["rag"]),
    ("¿está comprometido el mail pepe@gmail.com?",    ["exposure"],   ["system_monitor"]),
    ("¿qué anoté ayer sobre el router?",              ["rag", "note"], ["recon_", "subdomain"]),
    ("recuerda que cambié la clave del wifi",         ["note", "rag"], ["recon_"]),
    ("busca en mi manual de ubuntu cómo montar nfs",  ["rag"],        ["subdomain"]),
    ("¿cómo está mi RAM y cuánto disco queda?",       ["system_monitor"], ["rag", "ocr"]),
    ("¿qué cambios tengo sin commitear?",             ["git"],        []),
    ("extrae el texto de este PDF escaneado",         ["ocr"],        ["rag"]),
    ("¿dónde tomé esta foto?",                        ["metadata"],   []),
    ("investiga protonmail.com y dime cómo está el disco", ["recon", "system_monitor"], []),
    ("hola, ¿qué puedes hacer?",                      [],             []),
]

router = ToolRouter()
print("=== tool_category (schema → categoría) ===")
for name, cat in sorted(router.tool_category.items()):
    print(f"  {name:24} -> {cat}")
print()
fallos = 0

for msg, requeridos, prohibidos in CASOS:
    tools = router.route(msg)
    nombres = [t.get("function", {}).get("name", str(t)) if isinstance(t, dict) else str(t)
               for t in tools]
    blob = " ".join(nombres).lower()
    faltan = [r for r in requeridos if r not in blob]
    sobran = [p for p in prohibidos if p in blob]
    chars = len(json.dumps(tools, ensure_ascii=False))
    estado = "OK " if not faltan and not sobran else "FALLO"
    if estado == "FALLO":
        fallos += 1
    print(f"[{estado}] {msg[:52]:52} → {len(tools):2} tools · ~{chars // 4:4} tokens")
    if faltan:
        print(f"        faltan: {faltan}")
    if sobran:
        print(f"        prohibidas presentes: {sobran}")
    if estado == "FALLO":
        print(f"        enviadas: {nombres}")

print(f"\n{len(CASOS) - fallos}/{len(CASOS)} casos correctos")
sys.exit(1 if fallos else 0)
