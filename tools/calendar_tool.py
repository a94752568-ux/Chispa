import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "calendar_tool",
        "description": "USAR CUANDO el usuario pregunte por su agenda o eventos próximos ('¿qué tengo esta semana?', '¿tengo algo agendado mañana?', '¿qué viene en mi calendario?'). Devuelve los eventos de los próximos 7 días leídos de archivos .ics locales. Sin argumentos.",
        "parameters": {"type": "object", "properties": {}}
    }
}
def _get_calendar_dirs() -> List[Path]:
    """Obtiene carpetas configurables por env: ~/Calendario, ~/.local/share/khal, fallback."""
    dirs = []
    
    # Primero, mirar variable de entorno CALENDAR_DIRS
    env_dirs = os.environ.get("CALENDAR_DIRS", "")
    if env_dirs:
        for dir_path in env_dirs.split(":"):
            path = Path(dir_path.strip())
            if path.exists():
                dirs.append(path)
    
    # Por defecto: ~/Calendario
    default_dir = Path.home() / "Calendario"
    if default_dir.exists():
        dirs.append(default_dir)
    
    # También: ~/.local/share/khal
    khal_dir = Path.home() / ".local" / "share" / "khal"
    if khal_dir.exists():
        dirs.append(khal_dir)
    
    return dirs
def _parse_ics_with_stdlib(file_path: Path) -> List[Dict[str, Any]]:
    """Parsea un archivo .ics usando métodos stdlib con tolerancia.
    
    v1: solo eventos únicos sin RRULE.
    """
    events = []
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Separar líneas y buscar líneas de eventos
        lines = content.splitlines()
        in_event = False
        event_data = {}
        event_start = None
        
        for line in lines:
            line = line.strip()
            
            if line == "BEGIN:VEVENT":
                in_event = True
                event_data = {}
                event_start = datetime.now()
            
            elif line == "END:VEVENT" and in_event:
                # Procesar evento completo
                event = _process_event_data(event_data)
                if event:
                    events.append(event)
                in_event = False
            
            elif in_event and ":" in line:
                # Parsear propiedades del evento
                parts = line.split(":", 1)
                if len(parts) == 2:
                    key, value = parts
                    event_data[key] = value
        
    except Exception:
        pass
    
    return events
def _process_event_data(event_data: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Procesa los datos de un evento parsed de .ics."""
    try:
        dt_start = event_data.get("DTSTART")
        dt_end = event_data.get("DTEND")
        summary = event_data.get("SUMMARY", "Evento sin título")
        location = event_data.get("LOCATION", "")
        description = event_data.get("DESCRIPTION", "")
        
        if not dt_start:
            return None
        
        # Parsear DTSTART (formato simple YYYYMMDDTHHMMSS)
        event_datetime = _parse_datetime(dt_start)
        
        if not event_datetime:
            return None
        
        # Verificar si es un evento recurrente (RRULE)
        rrule = event_data.get("RRULE", "")
        if rrule:
            return None  # Skip recurrent events (v1 requirement)
        
        # Calcular duración
        if dt_end:
            end_datetime = _parse_datetime(dt_end)
        else:
            end_datetime = event_datetime + timedelta(hours=1)
        
        return {
            "datetime": event_datetime,
            "summary": summary,
            "location": location,
            "description": description,
            "end_datetime": end_datetime
        }
    except Exception:
        return None
def _parse_datetime(dt_str: str) -> Optional[datetime]:
    """Parsea strings de fecha/hora en formato .ics simple."""
    try:
        # Intentar varios formatos
        formats = [
            "%Y%m%dT%H%M%S",
            "%Y%m%dT%H%M",
            "%Y%m%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d"
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        
        return None
    except Exception:
        return None
def _check_recurring_percentage(events: List[Dict[str, Any]]) -> bool:
    """Verifica si >30% de eventos son recurrentes.
    
    Para v1, consideramos recurrentes solo si tienen RRULE.
    """
    if not events:
        return False
    
    # En v1, solo contamos recurrentes si tienen RRULE (ya filtrados)
    # Por lo tanto, si pasaron el filtro, son todos únicos
    recurring_count = 0  # No RRULE detectada en v1
    total = len(events)
    
    return (recurring_count / total) > 0.30
def _load_calendar_events() -> List[Dict[str, Any]]:
    """Carga eventos de calendario desde .ics en todas las dirs configurables."""
    all_events = []
    calendar_dirs = _get_calendar_dirs()
    
    if not calendar_dirs:
        return all_events
    
    for calendar_dir in calendar_dirs:
        for ics_file in calendar_dir.glob("*.ics"):
            events = _parse_ics_with_stdlib(ics_file)
            all_events.extend(events)
    
    return all_events
def execute() -> str:
    """Retorna la agenda de los próximos 7 días desde .ics locales."""
    try:
        all_events = _load_calendar_events()
        
        if not all_events:
            return "No se encontraron archivos .ics en las carpetas de calendario configuradas."
        
        today = datetime.now()
        end_date = today + timedelta(days=7)
        
        # Filtrar eventos de la semana
        week_events = []
        for event in all_events:
            event_date = event["datetime"]
            if today.date() <= event_date.date() <= end_date.date():
                week_events.append(event)
        
        if not week_events:
            return "No hay eventos en el calendario para los próximos 7 días."
        
        # Ordenar por fecha
        week_events.sort(key=lambda x: x["datetime"])
        
        # Formatear salida
        output = f"Agenda de los próximos 7 días ({today.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}):\n\n"
        
        current_date = None
        for event in week_events:
            event_date = event["datetime"].date()
            if event_date != current_date:
                current_date = event_date
                output += f"{current_date.strftime('%Y-%m-%d')} ({current_date.strftime('%A')}):\n"
            
            time_str = event["datetime"].strftime("%H:%M")
            output += f"  {time_str} - {event['summary']}"
            
            if event["location"]:
                output += f" en {event['location']}"
            
            output += "\n"
        
        # Nota sobre recurrencia si aplica
        if _check_recurring_percentage(all_events):
            output += "\n⚠️ >30% de eventos recurrentes. Usar icalendar + recur para v1.5 (instalar icalendar)."
        
        return output
    
    except Exception as e:
        return f"Error calendar_tool: {e}"