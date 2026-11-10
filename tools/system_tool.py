import platform

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "system_info",
        "description": "USAR CUANDO el usuario pida un resumen BREVE del estado de su equipo ('estado de mi sistema', '¿qué equipo tengo?'). Devuelve 4 líneas: OS, CPU, RAM y disco. Para diagnóstico con carga, temperatura NVMe y advertencias usa la tool 'system_monitor' en su lugar.",
        "parameters": {"type": "object", "properties": {}}
    }
}
def execute() -> str:
    try:
        # Llamar al sistema_monitor para CPU, RAM y disco detallados
        from system_monitor import execute as monitor_execute
        result = monitor_execute()
        # Extraer solo las líneas principales de system_monitor para mantener compatibilidad
        lines = result.split('\n')
        cpu_line = [l for l in lines if 'CPU:' in l][0] if any('CPU:' in l for l in lines) else "CPU: Info no disponible"
        ram_line = [l for l in lines if 'RAM:' in l][0] if any('RAM:' in l for l in lines) else "RAM: Info no disponible"
        disk_line = [l for l in lines if 'Disco:' in l][0] if any('Disco:' in l for l in lines) else "Disco: Info no disponible"
        return f"OS: {platform.system()} {platform.release()}\n{cpu_line}\n{ram_line}\n{disk_line}\nPython: {platform.python_version()}"
    except Exception as e:
        # Fallback al original si hay error
        return f"OS: {platform.system()} {platform.release()} - {platform.version()}\nPython: {platform.python_version()}"
