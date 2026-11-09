from datetime import datetime, timezone
TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "get_current_time",
        "description": "Obtiene fecha y hora actual en La Paz, Mexico y UTC",
        "parameters": {"type": "object", "properties": {}}
    }
}
def execute() -> str:
    now_local = datetime.now()
    return f"Fecha local: {now_local.strftime('%Y-%m-%d %H:%M:%S')} (La Paz, Baja California Sur, GMT-7)\nUTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"
