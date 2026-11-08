"""
Plantilla para crear tu propia funcion.

1. Copia este archivo a mi_tool.py
2. Cambia TOOL_DEFINITION name y description
3. Implementa execute()

El sistema lo detecta automaticamente al reiniciar la app.
"""
TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "mi_tool",
        "description": "Descripcion de lo que hace tu tool",
        "parameters": {
            "type": "object",
            "properties": {
                "arg1": {"type": "string", "description": "Argumento 1"}
            },
            "required": ["arg1"]
        }
    }
}

def execute(arg1: str) -> str:
    return f"Ejecutado mi_tool con {arg1}"
