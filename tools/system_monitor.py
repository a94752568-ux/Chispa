import os
import shutil
from pathlib import Path

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "system_monitor",
        "description": "Monitorea estado del sistema: CPU, RAM, disco, temp NVMe y carga. Advierte si >85% uso.",
        "parameters": {"type": "object", "properties": {}}
    }
}
def get_nvme_temperature():
    """Get NVMe temperature from /sys/class/nvme/*/hwmon if available."""
    try:
        nvme_dirs = Path("/sys/class/nvme").glob("*")
        for nvme_dir in nvme_dirs:
            hwmon_dir = nvme_dir / "hwmon"
            if hwmon_dir.exists():
                for temp_file in hwmon_dir.glob("temp*_input"):
                    try:
                        with open(temp_file, "r") as f:
                            temp_milli_c = int(f.read().strip())
                            temp_c = temp_milli_c / 1000.0
                            return f"{temp_c:.1f}°C"
                    except (ValueError, IOError):
                        continue
    except Exception:
        pass
    return None
def execute() -> str:
    try:
        # CPU from /proc/stat
        with open("/proc/stat", "r") as f:
            for line in f:
                if line.startswith("cpu "):
                    parts = line.split()
                    user, nice, system, idle, iowait, irq, softirq, steal, guest, guest_nice = map(int, parts[1:])
                    total = user + nice + system + idle + iowait + irq + softirq + steal
                    idle_total = idle + iowait
                    cpu_percent = 100.0 * (total - idle_total) / total if total > 0 else 0.0
                    break
        
        # RAM from /proc/meminfo
        with open("/proc/meminfo", "r") as f:
            mem_info = {}
            for line in f:
                if ":" in line:
                    key, val = line.split(":")
                    mem_info[key.strip()] = val.strip().split()[0]
        
        total_mem = int(mem_info.get("MemTotal", 0))
        free_mem = int(mem_info.get("MemFree", 0))
        buffers = int(mem_info.get("Buffers", 0))
        cached = int(mem_info.get("Cached", 0))
        available = int(mem_info.get("MemAvailable", free_mem + buffers + cached))
        
        used_ram = total_mem - available
        ram_percent = 100.0 * used_ram / total_mem if total_mem > 0 else 0.0
        
        # Disk from shutil.disk_usage
        disk = shutil.disk_usage("/")
        disk_percent = 100.0 * disk.used / disk.total if disk.total > 0 else 0.0
        
        # Load average from /proc/loadavg
        with open("/proc/loadavg", "r") as f:
            load_line = f.read().strip()
            load_parts = load_line.split()
            load_1min = float(load_parts[0])
            load_5min = float(load_parts[1])
            load_15min = float(load_parts[2])
        
        # NVMe temperature (optional)
        temp = get_nvme_temperature()
        temp_text = f", Temp: {temp}" if temp else ""
        
        # Warnings
        warnings = []
        if cpu_percent > 85:
            warnings.append(f"CPU {cpu_percent:.1f}% > 85%")
        if ram_percent > 85:
            warnings.append(f"RAM {ram_percent:.1f}% > 85%")
        if disk_percent > 85:
            warnings.append(f"Disco {disk_percent:.1f}% > 85%")
        
        warning_text = f"\n⚠️ Alertas: {', '.join(warnings)}" if warnings else ""
        
        result = (
            f"Estado del sistema:\n"
            f"  CPU: {cpu_percent:.1f}%"
            f", RAM: {ram_percent:.1f}% ({used_ram//1024//1024}MB/{total_mem//1024//1024}MB)"
            f", Disco: {disk_percent:.1f}% ({disk.used//1024//1024//1024}GB/{disk.total//1024//1024//1024}GB)"
            f", Carga 1min: {load_1min:.2f}{temp_text}"
            f"{warning_text}"
        )
        
        return result
        
    except Exception as e:
        return f"Error monitoreando sistema: {e}"