from datetime import datetime, timezone
TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "get_current_time",
        "description": "USAR CUANDO el usuario pregunte la fecha o la hora ('¿qué hora es?', '¿qué día es hoy?') o cuando razonar sobre fechas actuales sea imprescindible (plazos, vencimientos, 'hace una semana'). Sin argumentos: devuelve hora local (La Paz, Baja California Sur, GMT-7) y UTC.",
        "parameters": {"type": "object", "properties": {}}
    }
}
def execute() -> str:
    now_local = datetime.now()
    return f"Fecha local: {now_local.strftime('%Y-%m-%d %H:%M:%S')} (La Paz, Baja California Sur, GMT-7)\nUTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"
