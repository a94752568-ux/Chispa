import platform, psutil, shutil
TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "system_info",
        "description": "Obtiene informacion del sistema Lubuntu: CPU, RAM, disco, OS",
        "parameters": {"type": "object", "properties": {}}
    }
}
def execute() -> str:
    try:
        import psutil
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return f"OS: {platform.system()} {platform.release()}\nCPU: {platform.processor()}\nRAM: {ram.percent}% usado ({ram.used//1024//1024}MB/{ram.total//1024//1024}MB)\nDisco: {disk.percent}% usado\nPython: {platform.python_version()}"
    except:
        return f"OS: {platform.system()} {platform.release()} - {platform.version()}\nPython: {platform.python_version()}"
